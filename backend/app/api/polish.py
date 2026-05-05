"""AI去味API - 核心特色功能"""
import json
from datetime import datetime
from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.api.common import verify_project_access
from app.api.settings import get_user_ai_service_from_db_by_usage
from app.database import get_db, get_engine
from app.models.generation_history import GenerationHistory
from app.models.character import Character
from app.models.outline import Outline
from app.models.project import Project
from app.models.relationship import Organization
from app.schemas.polish import (
    CharacterOptimizeTaskRequest,
    OutlineOptimizeTaskRequest,
    PolishRequest,
    PolishResponse,
)
from app.services.ai_service import AIService
from app.services.background_task_service import background_task_service, TaskProgressTracker
from app.services.prompt_service import PromptService
from app.utils.sse_response import (
    HEARTBEAT,
    WizardProgressTracker,
    create_sse_response,
    wrap_stream_with_heartbeat,
)
from app.logger import get_logger

router = APIRouter(prefix="/polish", tags=["AI去味"])
logger = get_logger(__name__)

POLISH_MAX_TOKENS_CEILING = 32000
POLISH_DEFAULT_MIN_TOKENS = 8192
POLISH_INSTRUCTION_MIN_TOKENS = 12000


async def _get_polish_ai_service(
    *,
    request: Request,
    db: AsyncSession,
) -> AIService:
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(status_code=401, detail="未登录")
    return await get_user_ai_service_from_db_by_usage(user_id, db, usage="polish")


def _extract_generated_text(response) -> str:
    """AIService returns a response dict; older callers expected a plain string."""
    if isinstance(response, str):
        return response
    if isinstance(response, dict):
        content = response.get("content", "")
        return content if isinstance(content, str) else str(content or "")
    return str(response or "")


def _finish_reason(response) -> str:
    if not isinstance(response, dict):
        return ""
    reason = response.get("finish_reason") or response.get("finishReason") or ""
    return str(reason)


def _polish_max_tokens(text: str, *, has_instruction: bool = False, retry: bool = False) -> int:
    minimum = POLISH_INSTRUCTION_MIN_TOKENS if has_instruction else POLISH_DEFAULT_MIN_TOKENS
    if retry:
        minimum = min(minimum * 2, POLISH_MAX_TOKENS_CEILING)
    requested = max(len(text or "") * 3, minimum)
    return min(requested, POLISH_MAX_TOKENS_CEILING)


def _ensure_non_empty_result(text: str, response, operation: str) -> str:
    if text.strip():
        return text
    reason = _finish_reason(response)
    if reason == "length":
        raise HTTPException(status_code=502, detail=f"{operation}失败: AI输出额度耗尽但未返回正文，请换用非推理模型或更高输出上限")
    raise HTTPException(status_code=502, detail=f"{operation}失败: AI返回空内容")


def _needs_empty_length_retry(response) -> bool:
    return _finish_reason(response) == "length" and not _extract_generated_text(response).strip()


async def _generate_polish_response(
    ai_service: AIService,
    *,
    prompt: str,
    source_text: str,
    has_instruction: bool,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    temperature: Optional[float] = 0.7,
    operation: str,
):
    max_tokens = _polish_max_tokens(source_text, has_instruction=has_instruction)
    response = await ai_service.generate_text(
        prompt=prompt,
        provider=provider,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        auto_mcp=False,
    )

    if not _needs_empty_length_retry(response):
        return response

    retry_max_tokens = _polish_max_tokens(source_text, has_instruction=has_instruction, retry=True)
    if retry_max_tokens <= max_tokens:
        return response

    logger.warning(
        "%s输出为空且触发length，自动提高max_tokens重试: %s -> %s, model=%s",
        operation,
        max_tokens,
        retry_max_tokens,
        model or "default",
    )
    return await ai_service.generate_text(
        prompt=prompt,
        provider=provider,
        model=model,
        temperature=temperature,
        max_tokens=retry_max_tokens,
        auto_mcp=False,
    )


def _strip_code_fence(text: str) -> str:
    cleaned = (text or "").strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
    return cleaned.strip()


