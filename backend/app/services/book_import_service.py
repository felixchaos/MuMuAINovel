"""拆书导入服务：任务管理、预览构建与落库执行"""
from __future__ import annotations

import asyncio
import json
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.common import verify_project_access
from app.config import PROJECT_ROOT, settings as app_settings
from app.database import get_engine
from app.logger import get_logger
from app.models.chapter import Chapter
from app.models.character import Character
from app.models.background_task import BackgroundTask
from app.models.career import Career, CharacterCareer
from app.models.foreshadow import Foreshadow
from app.models.mcp_plugin import MCPPlugin
from app.models.outline import Outline
from app.models.project import Project
from app.models.project_default_style import ProjectDefaultStyle
from app.models.relationship import CharacterRelationship, Organization, OrganizationMember, RelationshipType
from app.models.settings import Settings
from app.models.writing_style import WritingStyle
from app.schemas.book_import import (
    BookImportApplyRequest,
    BookImportApplyResponse,
    BookImportChapter,
    BookImportEntityCandidate,
    BookImportExtractMode,
    BookImportOutline,
    BookImportPreviewResponse,
    BookImportSetupMode,
    BookImportTaskCreateResponse,
    BookImportTaskStatusResponse,
    BookImportTokenBudget,
    BookImportTokenBudgetStage,
    BookImportWarning,
    ProjectSuggestion,
)
from app.services.ai_service import AIService, create_user_ai_service_with_mcp
from app.services.background_task_service import background_task_service
from app.services.name_authority_service import is_generic_reference
from app.services.prompt_service import PromptService
from app.services.txt_parser_service import txt_parser_service

logger = get_logger(__name__)

BOOK_IMPORT_TASK_TYPE = "book_import_parse"
BOOK_IMPORT_PROJECT_PLACEHOLDER = "__book_import__"
BOOK_IMPORT_PREVIEW_SCHEMA_VERSION = 1
BOOK_IMPORT_PREVIEW_STORAGE_DIR = PROJECT_ROOT / "storage" / "book_import_previews"


@dataclass
class _StepFailure:
    """记录某个生成步骤的失败信息"""
    step_name: str          # 步骤标识: world_building / career_system / characters
    step_label: str         # 步骤中文名
    error_message: str      # 错误详情
    retry_count: int = 0    # 已重试次数


@dataclass
class _BookImportTask:
    task_id: str
    user_id: str
    filename: str
    project_id: Optional[str]
    create_new_project: bool
    import_mode: str
    extract_mode: BookImportExtractMode = "tail"
    tail_chapter_count: int = 10
    setup_mode: BookImportSetupMode = "auto"
    status: str = "pending"
    progress: int = 0
    message: Optional[str] = "任务已创建"
    error: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    preview: Optional[BookImportPreviewResponse] = None
    preview_storage_path: Optional[str] = None
    cancelled: bool = False
    background_task_id: Optional[str] = None
    # 导入后生成的 project_id，用于重试时定位项目
    imported_project_id: Optional[str] = None
    # 步骤级失败记录
    failed_steps: list[_StepFailure] = field(default_factory=list)


