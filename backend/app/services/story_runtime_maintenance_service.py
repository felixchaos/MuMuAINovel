"""Runtime story maintenance fed by chapter analysis.

This service intentionally writes back into the official-compatible project
tables instead of introducing another fact store. PlotAnalysis remains the
analysis source, StoryMemory remains the durable fact/memory stream, and this
adapter keeps character cards, careers, relationships, organizations,
foreshadows, and project world-building fields in sync.
"""
from __future__ import annotations

from typing import Any, Dict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.logger import get_logger
from app.models.project import Project
from app.services.career_update_service import CareerUpdateService
from app.services.character_state_update_service import CharacterStateUpdateService
from app.services.foreshadow_service import foreshadow_service

logger = get_logger(__name__)


class StoryRuntimeMaintenanceService:
    """Conservative write-back layer for analysis-derived runtime state."""

    async def sync_from_analysis(
        self,
        *,
        db: AsyncSession,
        project_id: str,
        chapter_id: str,
        chapter_number: int,
        analysis_result: Dict[str, Any],
    ) -> Dict[str, Any]:
        summary: Dict[str, Any] = {
            "career": {"updated_count": 0, "changes": []},
            "character_state": {
                "state_updated_count": 0,
                "relationship_created_count": 0,
                "relationship_updated_count": 0,
                "org_updated_count": 0,
                "changes": [],
            },
            "organization_state": {"updated_count": 0, "changes": []},
            "foreshadow": {
                "planted_count": 0,
                "resolved_count": 0,
                "skipped_resolve_count": 0,
            },
            "worldbuilding": {"updated": False, "fields": [], "facts": []},
            "errors": [],
        }

        character_states = self._as_dict_list(analysis_result.get("character_states"))
        organization_states = self._as_dict_list(analysis_result.get("organization_states"))
        foreshadows = self._as_dict_list(analysis_result.get("foreshadows"))
        worldbuilding_facts = self._as_dict_list(analysis_result.get("worldbuilding_facts"))

        if character_states:
            await self._safe_step(
                summary,
                "career",
                self._sync_careers(
                    db=db,
                    project_id=project_id,
                    character_states=character_states,
                    chapter_id=chapter_id,
                    chapter_number=chapter_number,
                ),
            )
            await self._safe_step(
                summary,
                "character_state",
                self._sync_character_states(
                    db=db,
                    project_id=project_id,
                    character_states=character_states,
                    chapter_id=chapter_id,
                    chapter_number=chapter_number,
                ),
            )
        else:
            logger.debug("📋 分析结果中无角色状态信息，跳过角色/职业运行态维护")

        if organization_states:
            await self._safe_step(
                summary,
                "organization_state",
                self._sync_organization_states(
                    db=db,
                    project_id=project_id,
                    organization_states=organization_states,
                    chapter_number=chapter_number,
                ),
            )
        else:
            logger.debug("📋 分析结果中无组织状态信息，跳过组织运行态维护")

        if foreshadows:
            await self._safe_step(
                summary,
                "foreshadow",
                self._sync_foreshadows(
                    db=db,
                    project_id=project_id,
                    chapter_id=chapter_id,
                    chapter_number=chapter_number,
                    foreshadows=foreshadows,
                ),
            )
        else:
            logger.debug("📋 分析结果中无伏笔信息，跳过伏笔运行态维护")

        if worldbuilding_facts:
            await self._safe_step(
                summary,
                "worldbuilding",
                self._sync_worldbuilding_facts(
                    db=db,
                    project_id=project_id,
                    chapter_number=chapter_number,
                    facts=worldbuilding_facts,
                ),
            )
        else:
            logger.debug("📋 分析结果中无世界观事实，跳过世界观运行态维护")

        logger.info(
            "✅ 章节运行态维护完成: "
            f"职业{summary['career'].get('updated_count', 0)}，"
            f"角色状态{summary['character_state'].get('state_updated_count', 0)}，"
            f"关系新增{summary['character_state'].get('relationship_created_count', 0)}，"
            f"关系更新{summary['character_state'].get('relationship_updated_count', 0)}，"
            f"组织{summary['organization_state'].get('updated_count', 0)}，"
            f"伏笔埋入{summary['foreshadow'].get('planted_count', 0)}，"
            f"伏笔回收{summary['foreshadow'].get('resolved_count', 0)}，"
            f"世界观{'更新' if summary['worldbuilding'].get('updated') else '无变化'}"
        )
        return summary

    async def _safe_step(self, summary: Dict[str, Any], key: str, coro: Any) -> None:
        try:
            result = await coro
            if isinstance(result, dict):
                summary[key] = result
        except Exception as exc:
            logger.error(f"⚠️ 运行态维护步骤失败[{key}]: {exc}", exc_info=True)
            summary["errors"].append({"step": key, "error": str(exc)})

    async def _sync_careers(
        self,
        *,
        db: AsyncSession,
        project_id: str,
        character_states: list[Dict[str, Any]],
        chapter_id: str,
        chapter_number: int,
    ) -> Dict[str, Any]:
        logger.info("💼 开始根据分析结果更新角色职业...")
        return await CareerUpdateService.update_careers_from_analysis(
            db=db,
            project_id=project_id,
            character_states=character_states,
            chapter_id=chapter_id,
            chapter_number=chapter_number,
        )

    async def _sync_character_states(
        self,
        *,
        db: AsyncSession,
        project_id: str,
        character_states: list[Dict[str, Any]],
        chapter_id: str,
        chapter_number: int,
    ) -> Dict[str, Any]:
        logger.info("👤 开始根据分析结果更新角色状态、关系和组织成员...")
        return await CharacterStateUpdateService.update_from_analysis(
            db=db,
            project_id=project_id,
            character_states=character_states,
            chapter_id=chapter_id,
            chapter_number=chapter_number,
        )

    async def _sync_organization_states(
        self,
        *,
        db: AsyncSession,
        project_id: str,
        organization_states: list[Dict[str, Any]],
        chapter_number: int,
    ) -> Dict[str, Any]:
        logger.info("🏛️ 开始根据分析结果更新组织自身状态...")
        return await CharacterStateUpdateService.update_organization_states(
            db=db,
            project_id=project_id,
            organization_states=organization_states,
            chapter_number=chapter_number,
        )

    async def _sync_foreshadows(
        self,
        *,
        db: AsyncSession,
        project_id: str,
        chapter_id: str,
        chapter_number: int,
        foreshadows: list[Dict[str, Any]],
    ) -> Dict[str, Any]:
        logger.info("🔮 开始根据分析结果自动更新伏笔状态...")
        return await foreshadow_service.auto_update_from_analysis(
            db=db,
            project_id=project_id,
            chapter_id=chapter_id,
            chapter_number=chapter_number,
            analysis_foreshadows=foreshadows,
        )

    async def _sync_worldbuilding_facts(
        self,
        *,
        db: AsyncSession,
        project_id: str,
        chapter_number: int,
        facts: list[Dict[str, Any]],
    ) -> Dict[str, Any]:
        project_result = await db.execute(select(Project).where(Project.id == project_id))
        project = project_result.scalar_one_or_none()
        if not project:
            return {"updated": False, "fields": [], "facts": []}

        changed_fields: set[str] = set()
        accepted_facts: list[str] = []
        for fact in facts:
            content = str(fact.get("content") or "").strip()
            if not content:
                continue
            field_name = self._world_field_for_fact(fact)
            line = self._format_world_fact_line(chapter_number, fact)
            current_value = str(getattr(project, field_name) or "")
            if self._already_contains_fact(current_value, content):
                continue
            setattr(project, field_name, self._append_fact_line(current_value, line))
            changed_fields.add(field_name)
            accepted_facts.append(content)

        if changed_fields:
            await db.commit()

        return {
            "updated": bool(changed_fields),
            "fields": sorted(changed_fields),
            "facts": accepted_facts,
        }

    def _world_field_for_fact(self, fact: Dict[str, Any]) -> str:
        category = f"{fact.get('category') or ''} {fact.get('keyword') or ''}".lower()
        if any(token in category for token in ("时间", "时代", "纪年", "历史", "time", "era")):
            return "world_time_period"
        if any(token in category for token in ("地点", "地理", "空间", "区域", "城市", "location", "place")):
            return "world_location"
        if any(token in category for token in ("氛围", "基调", "气氛", "tone", "atmosphere")):
            return "world_atmosphere"
        return "world_rules"

    def _format_world_fact_line(self, chapter_number: int, fact: Dict[str, Any]) -> str:
        category = str(fact.get("category") or "世界观").strip()
        content = str(fact.get("content") or "").strip()
        impact = str(fact.get("impact") or "").strip()
        suffix = f" 影响：{impact}" if impact and impact not in content else ""
        return f"- 第{chapter_number}章 [{category}] {content}{suffix}"

    def _already_contains_fact(self, current_value: str, content: str) -> bool:
        normalized_current = " ".join((current_value or "").split())
        normalized_content = " ".join((content or "").split())
        if not normalized_content:
            return True
        if normalized_content in normalized_current:
            return True
        return len(normalized_content) > 20 and normalized_content[:20] in normalized_current

    def _append_fact_line(self, current_value: str, line: str) -> str:
        current = (current_value or "").strip()
        if not current:
            return line
        return f"{current}\n{line}"

    def _as_dict_list(self, value: Any) -> list[Dict[str, Any]]:
        if not isinstance(value, list):
            return []
        return [item for item in value if isinstance(item, dict)]


story_runtime_maintenance_service = StoryRuntimeMaintenanceService()