def _parse_json_object(text: str) -> Optional[Dict[str, Any]]:
    cleaned = _strip_code_fence(text)
    try:
        data = json.loads(cleaned)
        return data if isinstance(data, dict) else None
    except Exception:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return None
        try:
            data = json.loads(cleaned[start:end + 1])
            return data if isinstance(data, dict) else None
        except Exception:
            return None


def _string_value(data: Optional[Dict[str, Any]], key: str) -> Optional[str]:
    value = data.get(key) if data else None
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _string_list_value(data: Optional[Dict[str, Any]], key: str) -> Optional[list[str]]:
    value = data.get(key) if data else None
    if not isinstance(value, list):
        return None
    items = [item.strip() for item in value if isinstance(item, str) and item.strip()]
    return items or None


def _load_structure(structure: Optional[str]) -> Dict[str, Any]:
    if not structure:
        return {}
    try:
        data = json.loads(structure)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _build_outline_optimize_source(outline: Outline, structure: Dict[str, Any], project: Project) -> str:
    return json.dumps({
        "project_title": project.title,
        "order_index": outline.order_index,
        "title": outline.title,
        "content": outline.content or "",
        "structure": structure,
    }, ensure_ascii=False, indent=2)


def _build_character_optimize_source(character: Character, organization: Optional[Organization]) -> str:
    if character.is_organization:
        return json.dumps({
            "type": "organization",
            "name": character.name,
            "organization_type": character.organization_type or "",
            "organization_purpose": character.organization_purpose or "",
            "power_level": organization.power_level if organization else None,
            "location": organization.location if organization else "",
            "motto": organization.motto if organization else "",
            "color": organization.color if organization else "",
            "background": character.background or "",
        }, ensure_ascii=False, indent=2)

    return json.dumps({
        "type": "character",
        "name": character.name,
        "role_type": character.role_type or "",
        "age": character.age or "",
        "gender": character.gender or "",
        "personality": character.personality or "",
        "appearance": character.appearance or "",
        "background": character.background or "",
    }, ensure_ascii=False, indent=2)


async def _generate_optimized_text(
    ai_service: AIService,
    source: str,
    template_key: str,
    user_id: str,
    db: AsyncSession,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    temperature: Optional[float] = 0.6,
) -> str:
    template = await PromptService.get_template(template_key, user_id, db)
    if not template:
        template = getattr(PromptService, template_key, None)
    if not template:
        raise ValueError(f"未找到优化提示词模板: {template_key}")

    if "{source}" in template:
        prompt = PromptService.format_prompt(template, source=source)
    else:
        prompt = f"{template}\n\n请处理以下内容：\n{source}"

    response = await _generate_polish_response(
        ai_service,
        prompt=prompt,
        source_text=source,
        has_instruction=True,
        provider=provider,
        model=model,
        temperature=temperature,
        operation="AI优化",
    )
    return _ensure_non_empty_result(_extract_generated_text(response), response, "AI优化")


async def _build_denoising_prompt(original_text: str, user_id: Optional[str], db: AsyncSession) -> str:
    template = await PromptService.get_template_with_fallback("AI_DENOISING", user_id, db)
    if not template:
        template = PromptService.AI_DENOISING
    return PromptService.format_prompt(template, original_text=original_text)