class BookImportService:
    """拆书导入服务：BackgroundTask 管生命周期，预览结果落临时持久化。"""

    def __init__(self) -> None:
        self._tasks: dict[str, _BookImportTask] = {}
        self._tasks_lock = asyncio.Lock()

    async def create_task(
        self,
        *,
        user_id: str,
        filename: str,
        file_content: bytes,
        project_id: Optional[str],
        create_new_project: bool,
        import_mode: str,
        extract_mode: BookImportExtractMode = "tail",
        tail_chapter_count: int = 10,
        setup_mode: BookImportSetupMode = "auto",
        db: AsyncSession,
    ) -> BookImportTaskCreateResponse:
        normalized_tail_count = max(5, int(tail_chapter_count))
        normalized_extract_mode = extract_mode
        if normalized_tail_count % 5 != 0:
            normalized_tail_count = ((normalized_tail_count + 4) // 5) * 5
        if normalized_tail_count > 50:
            normalized_extract_mode = "full"

        background_task = await background_task_service.create_task(
            user_id=user_id,
            project_id=project_id or BOOK_IMPORT_PROJECT_PLACEHOLDER,
            task_type=BOOK_IMPORT_TASK_TYPE,
            task_input={
                "filename": filename,
                "project_id": project_id,
                "create_new_project": create_new_project,
                "import_mode": import_mode,
                "extract_mode": normalized_extract_mode,
                "tail_chapter_count": normalized_tail_count,
                "setup_mode": setup_mode,
            },
            db=db,
        )

        task_id = background_task.id
        task = _BookImportTask(
            task_id=task_id,
            user_id=user_id,
            filename=filename,
            project_id=project_id,
            create_new_project=create_new_project,
            import_mode=import_mode,
            extract_mode=normalized_extract_mode,
            tail_chapter_count=normalized_tail_count,
            setup_mode=setup_mode,
            background_task_id=background_task.id,
            preview_storage_path=str(self._get_preview_storage_path(user_id=user_id, task_id=task_id)),
        )
        async with self._tasks_lock:
            self._tasks[task_id] = task

        asyncio.create_task(self._run_pipeline(task_id=task_id, file_content=file_content))
        return BookImportTaskCreateResponse(task_id=task_id, status=background_task.status or "pending")

    async def get_task_status(self, *, task_id: str, user_id: str) -> BookImportTaskStatusResponse:
        task = await self._get_task(task_id=task_id, user_id=user_id)
        return self._to_status(task)

    async def get_preview(self, *, task_id: str, user_id: str) -> BookImportPreviewResponse:
        task = await self._get_task(task_id=task_id, user_id=user_id)
        if task.status != "completed":
            raise HTTPException(status_code=400, detail="任务尚未完成，无法获取预览")
        preview = await self._ensure_task_preview_loaded(task)
        if not preview:
            raise HTTPException(status_code=410, detail="预览缓存已失效，请重新上传TXT解析")
        return preview

    async def cancel_task(self, *, task_id: str, user_id: str) -> dict:
        task = await self._get_task(task_id=task_id, user_id=user_id)
        if task.status in {"completed", "failed", "cancelled"}:
            return {"success": True, "message": f"任务已是终态：{task.status}"}

        task.cancelled = True
        self._set_task_state(task, status="cancelled", progress=task.progress, message="任务已取消")
        await self._persist_background_task_state(task)
        return {"success": True, "message": "取消成功"}

    async def apply_import(
        self,
        *,
        task_id: str,
        user_id: str,
        payload: BookImportApplyRequest,
        db: AsyncSession,
    ) -> BookImportApplyResponse:
        task = await self._get_task(task_id=task_id, user_id=user_id)
        if task.status != "completed":
            raise HTTPException(status_code=400, detail="任务未完成，无法导入")

        statistics = {
            "chapters": 0,
            "outlines": 0,
        }

        preview = await self._ensure_task_preview_loaded(task)
        warnings = list(preview.warnings) if preview else []
        chapters_to_import, outlines_to_import, was_trimmed = self._select_chapters_for_import(
            chapters=payload.chapters,
            outlines=payload.outlines,
            extract_mode=task.extract_mode,
            tail_chapter_count=task.tail_chapter_count,
        )
        if was_trimmed:
            warnings.append(
                BookImportWarning(
                    code="apply_trimmed_for_extract_mode",
                    message=f"导入阶段已按解析配置仅保留 {len(chapters_to_import)} 章",
                    level="info",
                )
            )

        try:
            project = await self._prepare_project(
                db=db,
                user_id=user_id,
                task=task,
                suggestion=payload.project_suggestion,
                chapters=chapters_to_import,
                import_mode=payload.import_mode,
            )

            outline_id_map = await self._import_outlines(
                db=db,
                project_id=project.id,
                outlines=outlines_to_import,
                import_mode=payload.import_mode,
            )
            statistics["outlines"] = len(outlines_to_import)

            chapter_count, words_delta = await self._import_chapters(
                db=db,
                project_id=project.id,
                chapters=chapters_to_import,
                outline_id_map=outline_id_map,
                import_mode=payload.import_mode,
            )
            statistics["chapters"] = chapter_count

            candidate_stats = await self._import_entity_candidates(
                db=db,
                project_id=project.id,
                candidates=payload.entity_candidates,
            )
            statistics.update(candidate_stats)

            if payload.import_mode == "overwrite":
                project.current_words = words_delta
            else:
                project.current_words = (project.current_words or 0) + words_delta

            if payload.post_import_generation == "manual":
                project.wizard_step = 3
                project.wizard_status = "completed"
                project.status = "writing"
                statistics["generated_world_building"] = 0
                statistics["generated_careers"] = 0
                statistics["generated_entities"] = 0
            else:
                # 基于基础信息执行"向导前3步"（先生成世界观 -> 生成职业 -> 生成角色/组织），不生成大纲
                generated_world, generated_careers, generated_entities = await self._run_post_import_wizard_generation(
                    db=db,
                    user_id=user_id,
                    project=project,
                    character_count=max(project.character_count or 0, 5),
                    chapters=chapters_to_import,
                )
                statistics["generated_world_building"] = generated_world
                statistics["generated_careers"] = generated_careers
                statistics["generated_entities"] = generated_entities

            await db.commit()

            return BookImportApplyResponse(
                success=True,
                project_id=project.id,
                statistics=statistics,
                warnings=warnings,
            )
        except HTTPException:
            await db.rollback()
            raise
        except Exception as exc:
            await db.rollback()
            logger.error(f"拆书导入落库失败: {exc}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"导入失败: {exc}")

    # ---- 类型别名：进度回调 ----
    ProgressCallback = Optional[Any]  # Callable[[str, int, str], Awaitable[None]]

    async def apply_import_stream(
        self,
        *,
        task_id: str,
        user_id: str,
        payload: BookImportApplyRequest,
        db: AsyncSession,
        progress_callback: Any = None,
    ) -> BookImportApplyResponse:
        """
        与 apply_import 相同的落库逻辑，但通过 progress_callback 推送细粒度进度。
        progress_callback(message: str, progress: int, status: str)
        """
        task = await self._get_task(task_id=task_id, user_id=user_id)
        if task.status != "completed":
            raise HTTPException(status_code=400, detail="任务未完成，无法导入")

        statistics: Dict[str, int] = {
            "chapters": 0,
            "outlines": 0,
        }

        preview = await self._ensure_task_preview_loaded(task)
        warnings = list(preview.warnings) if preview else []
        chapters_to_import, outlines_to_import, was_trimmed = self._select_chapters_for_import(
            chapters=payload.chapters,
            outlines=payload.outlines,
            extract_mode=task.extract_mode,
            tail_chapter_count=task.tail_chapter_count,
        )
        if was_trimmed:
            warnings.append(
                BookImportWarning(
                    code="apply_trimmed_for_extract_mode",
                    message=f"导入阶段已按解析配置仅保留 {len(chapters_to_import)} 章",
                    level="info",
                )
            )

        async def _notify(message: str, progress: int, status: str = "processing") -> None:
            if progress_callback:
                await progress_callback(message, progress, status)

        try:
            # -- 步骤1: 创建项目 (0-5%)
            await _notify("正在创建项目...", 2)
            project = await self._prepare_project(
                db=db,
                user_id=user_id,
                task=task,
                suggestion=payload.project_suggestion,
                chapters=chapters_to_import,
                import_mode=payload.import_mode,
            )
            await _notify("项目创建完成", 5)

            # -- 步骤2: 导入大纲 (5-10%)
            await _notify("正在导入大纲...", 6)
            outline_id_map = await self._import_outlines(
                db=db,
                project_id=project.id,
                outlines=outlines_to_import,
                import_mode=payload.import_mode,
            )
            statistics["outlines"] = len(outlines_to_import)
            await _notify(f"已导入 {len(outlines_to_import)} 个大纲", 10)

            # -- 步骤3: 导入章节 (10-20%)
            await _notify(f"正在导入 {len(chapters_to_import)} 个章节...", 12)
            chapter_count, words_delta = await self._import_chapters(
                db=db,
                project_id=project.id,
                chapters=chapters_to_import,
                outline_id_map=outline_id_map,
                import_mode=payload.import_mode,
            )
            statistics["chapters"] = chapter_count

            candidate_stats = await self._import_entity_candidates(
                db=db,
                project_id=project.id,
                candidates=payload.entity_candidates,
            )
            statistics.update(candidate_stats)

            if payload.import_mode == "overwrite":
                project.current_words = words_delta
            else:
                project.current_words = (project.current_words or 0) + words_delta
            imported_candidates = candidate_stats.get("imported_entity_candidates", 0)
            candidate_suffix = f"，确认实体 {imported_candidates} 个" if imported_candidates else ""
            await _notify(f"已导入 {chapter_count} 个章节（{words_delta}字）{candidate_suffix}", 20)

            if payload.post_import_generation == "manual":
                statistics["generated_world_building"] = 0
                statistics["generated_careers"] = 0
                statistics["generated_entities"] = 0
                project.wizard_step = 3
                project.wizard_status = "completed"
                project.status = "writing"

                await _notify("已选择手动设定模式，跳过AI生成世界观/职业/角色", 92, "info")
                await _notify("正在保存到数据库...", 95)
                await db.commit()
                await _notify("数据保存完成", 98)

                task.imported_project_id = project.id
                task.failed_steps = []
                task.updated_at = datetime.utcnow()
                await self._persist_background_task_state(task)

                return BookImportApplyResponse(
                    success=True,
                    project_id=project.id,
                    statistics=statistics,
                    warnings=warnings,
                )

            # -- 步骤4: 生成世界观 (20-40%)
            failed_steps: list[_StepFailure] = []

            await _notify("🌍 正在生成世界观...", 22)
            try:
                generated_world = await self._generate_world_building_from_project(
                    db=db,
                    user_id=user_id,
                    project=project,
                    progress_callback=progress_callback,
                    progress_range=(22, 40),
                    raise_on_error=True,
                )
                statistics["generated_world_building"] = generated_world
                await _notify("🌍 世界观生成完成", 40)
            except Exception as exc:
                logger.warning(f"拆书导入：世界观生成失败（将继续后续步骤）: {exc}")
                failed_steps.append(_StepFailure(
                    step_name="world_building",
                    step_label="世界观生成",
                    error_message=str(exc),
                ))
                await _notify(f"⚠️ 世界观生成失败：{str(exc)[:80]}，将继续后续步骤", 40, "warning")

            # -- 步骤5: 生成职业体系 (40-65%)
            await _notify("💼 正在生成职业体系...", 42)
            try:
                generated_careers = await self._generate_career_system_from_project(
                    db=db,
                    user_id=user_id,
                    project=project,
                    progress_callback=progress_callback,
                    progress_range=(42, 65),
                )
                statistics["generated_careers"] = generated_careers
                await _notify(f"💼 职业体系生成完成（{generated_careers}个）", 65)
            except Exception as exc:
                logger.warning(f"拆书导入：职业体系生成失败（将继续后续步骤）: {exc}")
                failed_steps.append(_StepFailure(
                    step_name="career_system",
                    step_label="职业体系生成",
                    error_message=str(exc),
                ))
                await _notify(f"⚠️ 职业体系生成失败：{str(exc)[:80]}，将继续后续步骤", 65, "warning")

            # -- 步骤6: 生成角色/组织 (65-92%)
            character_count_target = max(project.character_count or 0, 5)
            await _notify("👥 正在生成角色与组织...", 67)
            try:
                generated_entities = await self._generate_characters_and_organizations_from_project(
                    db=db,
                    user_id=user_id,
                    project=project,
                    count=character_count_target,
                    progress_callback=progress_callback,
                    progress_range=(67, 92),
                    source_chapters=chapters_to_import,
                )
                statistics["generated_entities"] = generated_entities
                await _notify(f"👥 角色/组织生成完成（{generated_entities}个）", 92)
            except Exception as exc:
                logger.warning(f"拆书导入：角色/组织生成失败: {exc}")
                failed_steps.append(_StepFailure(
                    step_name="characters",
                    step_label="角色与组织生成",
                    error_message=str(exc),
                ))
                await _notify(f"⚠️ 角色/组织生成失败：{str(exc)[:80]}", 92, "warning")

            # 标记向导完成并将项目置为创作中
            project.wizard_step = 3
            project.wizard_status = "completed"
            project.status = "writing"

            # -- 步骤7: 提交数据库 (92-98%)
            await _notify("正在保存到数据库...", 95)
            await db.commit()
            await _notify("数据保存完成", 98)

            # 记录失败步骤和项目ID到任务中，供重试使用
            task.imported_project_id = project.id
            task.failed_steps = failed_steps
            task.updated_at = datetime.utcnow()
            await self._persist_background_task_state(task)

            # 如果有步骤失败，通过 SSE 推送失败步骤详情
            if failed_steps:
                failed_info = [
                    {"step_name": f.step_name, "step_label": f.step_label, "error": f.error_message}
                    for f in failed_steps
                ]
                await _notify(
                    f"⚠️ 导入完成，但有 {len(failed_steps)} 个生成步骤失败，可点击重试",
                    98,
                    "warning",
                )
                # 通过特殊的 progress 消息推送失败步骤列表
                if progress_callback:
                    await progress_callback(
                        json.dumps({"failed_steps": failed_info}, ensure_ascii=False),
                        98,
                        "step_failures",
                    )

            return BookImportApplyResponse(
                success=True,
                project_id=project.id,
                statistics=statistics,
                warnings=warnings,
            )
        except HTTPException:
            await db.rollback()
            raise
        except Exception as exc:
            await db.rollback()
            logger.error(f"拆书导入落库失败: {exc}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"导入失败: {exc}")

    async def retry_failed_steps_stream(
        self,
        *,
        task_id: str,
        user_id: str,
        steps_to_retry: list[str],
        db: AsyncSession,
        progress_callback: Any = None,
    ) -> dict:
        """
        仅重试之前导入时失败的AI生成步骤。
        steps_to_retry: 需要重试的步骤名列表, 如 ["world_building", "career_system", "characters"]
        """
        task = await self._get_task(task_id=task_id, user_id=user_id)
        project_id = task.imported_project_id
        if not project_id:
            raise HTTPException(status_code=400, detail="该任务尚未完成导入，无法重试")

        # 验证 steps_to_retry 都是合法的失败步骤
        failed_step_names = {f.step_name for f in task.failed_steps}
        invalid_steps = [s for s in steps_to_retry if s not in failed_step_names]
        if invalid_steps:
            raise HTTPException(
                status_code=400,
                detail=f"以下步骤不在失败列表中，无法重试: {', '.join(invalid_steps)}",
            )

        async def _notify(message: str, progress: int, status: str = "processing") -> None:
            if progress_callback:
                await progress_callback(message, progress, status)

        try:
            from app.api.common import verify_project_access
            project = await verify_project_access(project_id, user_id, db)
            preview = await self._ensure_task_preview_loaded(task)

            retry_results: dict[str, Any] = {}
            still_failed: list[_StepFailure] = []
            total_steps = len(steps_to_retry)

            for step_idx, step_name in enumerate(steps_to_retry):
                step_start_pct = int(5 + (step_idx / total_steps) * 85)
                step_end_pct = int(5 + ((step_idx + 1) / total_steps) * 85)

                # 查找原来的失败记录
                original_failure = next((f for f in task.failed_steps if f.step_name == step_name), None)
                retry_count = (original_failure.retry_count if original_failure else 0) + 1

                if step_name == "world_building":
                    await _notify("🔄 正在重试世界观生成...", step_start_pct)
                    try:
                        result = await self._generate_world_building_from_project(
                            db=db,
                            user_id=user_id,
                            project=project,
                            progress_callback=progress_callback,
                            progress_range=(step_start_pct, step_end_pct),
                            raise_on_error=True,
                        )
                        retry_results["generated_world_building"] = result
                        await _notify("✅ 世界观重试成功", step_end_pct)
                    except Exception as exc:
                        logger.warning(f"世界观重试失败 (第{retry_count}次): {exc}")
                        still_failed.append(_StepFailure(
                            step_name="world_building",
                            step_label="世界观生成",
                            error_message=str(exc),
                            retry_count=retry_count,
                        ))
                        await _notify(f"⚠️ 世界观重试失败：{str(exc)[:80]}", step_end_pct, "warning")

                elif step_name == "career_system":
                    await _notify("🔄 正在重试职业体系生成...", step_start_pct)
                    try:
                        result = await self._generate_career_system_from_project(
                            db=db,
                            user_id=user_id,
                            project=project,
                            progress_callback=progress_callback,
                            progress_range=(step_start_pct, step_end_pct),
                        )
                        retry_results["generated_careers"] = result
                        await _notify(f"✅ 职业体系重试成功（{result}个）", step_end_pct)
                    except Exception as exc:
                        logger.warning(f"职业体系重试失败 (第{retry_count}次): {exc}")
                        still_failed.append(_StepFailure(
                            step_name="career_system",
                            step_label="职业体系生成",
                            error_message=str(exc),
                            retry_count=retry_count,
                        ))
                        await _notify(f"⚠️ 职业体系重试失败：{str(exc)[:80]}", step_end_pct, "warning")

                elif step_name == "characters":
                    character_count_target = max(project.character_count or 0, 5)
                    await _notify("🔄 正在重试角色与组织生成...", step_start_pct)
                    try:
                        result = await self._generate_characters_and_organizations_from_project(
                            db=db,
                            user_id=user_id,
                            project=project,
                            count=character_count_target,
                            progress_callback=progress_callback,
                            progress_range=(step_start_pct, step_end_pct),
                            source_chapters=preview.chapters if preview else None,
                        )
                        retry_results["generated_entities"] = result
                        await _notify(f"✅ 角色/组织重试成功（{result}个）", step_end_pct)
                    except Exception as exc:
                        logger.warning(f"角色/组织重试失败 (第{retry_count}次): {exc}")
                        still_failed.append(_StepFailure(
                            step_name="characters",
                            step_label="角色与组织生成",
                            error_message=str(exc),
                            retry_count=retry_count,
                        ))
                        await _notify(f"⚠️ 角色/组织重试失败：{str(exc)[:80]}", step_end_pct, "warning")

            # 提交数据库
            await _notify("正在保存到数据库...", 93)
            await db.commit()
            await _notify("数据保存完成", 96)

            # 更新任务的失败步骤记录
            task.failed_steps = still_failed
            task.updated_at = datetime.utcnow()
            await self._persist_background_task_state(task)

            if still_failed:
                failed_info = [
                    {"step_name": f.step_name, "step_label": f.step_label, "error": f.error_message, "retry_count": f.retry_count}
                    for f in still_failed
                ]
                if progress_callback:
                    await progress_callback(
                        json.dumps({"failed_steps": failed_info}, ensure_ascii=False),
                        98,
                        "step_failures",
                    )

            return {
                "success": True,
                "project_id": project_id,
                "retry_results": retry_results,
                "still_failed": [
                    {"step_name": f.step_name, "step_label": f.step_label, "error": f.error_message, "retry_count": f.retry_count}
                    for f in still_failed
                ],
            }
        except HTTPException:
            await db.rollback()
            raise
        except Exception as exc:
            await db.rollback()
            logger.error(f"拆书重试失败: {exc}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"重试失败: {exc}")

    async def _run_pipeline(self, *, task_id: str, file_content: bytes) -> None:
        task = self._tasks.get(task_id)
        if not task:
            return

        try:
            # 进度分配：编码识别 5%，文本清洗 10%，章节切分 15%，按配置筛选章节 18%，AI反向生成 20%-95%，完成 100%
            self._set_task_state(task, status="running", progress=5, message="正在识别编码并读取文本...")
            self._check_cancelled(task)

            text, encoding = txt_parser_service.decode_bytes(file_content)
            cleaned = txt_parser_service.clean_text(text)

            self._set_task_state(task, status="running", progress=10, message=f"文本清洗完成（编码：{encoding}）")
            self._check_cancelled(task)

            chapters_data, split_report = txt_parser_service.split_chapters_with_report(cleaned)
            if not chapters_data:
                raise ValueError("未能识别到有效章节，请检查TXT内容")

            self._set_task_state(
                task, status="running", progress=15,
                message=(
                    f"已识别 {len(chapters_data)} 个章节"
                    f"（{split_report.get('mode_label', '未知模式')}，置信度 {int(float(split_report.get('confidence') or 0) * 100)}%），"
                    "正在构建预览结构..."
                ),
            )
            self._check_cancelled(task)

            self._set_task_state(task, status="running", progress=18, message="正在按解析配置筛选章节并构建预览...")
            preview = await self._build_preview(
                task=task,
                filename=task.filename,
                task_id=task.task_id,
                chapters_data=chapters_data,
                split_report=split_report,
            )

            self._check_cancelled(task)
            task.preview = preview
            await self._save_preview_to_storage(task, preview)
            self._set_task_state(task, status="completed", progress=100, message="解析完成，可预览并确认导入")
        except asyncio.CancelledError:
            self._set_task_state(task, status="cancelled", progress=task.progress, message="任务已取消")
        except Exception as exc:
            logger.error(f"拆书任务失败 task_id={task_id}: {exc}", exc_info=True)
            self._set_task_state(
                task,
                status="failed",
                progress=task.progress,
                message="解析失败",
                error=str(exc),
            )
        finally:
            if task.status in {"completed", "failed", "cancelled"}:
                await self._persist_background_task_state(task)
                await self._drop_task_from_hot_cache(task.task_id)

    async def _prepare_project(
        self,
        *,
        db: AsyncSession,
        user_id: str,
        task: _BookImportTask,
        suggestion: ProjectSuggestion,
        chapters: list[BookImportChapter],
        import_mode: str,
    ) -> Project:
        world_time_period, world_location, world_atmosphere, world_rules = self._derive_world_settings(
            suggestion=suggestion,
            chapters=chapters,
        )
        world_time_period = (suggestion.world_time_period or world_time_period or "").strip()
        world_location = (suggestion.world_location or world_location or "").strip()
        world_atmosphere = (suggestion.world_atmosphere or world_atmosphere or "").strip()
        world_rules = (suggestion.world_rules or world_rules or "").strip()

        if task.create_new_project:
            project = Project(
                user_id=user_id,
                title=suggestion.title,
                description=suggestion.description,
                theme=suggestion.theme,
                genre=suggestion.genre,
                status="planning",
                wizard_status="incomplete",
                wizard_step=1,
                outline_mode="one-to-one",
                current_words=0,
                target_words=max(1000, int(suggestion.target_words or 100000)),
                narrative_perspective=(suggestion.narrative_perspective or "第三人称")[:50],
                world_time_period=world_time_period,
                world_location=world_location,
                world_atmosphere=world_atmosphere,
                world_rules=world_rules,
            )
            db.add(project)
            await db.flush()
            await self._ensure_project_default_style(db=db, project_id=project.id)
            return project

        if not task.project_id:
            raise HTTPException(status_code=400, detail="缺少目标项目ID")

        project = await verify_project_access(task.project_id, user_id, db)

        # 覆盖模式清空相关数据
        if import_mode == "overwrite":
            await self._clear_project_data(db=db, project_id=project.id)
            project.title = suggestion.title or project.title
            project.description = suggestion.description
            project.theme = suggestion.theme
            project.genre = suggestion.genre
            project.target_words = max(1000, int(suggestion.target_words or 100000))
            project.narrative_perspective = (suggestion.narrative_perspective or "第三人称")[:50]
            project.world_time_period = world_time_period
            project.world_location = world_location
            project.world_atmosphere = world_atmosphere
            project.world_rules = world_rules

        await self._ensure_project_default_style(db=db, project_id=project.id)
        return project

    async def _clear_project_data(self, *, db: AsyncSession, project_id: str) -> None:
        await db.execute(delete(Foreshadow).where(Foreshadow.project_id == project_id))
        await db.execute(delete(Chapter).where(Chapter.project_id == project_id))
        await db.execute(delete(Outline).where(Outline.project_id == project_id))

        # 覆盖导入时统一清理角色相关链路，避免后续自动生成出现脏数据
        char_ids_result = await db.execute(select(Character.id).where(Character.project_id == project_id))
        char_ids = [row[0] for row in char_ids_result.fetchall()]

        await db.execute(delete(CharacterRelationship).where(CharacterRelationship.project_id == project_id))
        await db.execute(delete(OrganizationMember).where(OrganizationMember.character_id.in_(char_ids)))
        await db.execute(delete(Organization).where(Organization.project_id == project_id))
        await db.execute(delete(CharacterCareer).where(CharacterCareer.character_id.in_(char_ids)))
        await db.execute(delete(Career).where(Career.project_id == project_id))
        await db.execute(delete(Character).where(Character.project_id == project_id))

    async def _ensure_project_default_style(self, *, db: AsyncSession, project_id: str) -> None:
        """确保项目存在默认写作风格（缺失时自动设置为首个全局预设风格）。"""
        existing_result = await db.execute(
            select(ProjectDefaultStyle.style_id).where(ProjectDefaultStyle.project_id == project_id)
        )
        if existing_result.scalar_one_or_none() is not None:
            return

        preset_result = await db.execute(
            select(WritingStyle.id, WritingStyle.name)
            .where(WritingStyle.user_id.is_(None))
            .order_by(func.coalesce(WritingStyle.order_index, 999999), WritingStyle.id)
            .limit(1)
        )
        preset_row = preset_result.first()
        if not preset_row:
            logger.warning(f"项目 {project_id} 未找到可用全局预设风格，跳过默认风格设置")
            return

        style_id, style_name = preset_row
        db.add(ProjectDefaultStyle(project_id=project_id, style_id=style_id))
        logger.info(f"项目 {project_id} 自动设置默认写作风格: {style_name}(id={style_id})")

    async def _import_outlines(
        self,
        *,
        db: AsyncSession,
        project_id: str,
        outlines: list[BookImportOutline],
        import_mode: str,
    ) -> dict[str, str]:
        if not outlines:
            return {}

        existing_max_order = 0
        if import_mode == "append":
            res = await db.execute(select(func.max(Outline.order_index)).where(Outline.project_id == project_id))
            existing_max_order = res.scalar_one() or 0

        title_to_id: dict[str, str] = {}
        for idx, item in enumerate(outlines, start=1):
            outline_content = item.content
            if not outline_content and item.structure and isinstance(item.structure, dict):
                outline_content = str(item.structure.get("summary") or item.structure.get("content") or "").strip()

            outline = Outline(
                project_id=project_id,
                title=item.title,
                content=outline_content,
                structure=json.dumps(item.structure, ensure_ascii=False) if item.structure else None,
                order_index=(existing_max_order + idx),
            )
            db.add(outline)
            await db.flush()
            title_to_id[item.title] = outline.id

        return title_to_id

    async def _import_chapters(
        self,
        *,
        db: AsyncSession,
        project_id: str,
        chapters: list[BookImportChapter],
        outline_id_map: dict[str, str],
        import_mode: str,
    ) -> tuple[int, int]:
        if not chapters:
            return 0, 0

        chapter_number_offset = 0
        if import_mode == "append":
            res = await db.execute(select(func.max(Chapter.chapter_number)).where(Chapter.project_id == project_id))
            chapter_number_offset = res.scalar_one() or 0

        count = 0
        total_words = 0
        for item in sorted(chapters, key=lambda x: x.chapter_number):
            chapter_number = chapter_number_offset + item.chapter_number
            word_count = len(item.content or "")

            chapter = Chapter(
                project_id=project_id,
                title=item.title,
                content=item.content,
                summary=item.summary,
                chapter_number=chapter_number,
                word_count=word_count,
                status="draft",
                outline_id=outline_id_map.get(item.outline_title or ""),
                sub_index=1,
            )
            db.add(chapter)
            count += 1
            total_words += word_count

        return count, total_words

    async def _import_entity_candidates(
        self,
        *,
        db: AsyncSession,
        project_id: str,
        candidates: list[BookImportEntityCandidate],
    ) -> dict[str, int]:
        """将用户确认的拆书候选写入现有角色/组织表，地点/物品先保留为预览证据。"""
        stats = {
            "imported_entity_candidates": 0,
            "imported_candidate_characters": 0,
            "imported_candidate_organizations": 0,
            "skipped_entity_candidates": 0,
        }
        if not candidates:
            return stats

        existing_result = await db.execute(
            select(Character.name).where(Character.project_id == project_id)
        )
        existing_names = {
            str(row[0]).strip()
            for row in existing_result.fetchall()
            if row[0]
        }
        seen_names = set(existing_names)

        for candidate in candidates[:80]:
            name = str(candidate.name or "").strip()
            if (
                not name
                or len(name) > 100
                or candidate.entity_type not in {"character", "organization"}
                or name in seen_names
                or is_generic_reference(name)
            ):
                stats["skipped_entity_candidates"] += 1
                continue

            evidence_lines = [
                f"- {snippet.strip()}"
                for snippet in (candidate.evidence or [])[:3]
                if snippet and snippet.strip()
            ]
            source_parts = [
                "由拆书实体预扫描确认导入。",
                f"全文出现次数：{candidate.occurrence_count}",
                f"候选置信度：{int((candidate.confidence or 0) * 100)}%",
            ]
            if candidate.classification_reason:
                source_parts.append(f"分类依据：{candidate.classification_reason}")
            if candidate.first_chapter_number:
                source_parts.append(f"首次出现：第 {candidate.first_chapter_number} 章")
            if evidence_lines:
                source_parts.append("证据片段：\n" + "\n".join(evidence_lines))
            source_note = "\n".join(source_parts)

            is_organization = candidate.entity_type == "organization"
            character = Character(
                project_id=project_id,
                name=name[:100],
                is_organization=is_organization,
                role_type="supporting",
                personality=None if is_organization else "拆书预扫描候选，等待进一步整理。",
                background=source_note,
                organization_type="组织" if is_organization else None,
                organization_purpose=source_note if is_organization else None,
                traits=json.dumps(["拆书候选"], ensure_ascii=False),
            )
            db.add(character)
            await db.flush()

            if is_organization:
                organization = Organization(
                    character_id=character.id,
                    project_id=project_id,
                    member_count=0,
                    power_level=50,
                )
                db.add(organization)
                await db.flush()
                stats["imported_candidate_organizations"] += 1
            else:
                stats["imported_candidate_characters"] += 1

            seen_names.add(name)
            stats["imported_entity_candidates"] += 1

        return stats

    def _select_chapters_for_import(
        self,
        *,
        chapters: list[BookImportChapter],
        outlines: list[BookImportOutline],
        extract_mode: BookImportExtractMode,
        tail_chapter_count: int,
    ) -> tuple[list[BookImportChapter], list[BookImportOutline], bool]:
        if not chapters:
            return [], [], False

        sorted_chapters = sorted(chapters, key=lambda x: x.chapter_number)
        normalized_tail_count = max(5, int(tail_chapter_count))
        if normalized_tail_count > 50 or extract_mode == "full":
            selected = sorted_chapters
        else:
            normalized_tail_count = min(normalized_tail_count, len(sorted_chapters))
            selected = sorted_chapters[-normalized_tail_count:]

        was_trimmed = len(sorted_chapters) > len(selected)

        normalized_chapters: list[BookImportChapter] = []
        for idx, item in enumerate(selected, start=1):
            normalized_chapters.append(
                BookImportChapter(
                    title=item.title,
                    content=item.content,
                    summary=item.summary,
                    chapter_number=idx,
                    outline_title=item.outline_title or item.title,
                )
            )

        normalized_outlines: list[BookImportOutline] = []
        sorted_outlines = sorted(outlines, key=lambda x: x.order_index) if outlines else []
        if sorted_outlines:
            if extract_mode == "full":
                selected_outlines = sorted_outlines[:len(normalized_chapters)]
            else:
                selected_outlines = sorted_outlines[-len(normalized_chapters):]
            for idx, item in enumerate(selected_outlines, start=1):
                normalized_outlines.append(
                    BookImportOutline(
                        title=item.title,
                        content=item.content,
                        order_index=idx,
                        structure=item.structure,
                    )
                )

        while len(normalized_outlines) < len(normalized_chapters):
            chapter = normalized_chapters[len(normalized_outlines)]
            normalized_outlines.append(
                BookImportOutline(
                    title=chapter.outline_title or chapter.title,
                    content=chapter.summary,
                    order_index=len(normalized_outlines) + 1,
                    structure=self._build_fallback_outline_structure(chapter),
                )
            )

        for idx in range(min(len(normalized_chapters), len(normalized_outlines))):
            normalized_chapters[idx].outline_title = normalized_outlines[idx].title

        return normalized_chapters, normalized_outlines, was_trimmed

    def _select_raw_chapters_for_preview(
        self,
        *,
        chapters_data: list[dict],
        extract_mode: BookImportExtractMode,
        tail_chapter_count: int,
    ) -> tuple[list[dict], bool]:
        if not chapters_data:
            return [], False

        normalized_tail_count = max(5, int(tail_chapter_count))
        if normalized_tail_count > 50 or extract_mode == "full":
            return chapters_data, False

        normalized_tail_count = min(normalized_tail_count, len(chapters_data))

        selected = chapters_data[-normalized_tail_count:]
        return selected, len(selected) < len(chapters_data)

    def _get_extract_mode_label(self, extract_mode: BookImportExtractMode, selected_total: int) -> str:
        if extract_mode == "full" or selected_total > 50:
            return "整本"
        return f"末{selected_total}章"

    def _derive_world_settings(
        self,
        *,
        suggestion: ProjectSuggestion,
        chapters: list[BookImportChapter],
    ) -> tuple[str, str, str, str]:
        """根据拆书内容推断基础世界设定，确保新建项目有可用初始值。"""
        sample_parts: list[str] = [
            suggestion.title or "",
            suggestion.theme or "",
            suggestion.genre or "",
            suggestion.description or "",
        ]
        for chapter in chapters[:3]:
            if chapter.content:
                sample_parts.append(chapter.content[:1200])

        sample_text = "\n".join(sample_parts)
        genre = suggestion.genre or ""
        theme = suggestion.theme or ""

        time_period = self._detect_time_period(sample_text, genre)
        location = self._detect_location(sample_text, genre)
        atmosphere = self._detect_atmosphere(sample_text, genre, theme)
        rules = self._detect_world_rules(sample_text, genre)

        return time_period, location, atmosphere, rules

    def _detect_time_period(self, text: str, genre: str) -> str:
        if any(k in text for k in ("民国", "军阀", "北洋", "租界")):
            return "近代民国时期"
        if any(k in text for k in ("星际", "宇宙", "机甲", "赛博", "未来", "人工智能")):
            return "未来科技时代"
        if any(k in text for k in ("古代", "王朝", "皇帝", "后宫", "朝堂", "将军", "宗门", "修仙", "江湖", "武林")):
            return "古代架空时代"
        if any(k in text for k in ("校园", "大学", "高中", "公司", "都市", "地铁")):
            return "现代都市"

        if any(k in genre for k in ("科幻", "星际")):
            return "未来科技时代"
        if any(k in genre for k in ("仙侠", "玄幻", "武侠", "历史", "古言")):
            return "古代架空时代"
        return "现代都市（可在世界设定页调整）"

    def _detect_location(self, text: str, genre: str) -> str:
        if any(k in text for k in ("星际", "宇宙", "舰队", "空间站", "机甲")):
            return "多星系宇宙与舰队文明"
        if any(k in text for k in ("宗门", "仙门", "秘境", "灵脉", "江湖", "武林")):
            return "宗门林立的江湖/仙侠世界"
        if any(k in text for k in ("王朝", "都城", "皇宫", "边关", "朝堂")):
            return "王朝都城与边疆并存的古代世界"
        if any(k in text for k in ("校园", "大学", "高中")):
            return "校园与城市生活场景"
        if any(k in text for k in ("都市", "城市", "街区", "公司", "医院")):
            return "现代城市社会"

        if "悬疑" in genre:
            return "现代城市与封闭场景并行"
        return "以人物活动区域为核心的现实场景"

    def _detect_atmosphere(self, text: str, genre: str, theme: str) -> str:
        if any(k in text for k in ("悬疑", "谜", "诡", "凶案", "惊悚", "追查")):
            return "紧张悬疑、危机渐进"
        if any(k in text for k in ("热血", "战斗", "对决", "复仇", "战争")):
            return "高压对抗、节奏强烈"
        if any(k in text for k in ("治愈", "日常", "温馨", "轻松", "搞笑")):
            return "日常细腻、轻松温暖"
        if any(k in text for k in ("权谋", "宫斗", "朝堂", "家族斗争")):
            return "权谋博弈、暗流涌动"

        if "言情" in genre:
            return "情感拉扯、细腻克制"
        if theme:
            return f"{theme}导向、人物驱动"
        return "人物驱动、冲突递进"

    def _detect_world_rules(self, text: str, genre: str) -> str:
        if any(k in text for k in ("修仙", "玄幻", "灵气", "境界", "宗门", "飞升")) or any(k in genre for k in ("仙侠", "玄幻")):
            return "存在修炼体系与等级秩序，资源与传承决定势力格局。"
        if any(k in text for k in ("星际", "机甲", "赛博", "人工智能", "基因")) or any(k in genre for k in ("科幻", "星际")):
            return "科技规则主导社会运行，组织制度与技术能力决定角色行动边界。"
        if any(k in text for k in ("江湖", "门派", "武林", "侠客")) or "武侠" in genre:
            return "江湖门派秩序与恩怨规则并行，强者与名望影响话语权。"
        if any(k in text for k in ("王朝", "皇权", "朝堂", "礼法")) or any(k in genre for k in ("历史", "古言")):
            return "以礼法与权力秩序为基础，家国与阶层关系深刻影响人物命运。"
        return "以现实逻辑为基础，结合剧情推进逐步补充特殊设定。"

    def _strip_chapter_prefix(self, title: str) -> str:
        """移除章节标题前缀“第X章/节/回/卷”，保留真实标题。"""
        normalized = (title or "").strip()
        if not normalized:
            return normalized

        stripped = re.sub(
            r"^第\s*[0-9零一二三四五六七八九十百千万两〇]+\s*[章节回卷]\s*[-—:：、.．）)】\]]*\s*",
            "",
            normalized,
        ).strip()

        return stripped or normalized

    async def _build_preview(
        self,
        *,
        task: _BookImportTask,
        filename: str,
        task_id: str,
        chapters_data: list[dict],
        split_report: Optional[dict] = None,
    ) -> BookImportPreviewResponse:
        suggestion = ProjectSuggestion(
            title=Path(filename).stem[:200] or "拆书导入项目",
            description="由拆书功能自动生成，可在导入前修改",
            theme=None,
            genre=None,
            narrative_perspective="第三人称",
            target_words=100000,
        )

        chapters: list[BookImportChapter] = []
        warnings: list[BookImportWarning] = []
        if split_report:
            confidence = float(split_report.get("confidence") or 0)
            if confidence < 0.55:
                warnings.append(
                    BookImportWarning(
                        code="low_split_confidence",
                        message=(
                            f"章节切分置信度较低（{int(confidence * 100)}%，"
                            f"模式：{split_report.get('mode_label') or split_report.get('mode') or '未知'}），"
                            "建议导入前检查章节边界"
                        ),
                        level="warning",
                    )
                )
            for reason in (split_report.get("reasons") or [])[:5]:
                warnings.append(
                    BookImportWarning(
                        code="split_diagnostic",
                        message=str(reason),
                        level="info" if confidence >= 0.55 else "warning",
                    )
                )

        selected_chapters_raw, was_trimmed = self._select_raw_chapters_for_preview(
            chapters_data=chapters_data,
            extract_mode=task.extract_mode,
            tail_chapter_count=task.tail_chapter_count,
        )
        selected_total = len(selected_chapters_raw)
        selection_label = self._get_extract_mode_label(task.extract_mode, selected_total)

        title_counter: Counter[str] = Counter()
        for idx, chapter in enumerate(selected_chapters_raw, start=1):
            raw_title = (chapter.get("title") or f"第{idx}章").strip()[:200]
            title = self._strip_chapter_prefix(raw_title)[:200]
            content = (chapter.get("content") or "").strip()
            summary = self._build_summary(content)

            chapters.append(
                BookImportChapter(
                    title=title,
                    content=content,
                    summary=summary,
                    chapter_number=idx,
                    outline_title=title,
                )
            )

            title_counter[title] += 1
            if len(content) < 300:
                warnings.append(
                    BookImportWarning(
                        code="chapter_too_short",
                        message=f"章节「{title}」内容较短，建议检查切分结果",
                        level="warning",
                    )
                )
            if len(content) > 12000:
                warnings.append(
                    BookImportWarning(
                        code="chapter_too_long",
                        message=f"章节「{title}」内容较长，建议确认是否应继续拆分",
                        level="info",
                    )
                )

            # 章节构建进度：18% -> 20%（在这个区间内按比例推进）
            chapter_progress = 18 + int(2 * idx / max(1, selected_total))
            if idx % max(1, selected_total // 5) == 0 or idx == selected_total:
                self._set_task_state(
                    task,
                    status="running",
                    progress=chapter_progress,
                    message=f"已处理{selection_label} {idx}/{selected_total} 个章节结构...",
                )

        for title, count in title_counter.items():
            if count > 1:
                warnings.append(
                    BookImportWarning(
                        code="duplicate_chapter_title",
                        message=f"检测到重复章节标题「{title}」共 {count} 次",
                        level="warning",
                    )
                )

        entity_candidates = self._scan_import_entity_candidates(
            chapters=chapters,
            title=Path(filename).stem,
        )
        if task.setup_mode != "manual" and entity_candidates:
            self._set_task_state(
                task,
                status="running",
                progress=20,
                message="正在校正实体候选类型...",
            )
            entity_candidates = await self._classify_import_entity_candidates_with_ai(
                user_id=task.user_id,
                task=task,
                chapters=chapters,
                candidates=entity_candidates,
                title=Path(filename).stem,
            )

        if was_trimmed:
            warnings.append(
                BookImportWarning(
                    code="trimmed_for_extract_mode",
                    message=f"已按解析配置仅保留{selection_label} {selected_total} 章用于导入（原始识别 {len(chapters_data)} 章）",
                    level="info",
                )
            )

        token_budget = self._estimate_book_import_token_budget(
            chapters=chapters,
            setup_mode=task.setup_mode,
            entity_candidate_count=len(entity_candidates),
        )

        if task.setup_mode == "manual":
            self._set_task_state(
                task,
                status="running",
                progress=95,
                message="已选择手动设定模式，跳过AI反向生成项目信息与大纲...",
            )
            outlines = self._build_fallback_import_outlines(chapters)
            return BookImportPreviewResponse(
                task_id=task_id,
                project_suggestion=suggestion,
                chapters=chapters,
                outlines=outlines,
                warnings=warnings,
                split_report=split_report,
                entity_candidates=entity_candidates,
                token_budget=token_budget,
            )

        # AI 反向生成项目信息：进度 20% -> 95%
        self._set_task_state(
            task,
            status="running",
            progress=20,
            message="正在调用AI反向生成项目信息（标题/简介/主题/类型）...",
        )
        suggestion = await self._generate_reverse_project_suggestion(
            user_id=task.user_id,
            suggestion=suggestion,
            chapters=chapters,
            task=task,
        )

        outlines = await self._generate_reverse_outlines(
            user_id=task.user_id,
            suggestion=suggestion,
            chapters=chapters,
            task=task,
        )

        return BookImportPreviewResponse(
            task_id=task_id,
            project_suggestion=suggestion,
            chapters=chapters,
            outlines=outlines,
            warnings=warnings,
            split_report=split_report,
            entity_candidates=entity_candidates,
            token_budget=token_budget,
        )

    def _estimate_book_import_token_budget(
        self,
        *,
        chapters: list[BookImportChapter],
        setup_mode: BookImportSetupMode,
        entity_candidate_count: int,
    ) -> BookImportTokenBudget:
        """估算拆书预览阶段 Token 消耗；真实用量仍以 AIUsageLog 为准。"""
        if setup_mode == "manual":
            return BookImportTokenBudget(
                note=(
                    "手动设定模式只执行规则拆章与可编辑预览，不强制调用 AI。"
                    "后续点击字段润色/生成工具时，会按实际 AI 调用记录 token。"
                ),
            )

        stages: list[BookImportTokenBudgetStage] = []

        entity_prompt_chars = min(9000, sum(len(item.content or "") for item in chapters[:30]))
        entity_prompt_chars += min(entity_candidate_count, 40) * 180
        stages.append(
            self._build_token_budget_stage(
                stage="entity_classification",
                label="实体候选分类",
                prompt_chars=entity_prompt_chars,
                completion_chars=min(entity_candidate_count, 40) * 80,
                api_calls=1 if entity_candidate_count else 0,
            )
        )

        project_prompt_chars = sum(len((chapter.content or "")[:1600]) + len(chapter.title or "") for chapter in chapters[:3])
        stages.append(
            self._build_token_budget_stage(
                stage="reverse_project",
                label="反向生成项目信息",
                prompt_chars=project_prompt_chars + 1400,
                completion_chars=1200,
                api_calls=1,
            )
        )

        batch_size = 5
        for batch_index, start in enumerate(range(0, len(chapters), batch_size), start=1):
            batch = chapters[start: start + batch_size]
            prompt_chars = sum(len((chapter.content or "")[:2200]) + len(chapter.title or "") + 120 for chapter in batch)
            stages.append(
                self._build_token_budget_stage(
                    stage=f"reverse_outlines_batch_{batch_index}",
                    label=f"反向生成大纲 {batch_index}",
                    prompt_chars=prompt_chars + 900,
                    completion_chars=max(900, len(batch) * 520),
                    api_calls=1,
                )
            )

        prompt_tokens = sum(item.estimated_prompt_tokens for item in stages)
        completion_tokens = sum(item.estimated_completion_tokens for item in stages)
        api_calls = sum(item.api_calls for item in stages)
        return BookImportTokenBudget(
            estimated_prompt_tokens=prompt_tokens,
            estimated_completion_tokens=completion_tokens,
            estimated_total_tokens=prompt_tokens + completion_tokens,
            estimated_api_calls=api_calls,
            note=(
                "这是基于文本长度和拆书批次的粗略 token 预算，不作为真实计费。"
                "参考价格来自服务器每日缓存的 OpenRouter 模型价格，可能与供应商实时价格存在数小时差异。"
            ),
            stages=stages,
        )

    def _build_token_budget_stage(
        self,
        *,
        stage: str,
        label: str,
        prompt_chars: int,
        completion_chars: int,
        api_calls: int,
    ) -> BookImportTokenBudgetStage:
        prompt_tokens = self._estimate_tokens_from_text_length(prompt_chars)
        completion_tokens = self._estimate_tokens_from_text_length(completion_chars)
        return BookImportTokenBudgetStage(
            stage=stage,
            label=label,
            estimated_prompt_tokens=prompt_tokens,
            estimated_completion_tokens=completion_tokens,
            estimated_total_tokens=prompt_tokens + completion_tokens,
            api_calls=api_calls,
        )

    @staticmethod
    def _estimate_tokens_from_text_length(length: int) -> int:
        return max(0, int((max(0, length) + 1) / 1.7))

    def _scan_import_entity_candidates(
        self,
        *,
        chapters: list[BookImportChapter],
        title: str,
        limit: int = 40,
    ) -> list[BookImportEntityCandidate]:
        source_text = self._build_import_source_text(chapters, max_chars=120000)
        if not source_text:
            return []

        candidates: dict[tuple[str, str], BookImportEntityCandidate] = {}

        def add_candidate(name: str, entity_type: str, bonus: int = 0) -> None:
            normalized = str(name or "").strip()
            if not normalized or len(normalized) > 24 or is_generic_reference(normalized):
                return
            occurrence_count = source_text.count(normalized) + bonus
            if occurrence_count < 2:
                return

            first_chapter_number: Optional[int] = None
            evidence: list[str] = []
            for chapter in chapters:
                chapter_text = f"{chapter.title}\n{chapter.content or ''}"
                pos = chapter_text.find(normalized)
                if pos < 0:
                    continue
                first_chapter_number = chapter.chapter_number
                start = max(0, pos - 28)
                end = min(len(chapter_text), pos + len(normalized) + 42)
                snippet = " ".join(chapter_text[start:end].split())
                if snippet and snippet not in evidence:
                    evidence.append(snippet)
                if len(evidence) >= 2:
                    break

            key = (normalized, entity_type)
            existing = candidates.get(key)
            if not existing or occurrence_count > existing.occurrence_count:
                candidates[key] = BookImportEntityCandidate(
                    name=normalized,
                    entity_type=entity_type,  # type: ignore[arg-type]
                    occurrence_count=occurrence_count,
                    first_chapter_number=first_chapter_number,
                    evidence=evidence,
                    confidence=0.68 if entity_type in {"character", "organization"} else 0.58,
                    classification_reason="规则预扫描：名称模式与全文出现次数匹配",
                )

        for name in self._extract_import_source_name_candidates(
            source_text=source_text,
            title=title,
            limit=limit,
        ):
            add_candidate(name, "character")

        entity_patterns = [
            (
                "organization",
                r"([\u4e00-\u9fff]{2,18}(?:学院|学校|公司|集团|帝国|王国|联邦|舰队|军团|军|局|社|协会|组织|教会|家族|政府|部门|研究所))",
            ),
            (
                "location",
                r"([\u4e00-\u9fff]{2,18}(?:城|市|镇|村|港|岛|山|海|湖|街|路|站|馆|厅|教室|广场|码头|旅馆|酒馆|医院|图书馆))",
            ),
            (
                "item",
                r"([\u4e00-\u9fff]{2,18}(?:钥匙|戒指|项链|书|剑|刀|枪|舰|船|药剂|宝石|装置|芯片|信件|地图|笔记本))",
            ),
        ]

        for entity_type, pattern in entity_patterns:
            counter: Counter[str] = Counter()
            for match in re.finditer(pattern, source_text):
                candidate = str(match.group(1) or "").strip()
                if len(candidate) < 2 or len(candidate) > 24 or is_generic_reference(candidate):
                    continue
                counter[candidate] += 1
            for name, count in counter.most_common(20):
                add_candidate(name, entity_type, bonus=max(0, count - source_text.count(name)))

        ranked = sorted(
            candidates.values(),
            key=lambda item: (
                {"character": 0, "organization": 1, "location": 2, "item": 3, "unknown": 4}.get(item.entity_type, 9),
                -item.occurrence_count,
                item.first_chapter_number or 999999,
                item.name,
            ),
        )
        return ranked[:limit]

    async def _classify_import_entity_candidates_with_ai(
        self,
        *,
        user_id: str,
        task: Optional[_BookImportTask],
        chapters: list[BookImportChapter],
        candidates: list[BookImportEntityCandidate],
        title: str,
    ) -> list[BookImportEntityCandidate]:
        """用现有用户 AI 配置对规则候选做轻量分类；失败时保持规则结果。"""
        if not candidates:
            return candidates

        try:
            engine = await get_engine(user_id)
            session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
            async with session_factory() as db:
                ai_service = await self._build_user_ai_service(db=db, user_id=user_id)
                source_context = self._build_import_source_prompt_context(chapters, max_chars=9000)
                candidate_lines = []
                for idx, item in enumerate(candidates[:40], start=1):
                    evidence = " / ".join(item.evidence[:2]) or "无"
                    candidate_lines.append(
                        f"{idx}. name={item.name} | rule_type={item.entity_type} | "
                        f"occurrences={item.occurrence_count} | first_chapter={item.first_chapter_number or '未知'} | "
                        f"evidence={evidence[:260]}"
                    )

                prompt = f"""
你是中文小说拆书的实体候选分类器。请只校正候选列表中的实体类型，不要新增候选，不要改写候选名称。

分类规则：
- character：稳定人物、拟人化角色、明确具有人物行动的存在。
- organization：国家、军队、学校、公司、家族、舰队、部门、势力、组织。
- location：城市、区域、建筑、场所、道路、岛屿、港口等地点。
- item：道具、装备、舰船、文档、装置、药剂、武器、物件。
- unknown：泛称、代词、章节标题、误切文本、无法从证据判断的候选。

注意：
- “大哥、那人、前辈、老师、同学、少女、男人、女人”等泛称通常应为 unknown，除非证据明确它是稳定称谓。
- 只输出严格 JSON 数组，每项字段为：name、entity_type、confidence、reason。
- name 必须与候选完全一致，entity_type 必须是 character/organization/location/item/unknown 之一，confidence 为 0 到 1。

书名：{title or '未命名'}

候选列表：
{chr(10).join(candidate_lines)}

正文上下文节选：
{source_context}
""".strip()

                ai_items = await ai_service.call_with_json_retry(
                    prompt=prompt,
                    max_retries=2,
                    expected_type="array",
                    temperature=0.2,
                    max_tokens=2400,
                )

            by_name: dict[str, dict[str, Any]] = {}
            if isinstance(ai_items, list):
                for raw in ai_items:
                    if not isinstance(raw, dict):
                        continue
                    name = str(raw.get("name") or "").strip()
                    if name:
                        by_name[name] = raw

            valid_types = {"character", "organization", "location", "item", "unknown"}
            refined: list[BookImportEntityCandidate] = []
            for candidate in candidates:
                raw = by_name.get(candidate.name)
                if not raw:
                    refined.append(candidate)
                    continue

                entity_type = str(raw.get("entity_type") or candidate.entity_type).strip()
                if entity_type not in valid_types:
                    entity_type = candidate.entity_type

                try:
                    confidence = float(raw.get("confidence", candidate.confidence))
                except (TypeError, ValueError):
                    confidence = candidate.confidence
                confidence = max(0.0, min(1.0, confidence))
                reason = str(raw.get("reason") or "").strip()

                refined.append(
                    candidate.model_copy(
                        update={
                            "entity_type": entity_type,
                            "confidence": confidence,
                            "classification_reason": reason[:160] or candidate.classification_reason,
                        }
                    )
                )

            if task:
                self._set_task_state(task, status="running", progress=22, message="实体候选分类完成，继续生成预览...")

            return sorted(
                refined,
                key=lambda item: (
                    {"character": 0, "organization": 1, "location": 2, "item": 3, "unknown": 4}.get(item.entity_type, 9),
                    -item.confidence,
                    -item.occurrence_count,
                    item.first_chapter_number or 999999,
                    item.name,
                ),
            )
        except Exception as exc:
            logger.warning(f"AI实体候选分类失败，保留规则预扫描结果: {exc}")
            if task:
                self._set_task_state(task, status="running", progress=22, message="实体候选分类失败，使用规则预扫描结果")
            return candidates

    def _build_fallback_import_outlines(self, chapters: list[BookImportChapter]) -> list[BookImportOutline]:
        return [
            BookImportOutline(
                title=chapter.title,
                content=self._build_fallback_outline_summary(chapter),
                order_index=chapter.chapter_number,
                structure=self._build_fallback_outline_structure(chapter),
            )
            for chapter in chapters
        ]

    async def _generate_reverse_project_suggestion(
        self,
        *,
        user_id: str,
        suggestion: ProjectSuggestion,
        chapters: list[BookImportChapter],
        task: Optional[_BookImportTask] = None,
    ) -> ProjectSuggestion:
        """
        基于前3章内容反向生成项目信息：
        小说简介、主题、类型、叙事角度、目标字数（默认10W）。
        进度区间：20% -> 95%
        """
        fallback = self._build_fallback_project_suggestion(
            title=suggestion.title,
            chapters=chapters,
        )

        sampled_chapters = chapters[:3]
        sampled_text = "\n\n".join(
            f"【第{idx + 1}章 {chapter.title}】\n{(chapter.content or '')[:2000]}"
            for idx, chapter in enumerate(sampled_chapters)
        ).strip()

        if not sampled_text:
            if task:
                self._set_task_state(task, status="running", progress=95, message="文本样本不足，使用规则推断项目信息")
            return fallback

        try:
            if task:
                self._set_task_state(task, status="running", progress=25, message="正在初始化AI服务...")

            engine = await get_engine(user_id)
            session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
            async with session_factory() as db:
                ai_service = await self._build_user_ai_service(db=db, user_id=user_id)

                if task:
                    self._set_task_state(task, status="running", progress=30, message="正在准备AI提示词...")

                template = await PromptService.get_template("BOOK_IMPORT_REVERSE_PROJECT_SUGGESTION", user_id, db)
                prompt = PromptService.format_prompt(
                    template,
                    title=suggestion.title or "拆书导入项目",
                    sampled_text=sampled_text,
                )

                if task:
                    self._set_task_state(task, status="running", progress=35, message="AI正在分析文本内容...")

                # 启动一个模拟进度推进的协程，在AI调用期间持续更新进度
                ai_done = asyncio.Event()

                async def _progress_ticker() -> None:
                    """在AI生成期间，每2秒推进一次进度（35% -> 85%）"""
                    if not task:
                        return
                    current = 35
                    messages = [
                        "AI正在分析文本内容...",
                        "AI正在识别故事主题与类型...",
                        "AI正在推断叙事角度...",
                        "AI正在生成项目简介...",
                        "AI正在整理生成结果...",
                    ]
                    msg_idx = 0
                    while not ai_done.is_set() and current < 85:
                        await asyncio.sleep(2)
                        if ai_done.is_set():
                            break
                        current = min(current + 5, 85)
                        msg = messages[min(msg_idx, len(messages) - 1)]
                        msg_idx += 1
                        self._set_task_state(task, status="running", progress=current, message=msg)

                ticker_task = asyncio.create_task(_progress_ticker())

                try:
                    project_data = await ai_service.call_with_json_retry(
                        prompt=prompt,
                        max_retries=3,
                        expected_type="object",
                    )
                finally:
                    ai_done.set()
                    await ticker_task

                if task:
                    self._set_task_state(task, status="running", progress=90, message="AI生成完成，正在整理项目信息...")

                result = ProjectSuggestion(
                    title=suggestion.title,
                    description=(project_data.get("description") or fallback.description or "").strip(),
                    theme=(project_data.get("theme") or fallback.theme or "").strip() or fallback.theme,
                    genre=(project_data.get("genre") or fallback.genre or "").strip() or fallback.genre,
                    narrative_perspective=self._extract_narrative_perspective(
                        project_data,
                        fallback.narrative_perspective,
                    ),
                    target_words=self._normalize_target_words(
                        project_data.get("target_words"),
                        fallback.target_words,
                    ),
                )

                if task:
                    self._set_task_state(task, status="running", progress=95, message="项目信息生成完毕，准备预览...")

                return result
        except Exception as exc:
            logger.warning(f"反向生成项目信息失败，回退规则推断: {exc}")
            if task:
                self._set_task_state(task, status="running", progress=95, message="AI生成失败，使用规则推断项目信息")
            return fallback

    async def _generate_reverse_outlines(
        self,
        *,
        user_id: str,
        suggestion: ProjectSuggestion,
        chapters: list[BookImportChapter],
        task: Optional[_BookImportTask] = None,
    ) -> list[BookImportOutline]:
        """
        基于导入章节反向生成对应大纲，严格对齐现有 OUTLINE_CREATE 结构。
        采用单批次5章分批生成，避免一次性上下文过大。
        """
        if not chapters:
            return []

        fallback_outlines = self._build_fallback_import_outlines(chapters)

        try:
            if task:
                self._set_task_state(task, status="running", progress=95, message="正在反向生成章节大纲（分批5章）...")

            engine = await get_engine(user_id)
            session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
            async with session_factory() as db:
                ai_service = await self._build_user_ai_service(db=db, user_id=user_id)
                template = await PromptService.get_template("BOOK_IMPORT_REVERSE_OUTLINES", user_id, db)

                batch_size = 5
                total_batches = (len(chapters) + batch_size - 1) // batch_size
                all_structures: list[dict[str, Any]] = []

                for batch_idx, start in enumerate(range(0, len(chapters), batch_size), start=1):
                    batch = chapters[start: start + batch_size]
                    if not batch:
                        continue

                    start_chapter = batch[0].chapter_number
                    end_chapter = batch[-1].chapter_number
                    chapters_text = self._build_reverse_outline_chapters_text(batch)
                    expected_count = len(batch)

                    if task:
                        progress = 95 + int(3 * (batch_idx - 1) / max(1, total_batches))
                        self._set_task_state(
                            task,
                            status="running",
                            progress=progress,
                            message=f"正在生成大纲批次 {batch_idx}/{total_batches}（第{start_chapter}-{end_chapter}章）...",
                        )

                    prompt = PromptService.format_prompt(
                        template,
                        title=suggestion.title or "拆书导入项目",
                        genre=suggestion.genre or "通用",
                        theme=suggestion.theme or "未设定",
                        narrative_perspective=suggestion.narrative_perspective or "第三人称",
                        start_chapter=start_chapter,
                        end_chapter=end_chapter,
                        expected_count=expected_count,
                        chapters_text=chapters_text,
                    )

                    ai_data = await ai_service.call_with_json_retry(
                        prompt=prompt,
                        max_retries=3,
                        expected_type="array",
                    )
                    normalized_batch = self._normalize_reverse_outline_batch(ai_data, batch)
                    all_structures.extend(normalized_batch)

                if len(all_structures) != len(chapters):
                    logger.warning(
                        f"反向大纲数量与章节数量不一致，回退校正: outlines={len(all_structures)}, chapters={len(chapters)}"
                    )
                    all_structures = [
                        self._build_fallback_outline_structure(chapter)
                        for chapter in chapters
                    ]

                outlines = [
                    BookImportOutline(
                        title=chapter.title,
                        content=str((structure.get("summary") or structure.get("content") or "")).strip(),
                        order_index=chapter.chapter_number,
                        structure=structure,
                    )
                    for chapter, structure in zip(chapters, all_structures)
                ]

                if task:
                    self._set_task_state(task, status="running", progress=99, message="大纲反向生成完成，正在整理预览...")

                return outlines
        except Exception as exc:
            logger.warning(f"反向生成章节大纲失败，回退规则大纲: {exc}")
            if task:
                self._set_task_state(task, status="running", progress=99, message="AI大纲生成失败，使用规则大纲")
            return fallback_outlines

    def _build_reverse_outline_chapters_text(self, chapters: list[BookImportChapter]) -> str:
        parts: list[str] = []
        for chapter in chapters:
            summary = (chapter.summary or "").strip()
            excerpt = (chapter.content or "").strip()[:2200]
            parts.append(
                f"【第{chapter.chapter_number}章 {chapter.title}】\n"
                f"章节摘要：{summary or '无'}\n"
                f"正文节选：\n{excerpt or '无'}"
            )
        return "\n\n".join(parts)

    def _normalize_reverse_outline_batch(
        self,
        ai_data: Any,
        chapters: list[BookImportChapter],
    ) -> list[dict[str, Any]]:
        ai_items = ai_data if isinstance(ai_data, list) else []
        normalized: list[dict[str, Any]] = []

        for idx, chapter in enumerate(chapters):
            fallback = self._build_fallback_outline_structure(chapter)
            candidate = ai_items[idx] if idx < len(ai_items) and isinstance(ai_items[idx], dict) else {}
            normalized.append(
                self._normalize_single_reverse_outline(
                    candidate,
                    fallback=fallback,
                    chapter_number=chapter.chapter_number,
                    chapter_title=chapter.title,
                )
            )

        return normalized

    def _normalize_single_reverse_outline(
        self,
        raw: dict[str, Any],
        *,
        fallback: dict[str, Any],
        chapter_number: int,
        chapter_title: str,
    ) -> dict[str, Any]:
        summary = str(raw.get("summary") or raw.get("content") or fallback.get("summary") or "").strip()
        if not summary:
            summary = str(fallback.get("summary") or "")

        scenes_raw = raw.get("scenes") if isinstance(raw.get("scenes"), list) else []
        scenes = [str(item).strip() for item in scenes_raw if str(item).strip()][:6]
        if not scenes:
            scenes = list(fallback.get("scenes") or [])

        characters_raw = raw.get("characters") if isinstance(raw.get("characters"), list) else []
        characters: list[dict[str, str]] = []
        for item in characters_raw:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            if not name:
                continue
            role_type = "organization" if str(item.get("type") or "").strip() == "organization" else "character"
            characters.append({"name": name[:80], "type": role_type})
        if not characters:
            characters = list(fallback.get("characters") or [])

        key_points_raw = raw.get("key_points") if isinstance(raw.get("key_points"), list) else []
        key_points = [str(item).strip() for item in key_points_raw if str(item).strip()][:8]
        if not key_points:
            key_points = list(fallback.get("key_points") or [])

        emotion = str(raw.get("emotion") or fallback.get("emotion") or "剧情递进").strip() or "剧情递进"
        goal = str(raw.get("goal") or fallback.get("goal") or "推进主线冲突").strip() or "推进主线冲突"

        return {
            "chapter_number": chapter_number,
            "title": chapter_title,
            "summary": summary[:2000],
            "scenes": scenes,
            "characters": characters,
            "key_points": key_points,
            "emotion": emotion[:200],
            "goal": goal[:300],
        }

    def _build_fallback_outline_structure(self, chapter: BookImportChapter) -> dict[str, Any]:
        summary = self._build_fallback_outline_summary(chapter)

        return {
            "chapter_number": chapter.chapter_number,
            "title": chapter.title,
            "summary": summary[:1200],
            "scenes": [
                "主角在当前处境中做出关键选择",
                "冲突升级并形成新的悬念",
            ],
            "characters": [],
            "key_points": [
                "推进主线冲突",
                "呈现角色动机与关系变化",
            ],
            "emotion": "紧张递进",
            "goal": "承接前章并推动后续剧情发展",
        }

    def _build_fallback_outline_summary(self, chapter: BookImportChapter) -> str:
        summary = chapter.summary or self._build_summary(chapter.content or "")
        normalized = str(summary or "").strip()
        return normalized or "本章围绕主要人物与核心冲突推进剧情。"

    def _build_fallback_project_suggestion(
        self,
        *,
        title: str,
        chapters: list[BookImportChapter],
    ) -> ProjectSuggestion:
        sampled_chapters = chapters[:3]
        sampled_text = "\n\n".join((chapter.content or "")[:2000] for chapter in sampled_chapters).strip()
        fallback_description_source = "\n".join(
            [chapter.summary or (chapter.content or "")[:600] for chapter in sampled_chapters]
        ).strip()
        fallback_description = (
            self._build_summary(fallback_description_source)
            or "由拆书功能基于前3章自动提炼：该故事围绕核心人物与主要冲突展开，可在导入前继续修改。"
        )

        return ProjectSuggestion(
            title=title,
            description=fallback_description[:500],
            theme=self._detect_theme_from_text(sampled_text),
            genre=self._detect_genre_from_text(sampled_text),
            narrative_perspective=self._detect_narrative_perspective(sampled_text),
            target_words=100000,
        )

    def _detect_theme_from_text(self, text: str) -> str:
        if any(k in text for k in ("复仇", "报仇", "雪恨")):
            return "复仇与救赎"
        if any(k in text for k in ("成长", "蜕变", "逆袭")):
            return "成长与逆袭"
        if any(k in text for k in ("真相", "谜团", "秘密", "调查")):
            return "真相与抉择"
        if any(k in text for k in ("权谋", "争权", "朝堂", "家族")):
            return "权力与人性"
        if any(k in text for k in ("爱情", "喜欢", "恋爱", "婚约")):
            return "爱情与选择"
        return "命运与选择"

    def _detect_genre_from_text(self, text: str) -> str:
        if any(k in text for k in ("修仙", "宗门", "灵气", "飞升", "仙门")):
            return "仙侠"
        if any(k in text for k in ("玄幻", "异界", "魔法", "斗气")):
            return "玄幻"
        if any(k in text for k in ("星际", "机甲", "赛博", "人工智能", "宇宙")):
            return "科幻"
        if any(k in text for k in ("悬疑", "凶案", "推理", "谜案", "诡")):
            return "悬疑"
        if any(k in text for k in ("总裁", "职场", "都市", "豪门")):
            return "都市"
        if any(k in text for k in ("恋爱", "言情", "心动", "告白")):
            return "言情"
        return "通用"

    def _detect_narrative_perspective(self, text: str) -> str:
        snippet = (text or "")[:6000]
        first_person_hits = len(re.findall(r"[我咱俺]\S{0,2}", snippet))
        third_person_hits = len(re.findall(r"[他她它]\S{0,2}", snippet))

        if first_person_hits >= 20 and first_person_hits > third_person_hits * 1.2:
            return "第一人称"
        return "第三人称"

    def _extract_narrative_perspective(self, project_data: Dict[str, Any], fallback: str = "第三人称") -> str:
        """从AI返回中兼容提取叙事视角字段，统一映射到项目参数可接受值。"""
        if not isinstance(project_data, dict):
            return self._normalize_narrative_perspective(None, fallback)

        candidates = [
            project_data.get("narrative_perspective"),
            project_data.get("narrativePerspective"),
            project_data.get("perspective"),
            project_data.get("narrative_view"),
            project_data.get("narrative_angle"),
            project_data.get("叙事视角"),
            project_data.get("叙事角度"),
            project_data.get("视角"),
        ]

        for value in candidates:
            normalized = self._normalize_narrative_perspective(value, "")
            if normalized:
                return normalized

        return self._normalize_narrative_perspective(None, fallback)

    def _normalize_narrative_perspective(self, value: Any, fallback: str = "第三人称") -> str:
        raw = str(value or "").strip()
        if not raw:
            return fallback

        if raw in {"第一人称", "第三人称", "全知视角"}:
            return raw

        raw_lower = raw.lower().replace("-", "_").replace(" ", "_")
        if raw_lower in {"first_person", "firstperson", "first_person_perspective", "1st_person", "first"}:
            return "第一人称"
        if raw_lower in {"third_person", "thirdperson", "third_person_perspective", "3rd_person", "third"}:
            return "第三人称"
        if raw_lower in {"omniscient", "god_view", "godview", "all_knowing"}:
            return "全知视角"

        if "第一人称" in raw or raw in {"第一视角", "主角视角", "第一人称（我）", "我视角"}:
            return "第一人称"
        if "第三人称" in raw or raw in {"第三视角", "第三人称（他/她）", "旁观视角"}:
            return "第三人称"
        if "全知" in raw or "上帝视角" in raw:
            return "全知视角"

        return fallback

    def _normalize_target_words(self, value: Any, fallback: int = 100000) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            parsed = fallback

        if parsed < 1000:
            return fallback
        if parsed > 3000000:
            return 3000000
        return parsed

    async def _build_user_ai_service(self, *, db: AsyncSession, user_id: str) -> AIService:
        """读取用户AI配置并创建支持MCP的AI服务实例。"""
        settings_result = await db.execute(select(Settings).where(Settings.user_id == user_id))
        user_settings = settings_result.scalar_one_or_none()

        if not user_settings:
            default_provider = app_settings.default_ai_provider
            if default_provider == "anthropic":
                default_key = app_settings.anthropic_api_key or ""
                default_base_url = app_settings.anthropic_base_url or ""
            elif default_provider == "gemini":
                default_key = app_settings.gemini_api_key or ""
                default_base_url = app_settings.gemini_base_url or ""
            else:
                default_key = app_settings.openai_api_key or ""
                default_base_url = app_settings.openai_base_url or ""

            user_settings = Settings(
                user_id=user_id,
                api_provider=default_provider,
                api_key=default_key,
                api_base_url=default_base_url,
                llm_model=app_settings.default_model,
                temperature=app_settings.default_temperature,
                max_tokens=app_settings.default_max_tokens,
            )
            db.add(user_settings)
            await db.flush()

        mcp_result = await db.execute(select(MCPPlugin).where(MCPPlugin.user_id == user_id))
        mcp_plugins = mcp_result.scalars().all()
        enable_mcp = any(plugin.enabled for plugin in mcp_plugins) if mcp_plugins else False

        if not user_settings.api_key:
            raise HTTPException(status_code=400, detail="未配置AI Key，无法执行拆书反向生成")

        return create_user_ai_service_with_mcp(
            api_provider=user_settings.api_provider,
            api_key=user_settings.api_key,
            api_base_url=user_settings.api_base_url or "",
            model_name=user_settings.llm_model,
            temperature=user_settings.temperature,
            max_tokens=user_settings.max_tokens,
            user_id=user_id,
            db_session=db,
            system_prompt=user_settings.system_prompt,
            enable_mcp=enable_mcp,
        )

    async def _run_post_import_wizard_generation(
        self,
        *,
        db: AsyncSession,
        user_id: str,
        project: Project,
        character_count: int,
        chapters: Optional[list[BookImportChapter]] = None,
    ) -> tuple[int, int, int]:
        """
        走“向导前3步”的核心链路：
        1) 基于项目信息生成世界观
        2) 职业体系
        3) 角色/组织
        不生成大纲。
        """
        generated_world = await self._generate_world_building_from_project(
            db=db,
            user_id=user_id,
            project=project,
        )

        generated_careers = await self._generate_career_system_from_project(
            db=db,
            user_id=user_id,
            project=project,
        )

        generated_entities = await self._generate_characters_and_organizations_from_project(
            db=db,
            user_id=user_id,
            project=project,
            count=character_count,
            source_chapters=chapters,
        )

        # 拆书导入场景不需要继续到大纲，直接标记流程完成，避免项目列表再次跳向导生成大纲
        project.wizard_step = 3
        project.wizard_status = "completed"
        project.status = "writing"

        return generated_world, generated_careers, generated_entities

    async def _generate_world_building_from_project(
        self,
        *,
        db: AsyncSession,
        user_id: str,
        project: Project,
        progress_callback: Any = None,
        progress_range: tuple[int, int] = (0, 100),
        raise_on_error: bool = False,
    ) -> int:
        """根据反向生成的项目基础信息，优先生成并写入世界观。"""

        async def _notify(msg: str, sub: float) -> None:
            if progress_callback:
                p = progress_range[0] + int((progress_range[1] - progress_range[0]) * sub)
                await progress_callback(msg, p)

        try:
            await _notify("🌍 正在初始化AI服务...", 0.1)
            ai_service = await self._build_user_ai_service(db=db, user_id=user_id)

            await _notify("🌍 正在准备世界观提示词...", 0.2)
            template = await PromptService.get_template("WORLD_BUILDING", user_id, db)
            prompt = PromptService.format_prompt(
                template,
                title=project.title or "拆书导入项目",
                genre=project.genre or "通用",
                theme=project.theme or "未设定",
                description=project.description or "暂无简介",
            )

            await _notify("🌍 AI正在生成世界观...", 0.3)
            world_data = await ai_service.call_with_json_retry(
                prompt=prompt,
                max_retries=3,
                expected_type="object",
            )
            if not isinstance(world_data, dict):
                return 0

            await _notify("🌍 正在解析世界观数据...", 0.8)
            time_period = str(world_data.get("time_period") or "").strip()
            location = str(world_data.get("location") or "").strip()
            atmosphere = str(world_data.get("atmosphere") or "").strip()
            rules = str(world_data.get("rules") or "").strip()

            updated = 0
            if time_period:
                project.world_time_period = time_period
                updated = 1
            if location:
                project.world_location = location
                updated = 1
            if atmosphere:
                project.world_atmosphere = atmosphere
                updated = 1
            if rules:
                project.world_rules = rules
                updated = 1

            await _notify("🌍 世界观写入完成", 1.0)
            return updated
        except Exception as exc:
            logger.warning(f"拆书导入阶段生成世界观失败，沿用现有世界观: {exc}")
            if raise_on_error:
                raise
            return 0

    async def _generate_career_system_from_project(
        self,
        *,
        db: AsyncSession,
        user_id: str,
        project: Project,
        progress_callback: Any = None,
        progress_range: tuple[int, int] = (0, 100),
    ) -> int:
        """根据项目世界观生成职业体系（3主2副）。"""

        async def _notify(msg: str, sub: float) -> None:
            if progress_callback:
                p = progress_range[0] + int((progress_range[1] - progress_range[0]) * sub)
                await progress_callback(msg, p)

        await _notify("💼 正在初始化AI服务...", 0.1)
        ai_service = await self._build_user_ai_service(db=db, user_id=user_id)

        await _notify("💼 正在准备职业体系提示词...", 0.2)
        template = await PromptService.get_template("CAREER_SYSTEM_GENERATION", user_id, db)
        prompt = PromptService.format_prompt(
            template,
            title=project.title,
            genre=project.genre or "未设定",
            theme=project.theme or "未设定",
            description=project.description or "暂无简介",
            time_period=project.world_time_period or "未设定",
            location=project.world_location or "未设定",
            atmosphere=project.world_atmosphere or "未设定",
            rules=project.world_rules or "未设定",
        )

        await _notify("💼 AI正在生成职业体系...", 0.3)
        career_data = await ai_service.call_with_json_retry(
            prompt=prompt,
            max_retries=3,
            expected_type="object",
        )

        await _notify("💼 正在解析职业数据...", 0.7)
        main_careers = career_data.get("main_careers", [])
        sub_careers = career_data.get("sub_careers", [])
        if not isinstance(main_careers, list):
            main_careers = []
        if not isinstance(sub_careers, list):
            sub_careers = []

        # 清理历史职业，避免重复（拆书导入走新建项目，但这里保持幂等）
        career_ids_result = await db.execute(select(Career.id).where(Career.project_id == project.id))
        career_ids = [row[0] for row in career_ids_result.fetchall()]
        if career_ids:
            await db.execute(delete(CharacterCareer).where(CharacterCareer.career_id.in_(career_ids)))
            await db.execute(delete(Career).where(Career.project_id == project.id))

        created = 0

        def _to_career_model(item: dict[str, Any], career_type: str, idx: int) -> Career:
            stages = item.get("stages", [])
            if not isinstance(stages, list):
                stages = []
            max_stage = item.get("max_stage", len(stages) if stages else (10 if career_type == "main" else 6))
            if not isinstance(max_stage, int) or max_stage <= 0:
                max_stage = len(stages) if stages else (10 if career_type == "main" else 6)

            attr_bonuses = item.get("attribute_bonuses")
            attr_bonuses_json = json.dumps(attr_bonuses, ensure_ascii=False) if attr_bonuses else None

            return Career(
                project_id=project.id,
                name=(item.get("name") or f"未命名{'主' if career_type == 'main' else '副'}职业{idx + 1}")[:100],
                type=career_type,
                description=item.get("description"),
                category=item.get("category"),
                stages=json.dumps(stages, ensure_ascii=False),
                max_stage=max_stage,
                requirements=item.get("requirements"),
                special_abilities=item.get("special_abilities"),
                worldview_rules=item.get("worldview_rules"),
                attribute_bonuses=attr_bonuses_json,
                source="ai",
            )

        for idx, item in enumerate(main_careers):
            if not isinstance(item, dict):
                continue
            db.add(_to_career_model(item, "main", idx))
            created += 1

        for idx, item in enumerate(sub_careers):
            if not isinstance(item, dict):
                continue
            db.add(_to_career_model(item, "sub", idx))
            created += 1

        await db.flush()
        return created

    def _build_import_source_text(
        self,
        chapters: Optional[list[BookImportChapter]],
        *,
        max_chars: int = 80000,
    ) -> str:
        if not chapters:
            return ""

        parts: list[str] = []
        remaining = max_chars
        for chapter in chapters:
            if remaining <= 0:
                break

            title = str(chapter.title or "").strip()
            content = str(chapter.content or "").strip()
            if title:
                title_part = title[:remaining]
                parts.append(title_part)
                remaining -= len(title_part)
            if content:
                if remaining <= 0:
                    break
                content_part = content[:remaining]
                parts.append(content_part)
                remaining -= len(content_part)
        return "\n".join(parts)

    def _build_import_source_prompt_context(
        self,
        chapters: Optional[list[BookImportChapter]],
        *,
        max_chars: int = 10000,
    ) -> str:
        if not chapters:
            return ""

        parts: list[str] = []
        for chapter in chapters[:30]:
            title = str(chapter.title or "").strip() or f"第{chapter.chapter_number}章"
            content = str(chapter.content or "").strip()
            excerpt = content[:500]
            parts.append(f"第{chapter.chapter_number}章《{title}》\n{excerpt}")

        context = "\n\n".join(parts).strip()
        return context[:max_chars]

    def _extract_import_source_name_candidates(
        self,
        *,
        source_text: str,
        title: str,
        limit: int = 30,
    ) -> list[str]:
        if not source_text:
            return []

        stopwords = {
            "放学", "教室", "数学", "老师", "粉笔", "黑板", "学校", "今天", "时候", "朋友",
            "什么", "身体", "眼睛", "世界", "魔物", "情绪", "心灵", "魔法", "少女", "不是",
            "这个", "那个", "一下", "一声", "一个", "一只", "一层", "一步", "一点", "一样",
            "里面", "第一", "第二", "第三", "第四", "第五", "体育", "男生", "女生", "同学",
            "书包", "课桌", "手机", "图书", "图书馆", "舞台", "后台", "体育馆", "城市", "空气",
            "然后", "只是", "他们", "可以", "低头", "右手", "自己", "声音", "看了", "她能",
            "事情", "对方", "以后", "原本", "现在", "这里", "那里", "心里", "手里", "身边",
        }
        counter: Counter[str] = Counter()

        title_candidate = re.sub(
            r"(魔法|少女|少年|传说|传|录|记|篇|小说|测试文|\s+)",
            "",
            title or "",
        )
        if 2 <= len(title_candidate) <= 4 and title_candidate in source_text:
            counter[title_candidate] += source_text.count(title_candidate) + 1000

        verbs = (
            "说|问|喊|叫|笑|看|站|走|跑|盯|抬|低|拿|想|听|点|摇|伸|皱|咬|推|坐|转|愣|"
            "开口|回答|眨|叹|冲|抓|握|扶|闭|睁|发现|感觉|知道|觉得|意识|沉默"
        )
        patterns = [
            rf"([\u4e00-\u9fff]{{2,4}})(?=(?:{verbs}))",
            rf"(?:叫|喊|问|对|看向|拉住|推了推)([\u4e00-\u9fff]{{2,4}})",
        ]

        match_counter: Counter[str] = Counter()
        for pattern in patterns:
            for match in re.finditer(pattern, source_text):
                name = self._normalize_import_source_name_candidate(match.group(1))
                if not name or name in stopwords or is_generic_reference(name):
                    continue
                match_counter[name] += 1

        for name, occurrences in match_counter.items():
            if occurrences >= 3:
                counter[name] += occurrences

        return [name for name, _ in counter.most_common(limit)]

    def _normalize_import_source_name_candidate(self, value: Any) -> str:
        name = str(value or "").strip()
        name = re.sub(r"^(但|而|可|又|便|于是|然后|如果|因为|只是|只有|那个|这个|她|他|它|你|我)+", "", name)
        name = re.sub(r"(轻声|猛地|慢慢|突然|尖|下|没|不|能|想|在)$", "", name)
        if not re.fullmatch(r"[\u4e00-\u9fff]{2,4}", name):
            return ""
        if is_generic_reference(name):
            return ""
        return name

    def _resolve_import_source_entity_name(
        self,
        name: Any,
        *,
        source_text: str,
        source_names: list[str],
    ) -> Optional[str]:
        raw_name = str(name or "").strip()
        if not raw_name:
            return None
        if raw_name in source_text:
            return raw_name

        for candidate in source_names:
            if raw_name.endswith(candidate) or candidate.endswith(raw_name):
                return candidate

        for size in range(min(4, len(raw_name) - 1), 1, -1):
            suffix = raw_name[-size:]
            if suffix in source_text and source_text.count(suffix) >= 3:
                return suffix

        return None

    def _build_import_fallback_entity(self, name: str, index: int) -> dict[str, Any]:
        return {
            "name": name,
            "age": None,
            "gender": "未知",
            "is_organization": False,
            "role_type": "protagonist" if index == 0 else "supporting",
            "personality": "由拆书导入根据原文出现频率自动建立，具体性格可在角色卡中继续补充。",
            "background": "该角色明确出现在导入原文中，系统未额外补写原文之外的人物经历。",
            "appearance": "原文未在当前抽取阶段形成稳定外貌描述，可后续手动完善。",
            "traits": [],
            "relationships_array": [],
            "organization_memberships": [],
        }

    def _ground_generated_entities_to_source(
        self,
        generated_entities: list[Any],
        *,
        source_text: str,
        source_names: list[str],
        target_count: int,
    ) -> list[dict[str, Any]]:
        normalized_items: list[dict[str, Any]] = []
        seen_names: set[str] = set()
        dropped_names: list[str] = []

        for item in generated_entities:
            if not isinstance(item, dict):
                continue

            raw_name = str(item.get("name") or "").strip()
            if not raw_name:
                continue

            is_organization = bool(item.get("is_organization", False))
            if is_organization:
                normalized_name = raw_name if raw_name in source_text else None
            else:
                normalized_name = self._resolve_import_source_entity_name(
                    raw_name,
                    source_text=source_text,
                    source_names=source_names,
                )

            if not normalized_name:
                dropped_names.append(raw_name)
                continue
            if normalized_name in seen_names:
                continue

            normalized = dict(item)
            normalized["name"] = normalized_name
            normalized_items.append(normalized)
            seen_names.add(normalized_name)

        fallback_limit = min(target_count, 5)
        for name in source_names:
            if len(normalized_items) >= fallback_limit:
                break
            if name in seen_names:
                continue
            normalized_items.append(self._build_import_fallback_entity(name, len(normalized_items)))
            seen_names.add(name)

        kept_names = {str(item.get("name") or "") for item in normalized_items}
        organization_names = {
            str(item.get("name") or "")
            for item in normalized_items
            if bool(item.get("is_organization", False))
        }

        for item in normalized_items:
            relationships = item.get("relationships_array")
            if isinstance(relationships, list):
                filtered_relationships: list[dict[str, Any]] = []
                for rel in relationships:
                    if not isinstance(rel, dict):
                        continue
                    target_name = self._resolve_import_source_entity_name(
                        rel.get("target_character_name"),
                        source_text=source_text,
                        source_names=source_names,
                    )
                    if not target_name or target_name not in kept_names or target_name == item.get("name"):
                        continue
                    normalized_rel = dict(rel)
                    normalized_rel["target_character_name"] = target_name
                    filtered_relationships.append(normalized_rel)
                item["relationships_array"] = filtered_relationships

            memberships = item.get("organization_memberships")
            if isinstance(memberships, list):
                item["organization_memberships"] = [
                    membership
                    for membership in memberships
                    if isinstance(membership, dict)
                    and str(membership.get("organization_name") or "").strip() in organization_names
                ]

            org_members = item.get("organization_members")
            if isinstance(org_members, list):
                item["organization_members"] = [
                    name for name in org_members
                    if str(name or "").strip() in kept_names
                ]

        if dropped_names:
            logger.info(
                "拆书导入过滤原文未出现的角色/组织: %s",
                "、".join(dropped_names[:20]),
            )

        return normalized_items[:target_count]

    async def _generate_characters_and_organizations_from_project(
        self,
        *,
        db: AsyncSession,
        user_id: str,
        project: Project,
        count: int,
        progress_callback: Any = None,
        progress_range: tuple[int, int] = (0, 100),
        source_chapters: Optional[list[BookImportChapter]] = None,
    ) -> int:
        """根据世界观+职业体系生成角色/组织，并补全职业和组织成员关系。"""

        async def _notify(msg: str, sub: float) -> None:
            if progress_callback:
                p = progress_range[0] + int((progress_range[1] - progress_range[0]) * sub)
                await progress_callback(msg, p)

        def _to_int(value: Any, default: int) -> int:
            try:
                return int(value)
            except (TypeError, ValueError):
                return default

        await _notify("👥 正在初始化AI服务...", 0.05)
        ai_service = await self._build_user_ai_service(db=db, user_id=user_id)

        # 控制数量区间，避免过多生成
        target_count = max(5, min(count, 20))

        # 职业上下文：用于提示词约束与后续名称映射
        careers_result = await db.execute(select(Career).where(Career.project_id == project.id))
        careers = careers_result.scalars().all()
        main_careers = [c for c in careers if c.type == "main"]
        sub_careers = [c for c in careers if c.type == "sub"]
        main_career_map = {c.name: c for c in main_careers}
        sub_career_map = {c.name: c for c in sub_careers}

        await _notify("👥 正在准备角色生成提示词...", 0.15)
        template = await PromptService.get_template("CHARACTERS_BATCH_GENERATION", user_id, db)
        source_text = self._build_import_source_text(source_chapters)
        source_names = self._extract_import_source_name_candidates(
            source_text=source_text,
            title=project.title or "",
        )
        requirements = (
            "请生成能够支撑前期剧情推进的关键角色与组织，"
            "角色和组织都要与世界观、职业体系一致。"
            "如果包含组织，数量不超过2个。"
            "请尽量为非组织角色补充 organization_memberships。"
        )
        if source_text:
            source_context = self._build_import_source_prompt_context(source_chapters)
            requirements = (
                "这是拆书导入项目，角色卡必须从原文抽取，不是重新创作。"
                "只能使用原文中明确出现的角色名或组织名，禁止推断姓氏、禁止补充原文不存在的新角色。"
                "主角姓名必须与原文保持一致；如果原文只写“晓卡”，就必须输出“晓卡”，不能改成“苏晓卡”等全名。"
                "原文未出现的组织不要生成；如果组织名不明确，可以只生成角色。"
                f"原文高频候选名：{'、'.join(source_names[:5]) or '未识别'}。\n"
                f"【原文节选】\n{source_context}\n\n"
                + requirements
            )

        if main_careers or sub_careers:
            careers_context = "\n\n【职业分配要求】\n"
            careers_context += "请为每个非组织角色返回 career_assignment 字段："
            careers_context += '{"main_career":"主职业名称","main_stage":2,"sub_careers":[{"career":"副职业名称","stage":1}]}'
            careers_context += "\n职业名称必须从以下列表中选择：\n"
            if main_careers:
                careers_context += "- 可用主职业：" + "、".join([c.name for c in main_careers]) + "\n"
            if sub_careers:
                careers_context += "- 可用副职业：" + "、".join([c.name for c in sub_careers]) + "\n"
            requirements += careers_context

        prompt = PromptService.format_prompt(
            template,
            count=target_count,
            time_period=project.world_time_period or "未设定",
            location=project.world_location or "未设定",
            atmosphere=project.world_atmosphere or "未设定",
            rules=project.world_rules or "未设定",
            theme=project.theme or "未设定",
            genre=project.genre or "未设定",
            requirements=requirements,
        )

        await _notify("👥 AI正在生成角色与组织...", 0.25)
        generated_data = await ai_service.call_with_json_retry(
            prompt=prompt,
            max_retries=3,
            expected_type="array",
        )
        await _notify("👥 正在解析角色数据...", 0.7)
        if isinstance(generated_data, dict):
            generated_entities = [generated_data]
        elif isinstance(generated_data, list):
            generated_entities = generated_data
        else:
            generated_entities = []
        if source_text:
            generated_entities = self._ground_generated_entities_to_source(
                generated_entities,
                source_text=source_text,
                source_names=source_names,
                target_count=target_count,
            )

        # 预加载角色/组织，便于去重和兼容 append 场景的名称引用
        existing_chars_result = await db.execute(select(Character).where(Character.project_id == project.id))
        existing_chars = existing_chars_result.scalars().all()
        existing_names = {c.name for c in existing_chars}
        character_name_to_obj: dict[str, Character] = {c.name: c for c in existing_chars}

        existing_orgs_result = await db.execute(
            select(Organization, Character.name)
            .join(Character, Organization.character_id == Character.id)
            .where(Organization.project_id == project.id)
        )
        organization_name_to_obj: dict[str, Organization] = {
            row[1]: row[0] for row in existing_orgs_result.all() if row[1]
        }

        existing_member_result = await db.execute(
            select(OrganizationMember.organization_id, OrganizationMember.character_id)
            .join(Organization, OrganizationMember.organization_id == Organization.id)
            .where(Organization.project_id == project.id)
        )
        member_pairs = {(row[0], row[1]) for row in existing_member_result.all()}

        existing_rel_result = await db.execute(
            select(CharacterRelationship.character_from_id, CharacterRelationship.character_to_id)
            .where(CharacterRelationship.project_id == project.id)
        )
        relationship_pairs = {(row[0], row[1]) for row in existing_rel_result.all()}

        rel_type_result = await db.execute(select(RelationshipType))
        relationship_type_map: dict[str, int] = {
            rel_type.name: rel_type.id
            for rel_type in rel_type_result.scalars().all()
            if rel_type.name
        }

        created = 0
        created_items: list[tuple[Character, dict[str, Any]]] = []

        # 第一阶段：创建 Character / Organization 实体
        for item in generated_entities:
            if not isinstance(item, dict):
                continue

            raw_name = (item.get("name") or "").strip()
            if not raw_name or raw_name in existing_names:
                continue

            is_organization = bool(item.get("is_organization", False))
            character = Character(
                project_id=project.id,
                name=raw_name[:100],
                age=(str(item.get("age")) if item.get("age") is not None else None) if not is_organization else None,
                gender=item.get("gender") if not is_organization else None,
                is_organization=is_organization,
                role_type=(item.get("role_type") or "supporting")[:50],
                personality=item.get("personality"),
                background=item.get("background"),
                appearance=item.get("appearance"),
                organization_type=item.get("organization_type") if is_organization else None,
                organization_purpose=item.get("organization_purpose") if is_organization else None,
                organization_members=(
                    json.dumps(item.get("organization_members"), ensure_ascii=False)
                    if item.get("organization_members") is not None else None
                ),
                traits=json.dumps(item.get("traits", []), ensure_ascii=False) if item.get("traits") else None,
            )
            db.add(character)
            await db.flush()

            if is_organization:
                organization = Organization(
                    character_id=character.id,
                    project_id=project.id,
                    power_level=max(0, min(_to_int(item.get("power_level", 50), 50), 100)),
                    member_count=0,
                    location=item.get("location"),
                    motto=item.get("motto"),
                    color=item.get("color"),
                )
                db.add(organization)
                await db.flush()
                organization_name_to_obj[character.name] = organization

            created_items.append((character, item))
            character_name_to_obj[character.name] = character
            existing_names.add(raw_name)
            created += 1

        # 第二阶段：创建职业关联（CharacterCareer + 冗余字段）
        if created_items and (main_career_map or sub_career_map):
            career_pairs: set[tuple[str, str]] = set()

            for character, item in created_items:
                if character.is_organization:
                    continue

                # 兼容两种字段：career_assignment(批量) / career_info(单角色)
                assignment = item.get("career_assignment")
                if not isinstance(assignment, dict):
                    career_info = item.get("career_info")
                    if isinstance(career_info, dict):
                        assignment = {
                            "main_career": career_info.get("main_career_name"),
                            "main_stage": career_info.get("main_career_stage", 1),
                            "sub_careers": [
                                {
                                    "career": sub.get("career_name"),
                                    "stage": sub.get("stage", 1),
                                }
                                for sub in (career_info.get("sub_careers") or [])
                                if isinstance(sub, dict)
                            ],
                        }

                if not isinstance(assignment, dict):
                    continue

                # 主职业
                main_name = (assignment.get("main_career") or "").strip()
                if main_name and main_name in main_career_map:
                    main_career = main_career_map[main_name]
                    main_stage = max(1, min(_to_int(assignment.get("main_stage", 1), 1), max(main_career.max_stage or 1, 1)))
                    main_key = (character.id, main_career.id)
                    if main_key not in career_pairs:
                        db.add(
                            CharacterCareer(
                                character_id=character.id,
                                career_id=main_career.id,
                                career_type="main",
                                current_stage=main_stage,
                                stage_progress=0,
                            )
                        )
                        career_pairs.add(main_key)

                    character.main_career_id = main_career.id
                    character.main_career_stage = main_stage

                # 副职业
                sub_list = assignment.get("sub_careers") or []
                if not isinstance(sub_list, list):
                    sub_list = []

                sub_career_json: list[dict[str, Any]] = []
                for sub in sub_list[:2]:
                    if not isinstance(sub, dict):
                        continue
                    sub_name = (sub.get("career") or "").strip()
                    if not sub_name or sub_name not in sub_career_map:
                        continue

                    sub_career = sub_career_map[sub_name]
                    sub_stage = max(1, min(_to_int(sub.get("stage", 1), 1), max(sub_career.max_stage or 1, 1)))
                    sub_key = (character.id, sub_career.id)
                    if sub_key in career_pairs:
                        continue

                    db.add(
                        CharacterCareer(
                            character_id=character.id,
                            career_id=sub_career.id,
                            career_type="sub",
                            current_stage=sub_stage,
                            stage_progress=0,
                        )
                    )
                    career_pairs.add(sub_key)
                    sub_career_json.append({"career_id": sub_career.id, "stage": sub_stage})

                if sub_career_json:
                    character.sub_careers = json.dumps(sub_career_json, ensure_ascii=False)

        # 第三阶段：创建角色关系（relationships_array / relationships）
        for character, item in created_items:
            if character.is_organization:
                continue

            relationships_data = item.get("relationships_array")
            if not isinstance(relationships_data, list):
                legacy_relationships = item.get("relationships")
                relationships_data = legacy_relationships if isinstance(legacy_relationships, list) else []

            for rel in relationships_data:
                if not isinstance(rel, dict):
                    continue

                target_name = (rel.get("target_character_name") or "").strip()
                if not target_name:
                    continue

                target_char = character_name_to_obj.get(target_name)
                if not target_char or target_char.is_organization:
                    continue
                if target_char.id == character.id:
                    continue

                pair = (character.id, target_char.id)
                if pair in relationship_pairs:
                    continue

                relationship_name = (rel.get("relationship_type") or "未知关系").strip()[:100]
                intimacy_level = max(-100, min(_to_int(rel.get("intimacy_level", 50), 50), 100))
                status = (rel.get("status") or "active")[:20]
                description = rel.get("description")
                if description is not None:
                    description = str(description)

                db.add(
                    CharacterRelationship(
                        project_id=project.id,
                        character_from_id=character.id,
                        character_to_id=target_char.id,
                        relationship_type_id=relationship_type_map.get(relationship_name),
                        relationship_name=relationship_name,
                        intimacy_level=intimacy_level,
                        status=status,
                        description=description,
                        source="ai",
                    )
                )
                relationship_pairs.add(pair)

        # 第四阶段：创建组织成员关系（优先使用角色上的 organization_memberships）
        for character, item in created_items:
            if character.is_organization:
                continue

            org_memberships = item.get("organization_memberships")
            if not isinstance(org_memberships, list):
                continue

            for membership in org_memberships:
                if not isinstance(membership, dict):
                    continue

                org_name = (membership.get("organization_name") or "").strip()
                if not org_name:
                    continue

                org = organization_name_to_obj.get(org_name)
                if not org:
                    continue

                pair = (org.id, character.id)
                if pair in member_pairs:
                    continue

                db.add(
                    OrganizationMember(
                        organization_id=org.id,
                        character_id=character.id,
                        position=(membership.get("position") or "成员")[:100],
                        rank=max(0, min(_to_int(membership.get("rank", 0), 0), 10)),
                        loyalty=max(0, min(_to_int(membership.get("loyalty", 50), 50), 100)),
                        joined_at=membership.get("joined_at"),
                        status=(membership.get("status") or "active")[:20],
                        source="ai",
                    )
                )
                member_pairs.add(pair)
                org.member_count = (org.member_count or 0) + 1

        # 第五阶段：回填组织对象里的 organization_members（按名称补充成员）
        for character, item in created_items:
            if not character.is_organization:
                continue

            org = organization_name_to_obj.get(character.name)
            if not org:
                continue

            member_names_raw = item.get("organization_members")
            member_names: list[str] = []
            if isinstance(member_names_raw, list):
                member_names = [str(name).strip() for name in member_names_raw if str(name).strip()]
            elif isinstance(member_names_raw, str) and member_names_raw.strip():
                member_names = [member_names_raw.strip()]

            for member_name in member_names:
                member_char = character_name_to_obj.get(member_name)
                if not member_char or member_char.is_organization:
                    continue

                pair = (org.id, member_char.id)
                if pair in member_pairs:
                    continue

                db.add(
                    OrganizationMember(
                        organization_id=org.id,
                        character_id=member_char.id,
                        position="成员",
                        rank=0,
                        loyalty=50,
                        status="active",
                        source="ai",
                    )
                )
                member_pairs.add(pair)
                org.member_count = (org.member_count or 0) + 1

        await db.flush()
        return created

    def _build_summary(self, content: str, max_len: int = 120) -> Optional[str]:
        if not content:
            return None
        normalized = re.sub(r"\s+", " ", content).strip()
        if len(normalized) <= max_len:
            return normalized
        return normalized[:max_len] + "…"

    def _get_preview_storage_path(self, *, user_id: str, task_id: str) -> Path:
        safe_user_id = re.sub(r"[^A-Za-z0-9_.-]", "_", str(user_id or "anonymous"))
        safe_task_id = re.sub(r"[^A-Za-z0-9_.-]", "_", str(task_id or "task"))
        return BOOK_IMPORT_PREVIEW_STORAGE_DIR / safe_user_id / f"{safe_task_id}.json"

    def _normalize_preview_storage_path(self, raw_path: Optional[str], *, user_id: str, task_id: str) -> Path:
        if not raw_path:
            return self._get_preview_storage_path(user_id=user_id, task_id=task_id)

        try:
            candidate = Path(raw_path).expanduser()
            storage_root = BOOK_IMPORT_PREVIEW_STORAGE_DIR.resolve()
            resolved = candidate.resolve()
            if resolved == storage_root or storage_root in resolved.parents:
                return candidate
        except Exception:
            pass

        return self._get_preview_storage_path(user_id=user_id, task_id=task_id)

    async def _save_preview_to_storage(
        self,
        task: _BookImportTask,
        preview: BookImportPreviewResponse,
    ) -> None:
        preview_path = self._normalize_preview_storage_path(
            task.preview_storage_path,
            user_id=task.user_id,
            task_id=task.task_id,
        )

        def _write() -> None:
            preview_path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = preview_path.with_suffix(f"{preview_path.suffix}.tmp")
            payload = {
                "schema_version": BOOK_IMPORT_PREVIEW_SCHEMA_VERSION,
                "task_id": task.task_id,
                "user_id": task.user_id,
                "filename": task.filename,
                "saved_at": datetime.utcnow().isoformat(),
                "preview": preview.model_dump(mode="json"),
            }
            with tmp_path.open("w", encoding="utf-8") as fp:
                json.dump(payload, fp, ensure_ascii=False)
            tmp_path.replace(preview_path)

        await asyncio.to_thread(_write)
        task.preview_storage_path = str(preview_path)

    async def _load_preview_from_storage(self, task: _BookImportTask) -> Optional[BookImportPreviewResponse]:
        preview_path = self._normalize_preview_storage_path(
            task.preview_storage_path,
            user_id=task.user_id,
            task_id=task.task_id,
        )
        if not preview_path.exists():
            return None

        def _read() -> Optional[BookImportPreviewResponse]:
            with preview_path.open("r", encoding="utf-8") as fp:
                payload = json.load(fp)
            if not isinstance(payload, dict):
                return None

            preview_payload = payload.get("preview") if "preview" in payload else payload
            preview = BookImportPreviewResponse.model_validate(preview_payload)
            if preview.task_id != task.task_id:
                return None
            return preview

        try:
            preview = await asyncio.to_thread(_read)
        except Exception as exc:
            logger.warning(f"读取拆书预览持久化文件失败 task_id={task.task_id}: {exc}")
            return None

        if preview:
            task.preview_storage_path = str(preview_path)
        return preview

    async def _ensure_task_preview_loaded(self, task: _BookImportTask) -> Optional[BookImportPreviewResponse]:
        if task.preview:
            return task.preview

        preview = await self._load_preview_from_storage(task)
        if preview:
            task.preview = preview
        return preview

    async def _drop_task_from_hot_cache(self, task_id: str) -> None:
        async with self._tasks_lock:
            self._tasks.pop(task_id, None)

    async def _get_task(self, *, task_id: str, user_id: str) -> _BookImportTask:
        async with self._tasks_lock:
            task = self._tasks.get(task_id)

        if not task:
            background_task = await self._get_background_task(task_id=task_id, user_id=user_id)
            if not background_task:
                raise HTTPException(status_code=404, detail="任务不存在")
            task = self._task_from_background_task(background_task)

        if task.user_id != user_id:
            raise HTTPException(status_code=403, detail="无权访问该任务")
        return task

    async def _get_background_task(self, *, task_id: str, user_id: str) -> Optional[BackgroundTask]:
        try:
            engine = await get_engine(user_id)
            SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
            async with SessionLocal() as db:
                background_task = await db.get(BackgroundTask, task_id)
                if (
                    not background_task
                    or background_task.user_id != user_id
                    or background_task.task_type != BOOK_IMPORT_TASK_TYPE
                ):
                    return None
                return background_task
        except Exception as exc:
            logger.warning(f"读取拆书后台任务失败 task_id={task_id}: {exc}")
            return None

    def _task_from_background_task(self, background_task: BackgroundTask) -> _BookImportTask:
        task_input = background_task.task_input or {}
        task_result = background_task.task_result or {}
        preview_storage = task_result.get("preview_storage") if isinstance(task_result, dict) else None
        preview_storage_path = None
        if isinstance(preview_storage, dict):
            preview_storage_path = preview_storage.get("path")
        return _BookImportTask(
            task_id=background_task.id,
            user_id=background_task.user_id,
            filename=str(task_input.get("filename") or ""),
            project_id=task_input.get("project_id"),
            create_new_project=bool(task_input.get("create_new_project", True)),
            import_mode=str(task_input.get("import_mode") or "append"),
            extract_mode=task_input.get("extract_mode") or "tail",
            tail_chapter_count=int(task_input.get("tail_chapter_count") or 10),
            setup_mode=task_input.get("setup_mode") or "auto",
            status=background_task.status or "pending",
            progress=int(background_task.progress or 0),
            message=background_task.status_message,
            error=background_task.error_message,
            created_at=background_task.created_at or datetime.utcnow(),
            updated_at=background_task.updated_at or background_task.created_at or datetime.utcnow(),
            preview_storage_path=str(self._normalize_preview_storage_path(
                preview_storage_path,
                user_id=background_task.user_id,
                task_id=background_task.id,
            )),
            cancelled=bool(background_task.cancel_requested),
            background_task_id=background_task.id,
            imported_project_id=task_result.get("imported_project_id"),
            failed_steps=[
                _StepFailure(
                    step_name=str(item.get("step_name") or ""),
                    step_label=str(item.get("step_label") or ""),
                    error_message=str(item.get("error") or item.get("error_message") or ""),
                    retry_count=int(item.get("retry_count") or 0),
                )
                for item in task_result.get("failed_steps", [])
                if isinstance(item, dict)
            ],
        )

    def _to_status(self, task: _BookImportTask) -> BookImportTaskStatusResponse:
        return BookImportTaskStatusResponse(
            task_id=task.task_id,
            status=task.status,  # type: ignore[arg-type]
            progress=task.progress,
            message=task.message,
            error=task.error,
            created_at=task.created_at,
            updated_at=task.updated_at,
        )

    def _set_task_state(
        self,
        task: _BookImportTask,
        *,
        status: str,
        progress: int,
        message: Optional[str],
        error: Optional[str] = None,
    ) -> None:
        task.status = status
        task.progress = max(0, min(100, progress))
        task.message = message
        task.error = error
        task.updated_at = datetime.utcnow()
        self._schedule_background_task_sync(task)

    def _schedule_background_task_sync(self, task: _BookImportTask) -> None:
        if not task.background_task_id:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        loop.create_task(self._persist_background_task_state(task))

    async def _persist_background_task_state(self, task: _BookImportTask) -> None:
        if not task.background_task_id:
            return

        try:
            engine = await get_engine(task.user_id)
            SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
            async with SessionLocal() as db:
                background_task = await db.get(BackgroundTask, task.background_task_id)
                if not background_task or background_task.user_id != task.user_id:
                    return

                background_task.status = task.status
                background_task.progress = task.progress
                background_task.status_message = task.message
                background_task.error_message = task.error
                background_task.cancel_requested = bool(task.cancelled)
                background_task.progress_details = {
                    "stage": "book_import",
                    "message": task.message,
                    "filename": task.filename,
                    "extract_mode": task.extract_mode,
                    "setup_mode": task.setup_mode,
                }
                if task.status == "running" and not background_task.started_at:
                    background_task.started_at = task.updated_at
                if task.status in {"completed", "failed", "cancelled"}:
                    background_task.completed_at = task.updated_at
                    background_task.task_result = self._build_background_task_result(task)

                await db.commit()
        except Exception as exc:
            logger.warning(f"同步拆书后台任务状态失败 task_id={task.task_id}: {exc}")

    def _build_background_task_result(self, task: _BookImportTask) -> dict[str, Any]:
        split_report = None
        token_budget = None
        chapter_count = 0
        entity_candidate_count = 0
        preview_storage_path = self._normalize_preview_storage_path(
            task.preview_storage_path,
            user_id=task.user_id,
            task_id=task.task_id,
        )
        preview_storage_exists = preview_storage_path.exists()
        if task.preview:
            chapter_count = len(task.preview.chapters)
            entity_candidate_count = len(getattr(task.preview, "entity_candidates", []) or [])
            if task.preview.split_report:
                dump = getattr(task.preview.split_report, "model_dump", None)
                split_report = dump(mode="json") if callable(dump) else dict(task.preview.split_report)
            if task.preview.token_budget:
                dump = getattr(task.preview.token_budget, "model_dump", None)
                token_budget = dump(mode="json") if callable(dump) else dict(task.preview.token_budget)

        return {
            "task_id": task.task_id,
            "filename": task.filename,
            "preview_available": bool(task.preview) or preview_storage_exists,
            "preview_storage": {
                "type": "file",
                "schema_version": BOOK_IMPORT_PREVIEW_SCHEMA_VERSION,
                "path": str(preview_storage_path),
                "exists": preview_storage_exists,
            },
            "chapter_count": chapter_count,
            "entity_candidate_count": entity_candidate_count,
            "split_report": split_report,
            "token_budget": token_budget,
            "imported_project_id": task.imported_project_id,
            "failed_steps": [
                {
                    "step_name": item.step_name,
                    "step_label": item.step_label,
                    "error": item.error_message,
                    "retry_count": item.retry_count,
                }
                for item in task.failed_steps
            ],
        }

    def _check_cancelled(self, task: _BookImportTask) -> None:
        if task.cancelled or task.status == "cancelled":
            raise asyncio.CancelledError("任务已取消")


book_import_service = BookImportService()