@router.post("", response_model=PolishResponse, summary="AI去味")
async def polish_text(
    request: PolishRequest,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    AI去味 - 将AI生成的文本改写得更像人类作家的手笔
    
    核心功能：
    - 去除AI痕迹（工整排比、重复修辞、机械总结）
    - 增加人性化（口语化、不完美细节、真实情感）
    - 优化叙事（自然节奏、简单词汇、松弛感）
    - 让对话更生活化
    
    这是本项目的核心特色功能！
    """
    try:
        # 获取用户ID
        user_id = getattr(http_request.state, 'user_id', None)
        user_ai_service = await _get_polish_ai_service(request=http_request, db=db)

        if request.project_id:
            await verify_project_access(request.project_id, user_id, db)
        
        if request.instruction:
            prompt = (
                f"{request.instruction.strip()}\n\n"
                "请处理以下内容：\n"
                f"{request.original_text}"
            )
        else:
            prompt = await _build_denoising_prompt(request.original_text, user_id, db)
        
        logger.info(f"开始AI去味处理，原文长度: {len(request.original_text)}")
        
        # 调用AI进行去味处理
        ai_response = await _generate_polish_response(
            user_ai_service,
            prompt=prompt,
            source_text=request.original_text,
            has_instruction=bool(request.instruction),
            provider=request.provider,
            model=request.model,
            temperature=request.temperature,
            operation="AI去味",
        )
        polished_text = _ensure_non_empty_result(_extract_generated_text(ai_response), ai_response, "AI去味")
        
        # 计算字数
        word_count_before = len(request.original_text)
        word_count_after = len(polished_text)
        
        logger.info(f"AI去味完成，处理后长度: {word_count_after}")
        
        # 如果提供了项目ID，记录到历史
        if request.project_id:
            history = GenerationHistory(
                project_id=request.project_id,
                prompt=f"原文: {request.original_text[:100]}...",
                generated_content=polished_text,
                model=request.model or "default"
            )
            db.add(history)
            await db.commit()
        
        return PolishResponse(
            original_text=request.original_text,
            polished_text=polished_text,
            word_count_before=word_count_before,
            word_count_after=word_count_after
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"AI去味失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"AI去味失败: {str(e)}")


@router.post("/stream", summary="AI去味/润色（SSE流式）")
async def polish_text_stream(
    request: PolishRequest,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    AI去味/润色流式接口。

    与普通 /polish 使用相同请求体和提示词构建方式，但通过 SSE 逐块返回内容，
    前端可边生成边预览，完成后再决定是否应用。
    """
    user_id = getattr(http_request.state, 'user_id', None)
    user_ai_service = await _get_polish_ai_service(request=http_request, db=db)

    if request.project_id:
        await verify_project_access(request.project_id, user_id, db)

    if request.instruction:
        prompt = (
            f"{request.instruction.strip()}\n\n"
            "请处理以下内容：\n"
            f"{request.original_text}"
        )
    else:
        prompt = await _build_denoising_prompt(request.original_text, user_id, db)

    has_instruction = bool(request.instruction)
    max_tokens = _polish_max_tokens(request.original_text, has_instruction=has_instruction)

    async def _stream_generator():
        tracker = WizardProgressTracker("AI润色")
        accumulated = ""
        estimated_total = max(len(request.original_text), 1200)

        try:
            logger.info(f"开始流式AI去味处理，原文长度: {len(request.original_text)}")
            yield await tracker.start("开始AI润色...")
            yield await tracker.preparing("准备润色提示词...")

            async for chunk in wrap_stream_with_heartbeat(
                user_ai_service.generate_text_stream(
                    prompt=prompt,
                    provider=request.provider,
                    model=request.model,
                    temperature=request.temperature,
                    max_tokens=max_tokens,
                    auto_mcp=False,
                )
            ):
                if chunk is HEARTBEAT:
                    yield await tracker.heartbeat()
                    continue

                content = chunk.get("content", "") if isinstance(chunk, dict) else str(chunk or "")
                if not content:
                    continue

                accumulated += content
                yield await tracker.generating(
                    current_chars=len(accumulated),
                    estimated_total=estimated_total,
                    message="AI润色中..."
                )
                yield await tracker.generating_chunk(content)

            polished_text = accumulated.strip()
            if not polished_text:
                yield await tracker.error("AI未返回可用润色内容，请调整要求或更换模型后重试", 502)
                return

            if request.project_id:
                history = GenerationHistory(
                    project_id=request.project_id,
                    prompt=f"原文: {request.original_text[:100]}...",
                    generated_content=polished_text,
                    model=request.model or "default"
                )
                db.add(history)
                await db.commit()

            yield await tracker.complete("AI润色完成")
            yield await tracker.result({
                "original_text": request.original_text,
                "polished_text": polished_text,
                "word_count_before": len(request.original_text),
                "word_count_after": len(polished_text),
            })
            yield await tracker.done()
            logger.info(f"流式AI去味完成，处理后长度: {len(polished_text)}")
        except Exception as e:
            logger.error(f"流式AI去味失败: {str(e)}", exc_info=True)
            yield await tracker.error(f"AI去味失败: {str(e)}", 500)

    return create_sse_response(_stream_generator())


@router.post("/outlines/background", summary="后台优化已有大纲")
async def optimize_outlines_background(
    data: OutlineOptimizeTaskRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """创建后台任务优化已有大纲，进度和取消走统一后台任务面板。"""
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(status_code=401, detail="未登录")

    await verify_project_access(data.project_id, user_id, db)

    if data.outline_ids:
        result = await db.execute(
            select(Outline.id).where(
                Outline.project_id == data.project_id,
                Outline.id.in_(data.outline_ids)
            )
        )
        found_ids = {row[0] for row in result.all()}
        missing_count = len(set(data.outline_ids) - found_ids)
        if missing_count:
            raise HTTPException(status_code=400, detail=f"有 {missing_count} 条大纲不存在或不属于当前项目")

    task = await background_task_service.create_task(
        user_id=user_id,
        project_id=data.project_id,
        task_type="outline_optimize",
        task_input=data.model_dump(),
        db=db,
    )
    await background_task_service.spawn_background_task(
        task.id,
        user_id,
        _run_outline_optimize_background,
        data.model_dump(),
    )

    return {
        "task_id": task.id,
        "task_type": "outline_optimize",
        "status": "pending",
        "message": "大纲优化任务已创建，请通过后台任务面板查看进度"
    }


@router.post("/characters/background", summary="后台优化角色/组织设定")
async def optimize_characters_background(
    data: CharacterOptimizeTaskRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """创建后台任务优化角色/组织设定，进度和取消走统一后台任务面板。"""
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(status_code=401, detail="未登录")

    await verify_project_access(data.project_id, user_id, db)

    if not data.character_ids:
        raise HTTPException(status_code=400, detail="请选择要优化的角色或组织")

    result = await db.execute(
        select(Character.id).where(
            Character.project_id == data.project_id,
            Character.id.in_(data.character_ids)
        )
    )
    found_ids = {row[0] for row in result.all()}
    missing_count = len(set(data.character_ids) - found_ids)
    if missing_count:
        raise HTTPException(status_code=400, detail=f"有 {missing_count} 个角色/组织不存在或不属于当前项目")

    task = await background_task_service.create_task(
        user_id=user_id,
        project_id=data.project_id,
        task_type="character_optimize",
        task_input=data.model_dump(),
        db=db,
    )
    await background_task_service.spawn_background_task(
        task.id,
        user_id,
        _run_character_optimize_background,
        data.model_dump(),
    )

    return {
        "task_id": task.id,
        "task_type": "character_optimize",
        "status": "pending",
        "message": "角色设定优化任务已创建，请通过后台任务面板查看进度"
    }


async def _run_outline_optimize_background(task_id: str, user_id: str, data: Dict[str, Any]):
    engine = await get_engine(user_id)
    AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with AsyncSessionLocal() as bg_db:
        tracker = TaskProgressTracker(task_id, user_id, "大纲优化")
        try:
            if await tracker.check_cancelled():
                return
            await tracker.start("开始优化已有大纲...")

            project_id = data["project_id"]
            outline_ids = data.get("outline_ids")

            await tracker.loading("加载项目信息...", 0.4)
            project_result = await bg_db.execute(select(Project).where(Project.id == project_id))
            project = project_result.scalar_one_or_none()
            if not project:
                raise ValueError("项目不存在")

            await tracker.loading("加载大纲列表...", 0.8)
            query = select(Outline).where(Outline.project_id == project_id)
            if outline_ids:
                query = query.where(Outline.id.in_(outline_ids))
            query = query.order_by(Outline.order_index)
            outlines_result = await bg_db.execute(query)
            outlines = outlines_result.scalars().all()
            if not outlines:
                raise ValueError("没有可优化的大纲")

            ai_service = await get_user_ai_service_from_db_by_usage(user_id, bg_db, usage="polish")
            total = len(outlines)
            succeeded = 0
            failed: list[Dict[str, str]] = []

            await tracker.preparing(f"共 {total} 条大纲，准备逐条优化...")
            for idx, outline in enumerate(outlines):
                if await tracker.check_cancelled():
                    return

                await tracker.generating(
                    current_chars=idx,
                    estimated_total=total,
                    message=f"正在优化 {idx + 1}/{total}：{outline.title}"
                )

                try:
                    structure = _load_structure(outline.structure)
                    source = _build_outline_optimize_source(outline, structure, project)
                    optimized_text = await _generate_optimized_text(
                        ai_service=ai_service,
                        source=source,
                        template_key="OUTLINE_OPTIMIZE",
                        user_id=user_id,
                        db=bg_db,
                        provider=data.get("provider"),
                        model=data.get("model"),
                        temperature=data.get("temperature") or 0.6,
                    )
                    parsed = _parse_json_object(optimized_text)
                    content = (
                        _string_value(parsed, "content")
                        or _string_value(parsed, "summary")
                        or _strip_code_fence(optimized_text)
                    )
                    if not content:
                        raise ValueError("AI优化结果为空")

                    next_structure = {
                        **structure,
                        "summary": content,
                        "content": content,
                    }
                    key_points = _string_list_value(parsed, "key_points")
                    key_events = _string_list_value(parsed, "key_events")
                    emotion = _string_value(parsed, "emotion")
                    goal = _string_value(parsed, "goal")

                    if key_points:
                        next_structure["key_points"] = key_points
                    if key_events:
                        next_structure["key_events"] = key_events
                    if emotion:
                        next_structure["emotion"] = emotion
                    if goal:
                        next_structure["goal"] = goal

                    outline.content = content
                    outline.structure = json.dumps(next_structure, ensure_ascii=False, indent=2)
                    outline.updated_at = datetime.now()
                    await bg_db.commit()
                    succeeded += 1
                except Exception as item_error:
                    await bg_db.rollback()
                    failed.append({"id": outline.id, "title": outline.title, "error": str(item_error)})
                    logger.error(f"优化大纲失败: {outline.title} - {item_error}", exc_info=True)

            result = {"total": total, "succeeded": succeeded, "failed": failed}
            await tracker.saving("保存优化结果...", 1)
            await tracker._update_task(task_result=result)
            if failed:
                await tracker.complete(f"大纲优化完成：成功 {succeeded} 条，失败 {len(failed)} 条")
            else:
                await tracker.complete(f"大纲优化完成，共 {succeeded} 条")
        except Exception as e:
            logger.error(f"后台大纲优化失败: {e}", exc_info=True)
            await tracker.error(str(e))


async def _run_character_optimize_background(task_id: str, user_id: str, data: Dict[str, Any]):
    engine = await get_engine(user_id)
    AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with AsyncSessionLocal() as bg_db:
        tracker = TaskProgressTracker(task_id, user_id, "角色设定优化")
        try:
            if await tracker.check_cancelled():
                return
            await tracker.start("开始优化角色/组织设定...")

            project_id = data["project_id"]
            character_ids = data["character_ids"]

            await tracker.loading("加载角色列表...", 0.6)
            characters_result = await bg_db.execute(
                select(Character)
                .where(Character.project_id == project_id, Character.id.in_(character_ids))
                .order_by(Character.created_at)
            )
            characters = characters_result.scalars().all()
            if not characters:
                raise ValueError("没有可优化的角色或组织")

            ai_service = await get_user_ai_service_from_db_by_usage(user_id, bg_db, usage="polish")
            total = len(characters)
            succeeded = 0
            failed: list[Dict[str, str]] = []

            await tracker.preparing(f"共 {total} 个角色/组织，准备逐个优化...")
            for idx, character in enumerate(characters):
                if await tracker.check_cancelled():
                    return

                await tracker.generating(
                    current_chars=idx,
                    estimated_total=total,
                    message=f"正在优化 {idx + 1}/{total}：{character.name}"
                )

                try:
                    organization = None
                    if character.is_organization:
                        org_result = await bg_db.execute(
                            select(Organization).where(Organization.character_id == character.id)
                        )
                        organization = org_result.scalar_one_or_none()

                    source = _build_character_optimize_source(character, organization)
                    optimized_text = await _generate_optimized_text(
                        ai_service=ai_service,
                        source=source,
                        template_key="ORGANIZATION_OPTIMIZE" if character.is_organization else "CHARACTER_OPTIMIZE",
                        user_id=user_id,
                        db=bg_db,
                        provider=data.get("provider"),
                        model=data.get("model"),
                        temperature=data.get("temperature") or 0.6,
                    )
                    parsed = _parse_json_object(optimized_text)
                    if not parsed:
                        raise ValueError("AI返回格式无法识别")

                    if character.is_organization:
                        purpose = _string_value(parsed, "organization_purpose")
                        motto = _string_value(parsed, "motto")
                        background = _string_value(parsed, "background")
                        if purpose:
                            character.organization_purpose = purpose
                        if background:
                            character.background = background
                        if motto:
                            if organization:
                                organization.motto = motto
                            else:
                                organization = Organization(
                                    character_id=character.id,
                                    project_id=character.project_id,
                                    member_count=0,
                                    motto=motto,
                                )
                                bg_db.add(organization)
                    else:
                        personality = _string_value(parsed, "personality")
                        appearance = _string_value(parsed, "appearance")
                        background = _string_value(parsed, "background")
                        if personality:
                            character.personality = personality
                        if appearance:
                            character.appearance = appearance
                        if background:
                            character.background = background

                    character.updated_at = datetime.now()
                    await bg_db.commit()
                    succeeded += 1
                except Exception as item_error:
                    await bg_db.rollback()
                    failed.append({"id": character.id, "name": character.name, "error": str(item_error)})
                    logger.error(f"优化角色设定失败: {character.name} - {item_error}", exc_info=True)

            result = {"total": total, "succeeded": succeeded, "failed": failed}
            await tracker.saving("保存优化结果...", 1)
            await tracker._update_task(task_result=result)
            if failed:
                await tracker.complete(f"角色设定优化完成：成功 {succeeded} 个，失败 {len(failed)} 个")
            else:
                await tracker.complete(f"角色设定优化完成，共 {succeeded} 个")
        except Exception as e:
            logger.error(f"后台角色设定优化失败: {e}", exc_info=True)
            await tracker.error(str(e))


@router.post("/batch", summary="批量AI去味")
async def polish_batch(
    payload: Any = Body(...),
    project_id: Optional[str] = None,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    http_request: Request = None,
    db: AsyncSession = Depends(get_db),
):
    """
    批量处理多个文本的AI去味
    
    适用于一次性处理多个章节或段落
    """
    try:
        # 获取用户ID
        user_id = getattr(http_request.state, 'user_id', None) if http_request else None
        if not user_id:
            raise HTTPException(status_code=401, detail="未登录")
        user_ai_service = await get_user_ai_service_from_db_by_usage(user_id, db, usage="polish")

        if isinstance(payload, dict):
            texts = payload.get("texts") or []
            project_id = payload.get("project_id") or project_id
            provider = payload.get("provider") or provider
            model = payload.get("model") or model
        else:
            texts = payload

        if project_id:
            await verify_project_access(project_id, user_id, db)

        if not isinstance(texts, list) or not all(isinstance(text, str) for text in texts):
            raise HTTPException(status_code=400, detail="texts 必须是字符串数组")
        
        results = []
        
        for idx, text in enumerate(texts):
            logger.info(f"处理第 {idx+1}/{len(texts)} 个文本")
            
            prompt = await _build_denoising_prompt(text, user_id, db)
            
            ai_response = await user_ai_service.generate_text(
                prompt=prompt,
                provider=provider,
                model=model,
                temperature=0.8,
                max_tokens=_polish_max_tokens(text)
            )
            polished_text = _ensure_non_empty_result(_extract_generated_text(ai_response), ai_response, "批量AI去味")
            
            results.append({
                "index": idx,
                "original": text,
                "polished": polished_text,
                "word_count_before": len(text),
                "word_count_after": len(polished_text)
            })
        
        logger.info(f"批量AI去味完成，共处理 {len(results)} 个文本")
        
        return {
            "total": len(results),
            "polished_texts": [item["polished"] for item in results],
            "results": results
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"批量AI去味失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"批量AI去味失败: {str(e)}")
