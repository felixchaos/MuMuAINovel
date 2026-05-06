"""角色管理API"""
from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
import json
from typing import Any, AsyncGenerator, Dict, List, Optional

from app.database import get_db
from app.utils.sse_response import SSEResponse, create_sse_response, WizardProgressTracker, wrap_stream_with_heartbeat, HEARTBEAT
from app.models.character import Character
from app.models.project import Project
from app.models.generation_history import GenerationHistory
from app.models.relationship import CharacterRelationship, Organization, OrganizationMember, RelationshipType
from app.schemas.character import (
    CharacterCreate,
    CharacterUpdate,
    CharacterResponse,
    CharacterListResponse,
    CharacterAnalyzeFromTextRequest,
    CharacterGenerateRequest,
    CharacterBatchRegenerateRequest
)
from app.services.ai_service import AIService
from app.services.json_helper import loads_json
from app.services.name_authority_service import build_name_authority
from app.services.prompt_service import prompt_service, PromptService
from app.services.import_export_service import ImportExportService
from app.services.project_story_context import build_project_story_context
from app.schemas.import_export import CharactersExportRequest, CharactersImportResult
from app.logger import get_logger
from app.api.settings import get_user_ai_service
from app.api.common import verify_project_access

router = APIRouter(prefix="/characters", tags=["角色管理"])
logger = get_logger(__name__)


def _compact_character_text(value: Any, limit: int = 1200) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "..."


def _normalize_role_type(value: Any) -> str:
    raw = str(value or "").strip().lower()
    mapping = {
        "protagonist": "protagonist",
        "main": "protagonist",
        "主角": "protagonist",
        "核心主角": "protagonist",
        "supporting": "supporting",
        "secondary": "supporting",
        "配角": "supporting",
        "重要配角": "supporting",
        "antagonist": "antagonist",
        "villain": "antagonist",
        "反派": "antagonist",
        "敌对": "antagonist",
    }
    return mapping.get(raw, "supporting")


def _normalize_traits(value: Any) -> Optional[str]:
    if not value:
        return None
    if isinstance(value, list):
        items = [str(item).strip() for item in value if str(item).strip()]
        return json.dumps(items[:12], ensure_ascii=False) if items else None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                return _normalize_traits(parsed)
        except Exception:
            pass
        items = [item.strip() for item in text.replace("，", ",").split(",") if item.strip()]
        return json.dumps(items[:12], ensure_ascii=False) if items else None
    return None


def _extract_character_items(ai_data: Any) -> List[Dict[str, Any]]:
    if isinstance(ai_data, list):
        return [item for item in ai_data if isinstance(item, dict)]
    if isinstance(ai_data, dict):
        for key in ("characters", "items", "roles"):
            items = ai_data.get(key)
            if isinstance(items, list):
                return [item for item in items if isinstance(item, dict)]
    return []


def _apply_character_analysis(
    character: Character,
    data: Dict[str, Any],
    *,
    overwrite_existing: bool,
) -> bool:
    changed = False
    field_map = {
        "age": "age",
        "gender": "gender",
        "personality": "personality",
        "background": "background",
        "appearance": "appearance",
    }

    role_type = _normalize_role_type(data.get("role_type"))
    if role_type and (overwrite_existing or not character.role_type):
        if character.role_type != role_type:
            character.role_type = role_type
            changed = True

    for source_key, attr in field_map.items():
        value = _compact_character_text(data.get(source_key), 2000 if attr in {"background", "personality"} else 1200)
        if not value:
            continue
        current = str(getattr(character, attr) or "").strip()
        if overwrite_existing or not current:
            if current != value:
                setattr(character, attr, value)
                changed = True

    traits = _normalize_traits(data.get("traits"))
    if traits and (overwrite_existing or not character.traits):
        if character.traits != traits:
            character.traits = traits
            changed = True

    return changed


async def _build_relationships_summary(character_id: str, project_id: str, db: AsyncSession) -> str:
    """从 character_relationships 表构建角色关系摘要文本"""
    from sqlalchemy import or_
    
    # 查询该角色参与的所有关系
    rels_result = await db.execute(
        select(CharacterRelationship).where(
            CharacterRelationship.project_id == project_id,
            or_(
                CharacterRelationship.character_from_id == character_id,
                CharacterRelationship.character_to_id == character_id
            )
        )
    )
    rels = rels_result.scalars().all()
    
    if not rels:
        return ""
    
    # 收集所有相关角色ID
    related_ids = set()
    for r in rels:
        related_ids.add(r.character_from_id)
        related_ids.add(r.character_to_id)
    related_ids.discard(character_id)
    
    if not related_ids:
        return ""
    
    # 批量查询角色名称
    chars_result = await db.execute(
        select(Character.id, Character.name).where(Character.id.in_(related_ids))
    )
    name_map = {row.id: row.name for row in chars_result}
    
    # 构建摘要
    parts = []
    for r in rels:
        if r.character_from_id == character_id:
            target_name = name_map.get(r.character_to_id, "未知")
            rel_name = r.relationship_name or "相关"
        else:
            target_name = name_map.get(r.character_from_id, "未知")
            rel_name = r.relationship_name or "相关"
        parts.append(f"与{target_name}：{rel_name}")
    
    return "；".join(parts)


async def _build_org_members_summary(character_id: str, db: AsyncSession) -> str:
    """从 organization_members 表构建组织成员JSON字符串（与schema契约保持一致）"""
    # 先查找该角色对应的 Organization 记录
    org_result = await db.execute(
        select(Organization).where(Organization.character_id == character_id)
    )
    org = org_result.scalar_one_or_none()
    if not org:
        return ""

    # 查询该组织的所有成员（按职级倒序，保证展示顺序稳定）
    members_result = await db.execute(
        select(OrganizationMember)
        .where(OrganizationMember.organization_id == org.id)
        .order_by(OrganizationMember.rank.desc(), OrganizationMember.created_at)
    )
    members = members_result.scalars().all()
    if not members:
        return ""

    # 批量查询成员角色名称
    member_char_ids = [m.character_id for m in members]
    chars_result = await db.execute(
        select(Character.id, Character.name).where(Character.id.in_(member_char_ids))
    )
    name_map = {row.id: row.name for row in chars_result}

    # 返回 JSON 字符串数组，避免前端 JSON.parse 报错
    member_items = []
    for m in members:
        name = name_map.get(m.character_id, "未知")
        position = m.position or "成员"
        member_items.append(f"{name}（{position}）")

    return json.dumps(member_items, ensure_ascii=False)


@router.get("", response_model=CharacterListResponse, summary="获取角色列表")
async def get_characters(
    project_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """获取指定项目的所有角色（query参数版本）"""
    # 验证用户权限
    user_id = getattr(request.state, 'user_id', None)
    await verify_project_access(project_id, user_id, db)
    
    # 获取总数
    count_result = await db.execute(
        select(func.count(Character.id)).where(Character.project_id == project_id)
    )
    total = count_result.scalar_one()
    
    # 获取角色列表
    result = await db.execute(
        select(Character)
        .where(Character.project_id == project_id)
        .order_by(Character.created_at.desc())
    )
    characters = result.scalars().all()
    
    # 为角色填充关系摘要、组织额外字段、职业信息
    enriched_characters = []
    for char in characters:
        # 从 character_relationships 表动态生成关系摘要
        rel_summary = await _build_relationships_summary(char.id, project_id, db)
        
        char_dict = {
            "id": char.id,
            "project_id": char.project_id,
            "name": char.name,
            "age": char.age,
            "gender": char.gender,
            "is_organization": char.is_organization,
            "role_type": char.role_type,
            "personality": char.personality,
            "background": char.background,
            "appearance": char.appearance,
            "relationships": rel_summary,
            "organization_type": char.organization_type,
            "organization_purpose": char.organization_purpose,
            "organization_members": await _build_org_members_summary(char.id, db) if char.is_organization else "",
            "traits": char.traits,
            "avatar_url": char.avatar_url,
            "created_at": char.created_at,
            "updated_at": char.updated_at,
            "power_level": None,
            "location": None,
            "motto": None,
            "color": None,
            "main_career_id": char.main_career_id,
            "main_career_stage": char.main_career_stage,
            "sub_careers": json.loads(char.sub_careers) if char.sub_careers else None
        }
        
        if char.is_organization:
            org_result = await db.execute(
                select(Organization).where(Organization.character_id == char.id)
            )
            org = org_result.scalar_one_or_none()
            if org:
                char_dict.update({
                    "power_level": org.power_level,
                    "location": org.location,
                    "motto": org.motto,
                    "color": org.color
                })
        
        enriched_characters.append(char_dict)
    
    return CharacterListResponse(total=total, items=enriched_characters)


@router.get("/project/{project_id}", response_model=CharacterListResponse, summary="获取项目的所有角色")
async def get_project_characters(
    project_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """获取指定项目的所有角色（路径参数版本）"""
    # 验证用户权限
    user_id = getattr(request.state, 'user_id', None)
    await verify_project_access(project_id, user_id, db)
    
    # 获取总数
    count_result = await db.execute(
        select(func.count(Character.id)).where(Character.project_id == project_id)
    )
    total = count_result.scalar_one()
    
    # 获取角色列表
    result = await db.execute(
        select(Character)
        .where(Character.project_id == project_id)
        .order_by(Character.created_at.desc())
    )
    characters = result.scalars().all()
    
    # 为角色填充关系摘要、组织额外字段、职业信息
    enriched_characters = []
    for char in characters:
        # 从 character_relationships 表动态生成关系摘要
        rel_summary = await _build_relationships_summary(char.id, project_id, db)
        
        char_dict = {
            "id": char.id,
            "project_id": char.project_id,
            "name": char.name,
            "age": char.age,
            "gender": char.gender,
            "is_organization": char.is_organization,
            "role_type": char.role_type,
            "personality": char.personality,
            "background": char.background,
            "appearance": char.appearance,
            "relationships": rel_summary,
            "organization_type": char.organization_type,
            "organization_purpose": char.organization_purpose,
            "organization_members": await _build_org_members_summary(char.id, db) if char.is_organization else "",
            "traits": char.traits,
            "avatar_url": char.avatar_url,
            "created_at": char.created_at,
            "updated_at": char.updated_at,
            "power_level": None,
            "location": None,
            "motto": None,
            "color": None,
            "main_career_id": char.main_career_id,
            "main_career_stage": char.main_career_stage,
            "sub_careers": json.loads(char.sub_careers) if char.sub_careers else None
        }
        
        if char.is_organization:
            org_result = await db.execute(
                select(Organization).where(Organization.character_id == char.id)
            )
            org = org_result.scalar_one_or_none()
            if org:
                char_dict.update({
                    "power_level": org.power_level,
                    "location": org.location,
                    "motto": org.motto,
                    "color": org.color
                })
        
        enriched_characters.append(char_dict)
    
    return CharacterListResponse(total=total, items=enriched_characters)


@router.get("/{character_id}", response_model=CharacterResponse, summary="获取角色详情")
async def get_character(
    character_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """根据ID获取角色详情"""
    result = await db.execute(
        select(Character).where(Character.id == character_id)
    )
    character = result.scalar_one_or_none()
    
    if not character:
        raise HTTPException(status_code=404, detail="角色不存在")
    
    # 验证用户权限
    user_id = getattr(request.state, 'user_id', None)
    await verify_project_access(character.project_id, user_id, db)
    
    # 从 character_relationships 表动态生成关系摘要
    rel_summary = await _build_relationships_summary(character.id, character.project_id, db)
    
    char_dict = {
        "id": character.id,
        "project_id": character.project_id,
        "name": character.name,
        "age": character.age,
        "gender": character.gender,
        "is_organization": character.is_organization,
        "role_type": character.role_type,
        "personality": character.personality,
        "background": character.background,
        "appearance": character.appearance,
        "relationships": rel_summary,
        "organization_type": character.organization_type,
        "organization_purpose": character.organization_purpose,
        "organization_members": await _build_org_members_summary(character.id, db) if character.is_organization else "",
        "traits": character.traits,
        "avatar_url": character.avatar_url,
        "created_at": character.created_at,
        "updated_at": character.updated_at,
        "power_level": None,
        "location": None,
        "motto": None,
        "color": None,
        "main_career_id": character.main_career_id,
        "main_career_stage": character.main_career_stage,
        "sub_careers": json.loads(character.sub_careers) if character.sub_careers else None
    }
    
    if character.is_organization:
        org_result = await db.execute(
            select(Organization).where(Organization.character_id == character.id)
        )
        org = org_result.scalar_one_or_none()
        if org:
            char_dict.update({
                "power_level": org.power_level,
                "location": org.location,
                "motto": org.motto,
                "color": org.color
            })
    
    return char_dict


@router.put("/{character_id}", response_model=CharacterResponse, summary="更新角色")
async def update_character(
    character_id: str,
    character_update: CharacterUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """更新角色信息"""
    from app.models.career import CharacterCareer, Career
    
    result = await db.execute(
        select(Character).where(Character.id == character_id)
    )
    character = result.scalar_one_or_none()
    
    if not character:
        raise HTTPException(status_code=404, detail="角色不存在")
    
    # 验证用户权限
    user_id = getattr(request.state, 'user_id', None)
    await verify_project_access(character.project_id, user_id, db)
    
    # 更新字段
    update_data = character_update.model_dump(exclude_unset=True)
    
    # 如果是组织，需要同步更新 Organization 表的字段
    org_fields = {}
    if character.is_organization:
        # 提取需要同步到 Organization 表的字段
        if 'power_level' in update_data:
            org_fields['power_level'] = update_data.pop('power_level')
        if 'location' in update_data:
            org_fields['location'] = update_data.pop('location')
        if 'motto' in update_data:
            org_fields['motto'] = update_data.pop('motto')
        if 'color' in update_data:
            org_fields['color'] = update_data.pop('color')
    
    # 处理主职业和副职业更新
    main_career_id = update_data.pop('main_career_id', None)
    main_career_stage = update_data.pop('main_career_stage', None)
    sub_careers_json = update_data.pop('sub_careers', None)
    
    if main_career_id is not None:
        # 验证职业存在
        if main_career_id:  # 不为空
            career_result = await db.execute(
                select(Career).where(
                    Career.id == main_career_id,
                    Career.project_id == character.project_id,
                    Career.type == 'main'
                )
            )
            career = career_result.scalar_one_or_none()
            
            if not career:
                raise HTTPException(status_code=400, detail="主职业不存在或类型错误")
            
            # 验证阶段有效性
            if main_career_stage and main_career_stage > career.max_stage:
                raise HTTPException(status_code=400, detail=f"阶段超出范围，该职业最大阶段为{career.max_stage}")
            
            # 更新或创建CharacterCareer关联
            char_career_result = await db.execute(
                select(CharacterCareer).where(
                    CharacterCareer.character_id == character_id,
                    CharacterCareer.career_type == 'main'
                )
            )
            char_career = char_career_result.scalar_one_or_none()
            
            if char_career:
                # 更新现有关联
                char_career.career_id = main_career_id
                if main_career_stage:
                    char_career.current_stage = main_career_stage
                logger.info(f"更新主职业关联：{character.name} -> {career.name}")
            else:
                # 创建新关联
                char_career = CharacterCareer(
                    character_id=character_id,
                    career_id=main_career_id,
                    career_type='main',
                    current_stage=main_career_stage or 1,
                    stage_progress=0
                )
                db.add(char_career)
                logger.info(f"创建主职业关联：{character.name} -> {career.name}")
            
            # 更新Character表的冗余字段
            character.main_career_id = main_career_id
            character.main_career_stage = main_career_stage or char_career.current_stage
        else:
            # 清空主职业
            char_career_result = await db.execute(
                select(CharacterCareer).where(
                    CharacterCareer.character_id == character_id,
                    CharacterCareer.career_type == 'main'
                )
            )
            char_career = char_career_result.scalar_one_or_none()
            if char_career:
                await db.delete(char_career)
                logger.info(f"移除主职业关联：{character.name}")
            
            character.main_career_id = None
            character.main_career_stage = None
    elif main_career_stage is not None and character.main_career_id:
        # 只更新阶段
        char_career_result = await db.execute(
            select(CharacterCareer).where(
                CharacterCareer.character_id == character_id,
                CharacterCareer.career_type == 'main'
            )
        )
        char_career = char_career_result.scalar_one_or_none()
        if char_career:
            char_career.current_stage = main_career_stage
            character.main_career_stage = main_career_stage
            logger.info(f"更新主职业阶段：{character.name} -> 阶段{main_career_stage}")
    
    # 处理副职业更新
    if sub_careers_json is not None:
        # 解析副职业JSON
        try:
            sub_careers_data = json.loads(sub_careers_json) if isinstance(sub_careers_json, str) else sub_careers_json
        except Exception:
            sub_careers_data = []
        
        # 删除现有的所有副职业关联
        existing_subs = await db.execute(
            select(CharacterCareer).where(
                CharacterCareer.character_id == character_id,
                CharacterCareer.career_type == 'sub'
            )
        )
        for sub_career in existing_subs.scalars():
            await db.delete(sub_career)
        
        # 创建新的副职业关联
        for sub_data in sub_careers_data[:2]:  # 最多2个副职业
            career_id = sub_data.get('career_id')
            if not career_id:
                continue
                
            # 验证副职业存在
            career_result = await db.execute(
                select(Career).where(
                    Career.id == career_id,
                    Career.project_id == character.project_id,
                    Career.type == 'sub'
                )
            )
            career = career_result.scalar_one_or_none()
            
            if career:
                # 创建副职业关联
                char_career = CharacterCareer(
                    character_id=character_id,
                    career_id=career_id,
                    career_type='sub',
                    current_stage=sub_data.get('stage', 1),
                    stage_progress=0
                )
                db.add(char_career)
                logger.info(f"添加副职业关联：{character.name} -> {career.name}")
        
        # 更新Character表的sub_careers冗余字段
        character.sub_careers = sub_careers_json if isinstance(sub_careers_json, str) else json.dumps(sub_careers_data, ensure_ascii=False)
        logger.info(f"更新副职业信息：{character.name}")
    
    # 更新 Character 表字段（排除 relationships 和 organization_members，这些字段现在由结构化表驱动）
    update_data.pop('relationships', None)
    update_data.pop('organization_members', None)
    for field, value in update_data.items():
        setattr(character, field, value)
    
    # 如果是组织且有需要同步的字段，更新 Organization 表
    if character.is_organization and org_fields:
        org_result = await db.execute(
            select(Organization).where(Organization.character_id == character_id)
        )
        org = org_result.scalar_one_or_none()
        
        if org:
            for field, value in org_fields.items():
                setattr(org, field, value)
            logger.info(f"同步更新组织详情：{character.name}")
        else:
            # 如果 Organization 记录不存在，自动创建
            org = Organization(
                character_id=character_id,
                project_id=character.project_id,
                member_count=0,
                **org_fields
            )
            db.add(org)
            logger.info(f"自动创建组织详情：{character.name}")
    
    await db.commit()
    await db.refresh(character)
    
    logger.info(f"更新角色/组织成功：{character.name} (ID: {character_id})")
    
    # 构建响应，从关系表动态生成 relationships
    rel_summary = await _build_relationships_summary(character_id, character.project_id, db)
    response_data = {
        "id": character.id,
        "project_id": character.project_id,
        "name": character.name,
        "age": character.age,
        "gender": character.gender,
        "is_organization": character.is_organization,
        "role_type": character.role_type,
        "personality": character.personality,
        "background": character.background,
        "appearance": character.appearance,
        "relationships": rel_summary,
        "organization_type": character.organization_type,
        "organization_purpose": character.organization_purpose,
        "organization_members": await _build_org_members_summary(character.id, db) if character.is_organization else "",
        "traits": character.traits,
        "avatar_url": character.avatar_url,
        "created_at": character.created_at,
        "updated_at": character.updated_at,
        "main_career_id": character.main_career_id,
        "main_career_stage": character.main_career_stage,
        "sub_careers": json.loads(character.sub_careers) if character.sub_careers else None,
        "power_level": None,
        "location": None,
        "motto": None,
        "color": None
    }
    
    # 如果是组织，添加组织额外字段
    if character.is_organization:
        org_result = await db.execute(
            select(Organization).where(Organization.character_id == character_id)
        )
        org = org_result.scalar_one_or_none()
        if org:
            response_data.update({
                "power_level": org.power_level,
                "location": org.location,
                "motto": org.motto,
                "color": org.color
            })
    
    return response_data


@router.delete("/{character_id}", summary="删除角色")
async def delete_character(
    character_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """删除角色"""
    from app.models.career import CharacterCareer
    
    result = await db.execute(
        select(Character).where(Character.id == character_id)
    )
    character = result.scalar_one_or_none()
    
    if not character:
        raise HTTPException(status_code=404, detail="角色不存在")
    
    # 验证用户权限
    user_id = getattr(request.state, 'user_id', None)
    await verify_project_access(character.project_id, user_id, db)
    
    # 清理角色-职业关联关系
    career_relations_result = await db.execute(
        select(CharacterCareer).where(CharacterCareer.character_id == character_id)
    )
    career_relations = career_relations_result.scalars().all()
    
    for relation in career_relations:
        await db.delete(relation)
        logger.info(f"删除角色职业关联：character_id={character_id}, career_id={relation.career_id}, type={relation.career_type}")
    
    # 删除角色
    await db.delete(character)
    await db.commit()
    
    logger.info(f"删除角色成功：{character.name} (ID: {character_id}), 清理了 {len(career_relations)} 条职业关联")
    
    return {"message": "角色删除成功"}


@router.post("", response_model=CharacterResponse, summary="手动创建角色")
async def create_character(
    character_data: CharacterCreate,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """
    手动创建角色或组织
    
    - 可以创建普通角色（is_organization=False）
    - 也可以创建组织（is_organization=True）
    - 如果创建组织且提供了组织额外字段，会自动创建Organization详情记录
    - 支持设置主职业和副职业
    """
    from app.models.career import CharacterCareer, Career
    
    # 验证用户权限
    user_id = getattr(request.state, 'user_id', None)
    await verify_project_access(character_data.project_id, user_id, db)
    
    try:
        # 创建角色（不再写入 relationships 文本字段，关系统一由 character_relationships 表管理）
        character = Character(
            project_id=character_data.project_id,
            name=character_data.name,
            age=character_data.age,
            gender=character_data.gender,
            is_organization=character_data.is_organization,
            role_type=character_data.role_type or "supporting",
            personality=character_data.personality,
            background=character_data.background,
            appearance=character_data.appearance,
            organization_type=character_data.organization_type,
            organization_purpose=character_data.organization_purpose,
            traits=character_data.traits,
            avatar_url=character_data.avatar_url,
            main_career_id=character_data.main_career_id,
            main_career_stage=character_data.main_career_stage,
            sub_careers=character_data.sub_careers
        )
        db.add(character)
        await db.flush()  # 获取character.id
        
        logger.info(f"✅ 手动创建角色成功：{character.name} (ID: {character.id}, 是否组织: {character.is_organization})")
        
        # 处理主职业关联
        if character_data.main_career_id and not character.is_organization:
            # 验证职业存在
            career_result = await db.execute(
                select(Career).where(
                    Career.id == character_data.main_career_id,
                    Career.project_id == character_data.project_id,
                    Career.type == 'main'
                )
            )
            career = career_result.scalar_one_or_none()
            
            if career:
                # 创建主职业关联
                char_career = CharacterCareer(
                    character_id=character.id,
                    career_id=character_data.main_career_id,
                    career_type='main',
                    current_stage=character_data.main_career_stage or 1,
                    stage_progress=0
                )
                db.add(char_career)
                logger.info(f"✅ 创建主职业关联：{character.name} -> {career.name}")
            else:
                logger.warning(f"⚠️ 主职业ID不存在或类型错误: {character_data.main_career_id}")
        
        # 处理副职业关联
        if character_data.sub_careers and not character.is_organization:
            try:
                sub_careers_data = json.loads(character_data.sub_careers) if isinstance(character_data.sub_careers, str) else character_data.sub_careers
                
                for sub_data in sub_careers_data[:2]:  # 最多2个副职业
                    career_id = sub_data.get('career_id')
                    if not career_id:
                        continue
                    
                    # 验证副职业存在
                    career_result = await db.execute(
                        select(Career).where(
                            Career.id == career_id,
                            Career.project_id == character_data.project_id,
                            Career.type == 'sub'
                        )
                    )
                    career = career_result.scalar_one_or_none()
                    
                    if career:
                        # 创建副职业关联
                        char_career = CharacterCareer(
                            character_id=character.id,
                            career_id=career_id,
                            career_type='sub',
                            current_stage=sub_data.get('stage', 1),
                            stage_progress=0
                        )
                        db.add(char_career)
                        logger.info(f"✅ 创建副职业关联：{character.name} -> {career.name}")
                    else:
                        logger.warning(f"⚠️ 副职业ID不存在或类型错误: {career_id}")
            except Exception as e:
                logger.warning(f"⚠️ 解析副职业数据失败: {e}")
        
        # 如果是组织，且提供了组织额外字段，自动创建Organization详情记录
        if character.is_organization and (
            character_data.power_level is not None or
            character_data.location or
            character_data.motto or
            character_data.color
        ):
            organization = Organization(
                character_id=character.id,
                project_id=character_data.project_id,
                member_count=0,
                power_level=character_data.power_level or 50,
                location=character_data.location,
                motto=character_data.motto,
                color=character_data.color
            )
            db.add(organization)
            await db.flush()
            logger.info(f"✅ 自动创建组织详情：{character.name} (Org ID: {organization.id})")
        
        await db.commit()
        await db.refresh(character)
        
        logger.info(f"🎉 成功手动创建角色/组织: {character.name}")
        
        # 构建响应（relationships 从关系表动态生成）
        char_dict = {
            "id": character.id,
            "project_id": character.project_id,
            "name": character.name,
            "age": character.age,
            "gender": character.gender,
            "is_organization": character.is_organization,
            "role_type": character.role_type,
            "personality": character.personality,
            "background": character.background,
            "appearance": character.appearance,
            "relationships": "",
            "organization_type": character.organization_type,
            "organization_purpose": character.organization_purpose,
            "organization_members": await _build_org_members_summary(character.id, db) if character.is_organization else "",
            "traits": character.traits,
            "avatar_url": character.avatar_url,
            "created_at": character.created_at,
            "updated_at": character.updated_at,
            "power_level": None,
            "location": None,
            "motto": None,
            "color": None,
            "main_career_id": character.main_career_id,
            "main_career_stage": character.main_career_stage,
            "sub_careers": json.loads(character.sub_careers) if character.sub_careers else None
        }
        
        if character.is_organization:
            org_result = await db.execute(
                select(Organization).where(Organization.character_id == character.id)
            )
            org = org_result.scalar_one_or_none()
            if org:
                char_dict.update({
                    "power_level": org.power_level,
                    "location": org.location,
                    "motto": org.motto,
                    "color": org.color
                })
        
        return char_dict
        
    except Exception as e:
        logger.error(f"手动创建角色失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"创建角色失败: {str(e)}")


@router.post("/batch-regenerate-stream", summary="AI批量修正已有角色/组织（流式）")
async def batch_regenerate_characters_stream(
    request: CharacterBatchRegenerateRequest,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
    user_ai_service: AIService = Depends(get_user_ai_service)
):
    """使用AI批量修正已有角色/组织，只更新现有记录，不新建也不删除。"""
    async def generate() -> AsyncGenerator[str, None]:
        from app.models.career import CharacterCareer, Career

        tracker = WizardProgressTracker("角色修正")
        db_committed = False

        def to_json_text(value):
            return json.dumps(value, ensure_ascii=False, indent=2)

        def parse_jsonish(value):
            if value is None:
                return None
            if isinstance(value, (list, dict)):
                return value
            if isinstance(value, str):
                try:
                    return loads_json(value)
                except Exception:
                    return value
            return value

        def as_clean_text(value):
            if value is None:
                return None
            if isinstance(value, (list, dict)):
                return json.dumps(value, ensure_ascii=False)
            return str(value).strip()

        def as_stage(value, default=1, maximum=999):
            try:
                stage = int(value)
            except Exception:
                stage = default
            return max(1, min(stage, maximum or 999))

        def normalize_career_name(value):
            if value is None:
                return ""
            return str(value).strip()

        try:
            user_id = getattr(http_request.state, 'user_id', None)

            yield await tracker.start("开始AI批量修正角色/组织...")
            yield await tracker.loading("验证项目权限...", 0.2)
            project = await verify_project_access(request.project_id, user_id, db)

            requested_ids = list(dict.fromkeys(request.character_ids))
            selected_result = await db.execute(
                select(Character).where(
                    Character.project_id == request.project_id,
                    Character.id.in_(requested_ids)
                )
            )
            selected_characters = selected_result.scalars().all()
            characters_by_id = {char.id: char for char in selected_characters}
            missing_ids = [char_id for char_id in requested_ids if char_id not in characters_by_id]
            if missing_ids:
                yield await tracker.error(f"部分角色不存在或不属于当前项目：{', '.join(missing_ids[:5])}", 404)
                return

            if not selected_characters:
                yield await tracker.error("没有可修正的角色/组织", 400)
                return

            yield await tracker.loading("加载项目上下文...", 0.6)
            all_chars_result = await db.execute(
                select(Character)
                .where(Character.project_id == request.project_id)
                .order_by(Character.is_organization.desc(), Character.created_at)
            )
            all_characters = all_chars_result.scalars().all()

            org_result = await db.execute(
                select(Organization).where(
                    Organization.character_id.in_([char.id for char in selected_characters if char.is_organization])
                )
            )
            org_by_character_id = {org.character_id: org for org in org_result.scalars().all()}

            careers_result = await db.execute(
                select(Career)
                .where(Career.project_id == request.project_id)
                .order_by(Career.type, Career.name)
            )
            careers = careers_result.scalars().all()
            career_by_name = {
                (career.type, normalize_career_name(career.name)): career
                for career in careers
            }

            selected_payload = []
            for char in selected_characters:
                org = org_by_character_id.get(char.id)
                selected_payload.append({
                    "id": char.id,
                    "name": char.name,
                    "is_organization": char.is_organization,
                    "role_type": char.role_type,
                    "age": char.age,
                    "gender": char.gender,
                    "personality": char.personality,
                    "appearance": char.appearance,
                    "background": char.background,
                    "relationships": await _build_relationships_summary(char.id, char.project_id, db),
                    "organization_type": char.organization_type,
                    "organization_purpose": char.organization_purpose,
                    "organization_members": await _build_org_members_summary(char.id, db) if char.is_organization else "",
                    "traits": parse_jsonish(char.traits),
                    "main_career_id": char.main_career_id,
                    "main_career_stage": char.main_career_stage,
                    "sub_careers": parse_jsonish(char.sub_careers) if char.sub_careers else [],
                    "power_level": org.power_level if org else None,
                    "location": org.location if org else None,
                    "motto": org.motto if org else None,
                    "color": org.color if org else None,
                })

            all_entities_context = [
                {
                    "id": char.id,
                    "name": char.name,
                    "type": "organization" if char.is_organization else "character",
                    "role_type": char.role_type,
                    "organization_type": char.organization_type,
                }
                for char in all_characters
            ]
            careers_context = [
                {
                    "name": career.name,
                    "type": career.type,
                    "max_stage": career.max_stage,
                    "description": career.description,
                }
                for career in careers
            ]

            story_context = await build_project_story_context(db, request.project_id)

            yield await tracker.preparing("构建AI修正提示词...")
            prompt = f"""
你是小说设定修正助手。请根据用户要求，批量修正已有角色/组织设定。

【硬性规则】
1. 只能修正下面 selected_entities 中已有的记录，禁止新增、删除或合并记录。
2. 每条更新必须保留原始 id，is_organization 必须与原记录一致。
3. 如果某个字段不需要修改，可以省略；如果返回字段，系统会写回数据库。
4. 角色与组织必须符合世界观；明显错误、冲突、穿帮、AI幻觉信息要智能修正。
5. 关系字段仅作为参考，本接口不直接改结构化关系表；不要输出 relationships 更新。
6. 职业只能使用 available_careers 中存在的名称。没有合适职业时省略 career_info。
7. 只输出合法 JSON，不要 Markdown，不要解释。

【项目世界观】
- 书名：{project.title}
- 主题：{project.theme or '未设定'}
- 类型：{project.genre or '未设定'}
- 时间背景：{project.world_time_period or '未设定'}
- 地理位置：{project.world_location or '未设定'}
- 氛围基调：{project.world_atmosphere or '未设定'}
- 世界规则：{project.world_rules or '未设定'}

【故事上下文】
{story_context}

【用户修正要求】
{request.requirements.strip()}

【项目全部实体索引】
{to_json_text(all_entities_context)}

【可用职业 available_careers】
{to_json_text(careers_context)}

【待修正实体 selected_entities】
{to_json_text(selected_payload)}

【输出格式】
{{
  "updates": [
    {{
      "id": "必须是 selected_entities 中的原始id",
      "name": "修正后的名称，可省略",
      "age": "角色年龄，可省略",
      "gender": "角色性别，可省略",
      "role_type": "protagonist/supporting/antagonist，可省略",
      "personality": "性格或组织特性，可省略",
      "appearance": "外貌或组织形象，可省略",
      "background": "背景故事，可省略",
      "traits": ["标签1", "标签2"],
      "organization_type": "组织类型，仅组织可用",
      "organization_purpose": "组织目的，仅组织可用",
      "power_level": 50,
      "location": "组织所在地，仅组织可用",
      "motto": "组织口号，仅组织可用",
      "color": "组织代表颜色，仅组织可用",
      "career_info": {{
        "main_career_name": "available_careers 中的主职业名称",
        "main_career_stage": 1,
        "sub_careers": [
          {{"career_name": "available_careers 中的副职业名称", "stage": 1}}
        ]
      }}
    }}
  ]
}}
"""

            if user_id:
                user_ai_service.user_id = user_id
                user_ai_service.db_session = db

            yield await tracker.generating(0, max(4000, len(prompt) * 2), "调用AI服务修正角色/组织...")
            ai_response = ""
            chunk_count = 0
            estimated_total = max(4000, len(prompt) * 2)

            async for chunk in wrap_stream_with_heartbeat(
                user_ai_service.generate_text_stream(
                    prompt=prompt,
                    provider=request.provider,
                    model=request.model,
                    tool_choice="auto" if request.enable_mcp else None,
                    auto_mcp=request.enable_mcp,
                ),
                heartbeat_interval=15.0
            ):
                if chunk is HEARTBEAT:
                    yield await tracker.heartbeat()
                    continue

                content = chunk.get("content", "") if isinstance(chunk, dict) else chunk
                if not content:
                    continue

                ai_response += content
                yield await SSEResponse.send_chunk(content)
                chunk_count += 1
                if chunk_count % 8 == 0:
                    yield await tracker.generating(len(ai_response), estimated_total, "AI修正角色/组织中...")

            if not ai_response.strip():
                yield await tracker.error("AI服务返回空响应")
                return

            yield await tracker.parsing("解析AI修正结果...")
            try:
                cleaned_response = user_ai_service._clean_json_response(ai_response)
                parsed_response = loads_json(cleaned_response)
            except json.JSONDecodeError as e:
                logger.error(f"❌ 批量修正角色JSON解析失败: {e}")
                logger.error(f"   原始响应预览: {ai_response[:300]}")
                yield await tracker.error(f"AI返回的内容无法解析为JSON：{str(e)}")
                return

            updates = parsed_response.get("updates") if isinstance(parsed_response, dict) else parsed_response
            if not isinstance(updates, list):
                yield await tracker.error("AI返回格式错误：updates 必须是数组")
                return

            characters_by_name = {char.name: char for char in selected_characters}

            async def sync_main_career(character: Character, career_info: dict):
                main_name = career_info.get("main_career_name", career_info.get("main_career"))
                if "main_career_name" not in career_info and "main_career" not in career_info:
                    return

                main_rel_result = await db.execute(
                    select(CharacterCareer).where(
                        CharacterCareer.character_id == character.id,
                        CharacterCareer.career_type == "main"
                    )
                )
                main_rel = main_rel_result.scalar_one_or_none()

                normalized = normalize_career_name(main_name)
                if not normalized or normalized in {"无", "none", "null", "None"}:
                    if main_rel:
                        await db.delete(main_rel)
                    character.main_career_id = None
                    character.main_career_stage = None
                    return

                career = career_by_name.get(("main", normalized))
                if not career:
                    logger.warning(f"AI修正返回的主职业不存在，已忽略: {normalized}")
                    return

                stage = as_stage(career_info.get("main_career_stage", career_info.get("main_stage", 1)), 1, career.max_stage)
                if main_rel:
                    main_rel.career_id = career.id
                    main_rel.current_stage = stage
                else:
                    db.add(CharacterCareer(
                        character_id=character.id,
                        career_id=career.id,
                        career_type="main",
                        current_stage=stage,
                        stage_progress=0
                    ))
                character.main_career_id = career.id
                character.main_career_stage = stage

            async def sync_sub_careers(character: Character, career_info: dict):
                if "sub_careers" not in career_info:
                    return

                existing_subs = await db.execute(
                    select(CharacterCareer).where(
                        CharacterCareer.character_id == character.id,
                        CharacterCareer.career_type == "sub"
                    )
                )
                for sub_rel in existing_subs.scalars():
                    await db.delete(sub_rel)

                sub_career_list = []
                raw_subs = career_info.get("sub_careers") or []
                if not isinstance(raw_subs, list):
                    raw_subs = []

                for sub_data in raw_subs[:2]:
                    if isinstance(sub_data, str):
                        sub_name = sub_data
                        sub_stage = 1
                    elif isinstance(sub_data, dict):
                        sub_name = sub_data.get("career_name", sub_data.get("career"))
                        sub_stage = sub_data.get("stage", 1)
                    else:
                        continue

                    normalized = normalize_career_name(sub_name)
                    if not normalized:
                        continue
                    career = career_by_name.get(("sub", normalized))
                    if not career:
                        logger.warning(f"AI修正返回的副职业不存在，已忽略: {normalized}")
                        continue

                    stage = as_stage(sub_stage, 1, career.max_stage)
                    db.add(CharacterCareer(
                        character_id=character.id,
                        career_id=career.id,
                        career_type="sub",
                        current_stage=stage,
                        stage_progress=0
                    ))
                    sub_career_list.append({"career_id": career.id, "stage": stage})

                character.sub_careers = json.dumps(sub_career_list, ensure_ascii=False) if sub_career_list else None

            yield await tracker.saving("写入修正结果...", 0.3)
            applied_ids = []
            ignored_updates = 0
            text_fields = [
                "name", "age", "gender", "role_type", "personality",
                "background", "appearance", "organization_type", "organization_purpose"
            ]
            org_fields = ["power_level", "location", "motto", "color"]

            for update_item in updates:
                if not isinstance(update_item, dict):
                    ignored_updates += 1
                    continue

                char_id = update_item.get("id") or update_item.get("character_id")
                character = characters_by_id.get(char_id)
                if not character:
                    original_name = update_item.get("original_name") or update_item.get("old_name") or update_item.get("name")
                    character = characters_by_name.get(original_name)

                if not character:
                    ignored_updates += 1
                    continue

                for field in text_fields:
                    if field not in update_item:
                        continue
                    if field.startswith("organization_") and not character.is_organization:
                        continue
                    if field == "role_type" and character.is_organization:
                        continue
                    setattr(character, field, as_clean_text(update_item.get(field)))

                if "traits" in update_item:
                    traits_value = update_item.get("traits")
                    if traits_value is None:
                        character.traits = None
                    elif isinstance(traits_value, (list, dict)):
                        character.traits = json.dumps(traits_value, ensure_ascii=False)
                    else:
                        character.traits = as_clean_text(traits_value)

                if character.is_organization:
                    org = org_by_character_id.get(character.id)
                    if not org:
                        org = Organization(
                            character_id=character.id,
                            project_id=character.project_id,
                            member_count=0
                        )
                        db.add(org)
                        await db.flush()
                        org_by_character_id[character.id] = org

                    for field in org_fields:
                        if field not in update_item:
                            continue
                        value = update_item.get(field)
                        if field == "power_level" and value is not None:
                            try:
                                value = max(0, min(int(value), 100))
                            except Exception:
                                value = org.power_level
                        setattr(org, field, as_clean_text(value) if field != "power_level" else value)
                else:
                    career_info = update_item.get("career_info") or update_item.get("career_assignment")
                    if isinstance(career_info, dict):
                        await sync_main_career(character, career_info)
                        await sync_sub_careers(character, career_info)

                applied_ids.append(character.id)

            if not applied_ids:
                yield await tracker.error("AI没有返回任何可应用的已有角色/组织更新")
                return

            history = GenerationHistory(
                project_id=request.project_id,
                prompt=prompt,
                generated_content=ai_response,
                model=user_ai_service.default_model
            )
            db.add(history)

            await db.commit()
            db_committed = True

            unique_applied_ids = list(dict.fromkeys(applied_ids))
            yield await tracker.complete(f"已修正{len(unique_applied_ids)}个角色/组织")
            yield await tracker.result({
                "updated_count": len(unique_applied_ids),
                "updated_ids": unique_applied_ids,
                "ignored_updates": ignored_updates,
            })
            yield await tracker.done()

            logger.info(f"✅ AI批量修正完成: project={request.project_id}, updated={len(unique_applied_ids)}")

        except HTTPException as he:
            logger.error(f"批量修正角色HTTP异常: {he.detail}")
            yield await tracker.error(str(he.detail), he.status_code)
        except GeneratorExit:
            logger.warning("角色批量修正生成器被提前关闭")
            if not db_committed and db.in_transaction():
                await db.rollback()
        except Exception as e:
            logger.error(f"批量修正角色失败: {str(e)}")
            if not db_committed and db.in_transaction():
                await db.rollback()
            yield await tracker.error(f"批量修正失败: {str(e)}")

    return create_sse_response(generate())


@router.post("/generate-stream", summary="AI生成角色（流式）")
async def generate_character_stream(
    request: CharacterGenerateRequest,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
    user_ai_service: AIService = Depends(get_user_ai_service)
):
    """
    使用AI生成角色卡（支持SSE流式进度显示）
    
    通过Server-Sent Events返回实时进度信息
    """
    async def generate() -> AsyncGenerator[str, None]:
        tracker = WizardProgressTracker("角色")
        try:
            # 验证用户权限和项目是否存在
            user_id = getattr(http_request.state, 'user_id', None)
            project = await verify_project_access(request.project_id, user_id, db)
            
            yield await tracker.start()
            
            # 获取已存在的角色列表
            yield await tracker.loading("获取项目上下文...", 0.3)
            
            existing_chars_result = await db.execute(
                select(Character)
                .where(Character.project_id == request.project_id)
                .order_by(Character.created_at.desc())
            )
            existing_characters = existing_chars_result.scalars().all()
            
            # 构建现有角色信息摘要
            existing_chars_info = ""
            character_list = []
            organization_list = []
            
            if existing_characters:
                for c in existing_characters[:10]:
                    if c.is_organization:
                        organization_list.append(f"- {c.name} [{c.organization_type or '组织'}]")
                    else:
                        character_list.append(f"- {c.name}（{c.role_type or '未知'}）")
                
                if character_list:
                    existing_chars_info += "\n已有角色：\n" + "\n".join(character_list)
                if organization_list:
                    existing_chars_info += "\n\n已有组织：\n" + "\n".join(organization_list)
            
            # 🎯 获取项目职业列表
            from app.models.career import Career
            careers_result = await db.execute(
                select(Career)
                .where(Career.project_id == request.project_id)
                .order_by(Career.type, Career.name)
            )
            careers = careers_result.scalars().all()
            
            # 构建职业信息摘要
            careers_info = ""
            if careers:
                main_careers = [c for c in careers if c.type == 'main']
                sub_careers = [c for c in careers if c.type == 'sub']
                
                if main_careers:
                    careers_info += "\n\n可用主职业列表（请在career_info中填写职业名称，系统会自动匹配ID）：\n"
                    for career in main_careers:
                        # 解析阶段信息
                        import json as json_lib
                        try:
                            stages = json_lib.loads(career.stages) if career.stages else []
                            stage_names = [s.get('name', f'阶段{s.get("level")}') for s in stages[:3]]  # 只显示前3个阶段
                            stage_info = " → ".join(stage_names)
                            if len(stages) > 3:
                                stage_info += " → ..."
                        except Exception:
                            stage_info = f"共{career.max_stage}个阶段"
                        
                        careers_info += f"- 名称: {career.name}"
                        if career.description:
                            careers_info += f", 描述: {career.description[:50]}"
                        careers_info += f", 阶段: {stage_info}\n"
                
                if sub_careers:
                    careers_info += "\n可用副职业列表（请在career_info中填写职业名称，系统会自动匹配ID）：\n"
                    for career in sub_careers[:5]:  # 最多显示5个副职业
                        careers_info += f"- 名称: {career.name}"
                        if career.description:
                            careers_info += f", 描述: {career.description[:50]}"
                        careers_info += "\n"
            else:
                careers_info = "\n\n⚠️ 项目中暂无职业设定"
            
            # 构建项目上下文
            project_context = f"""
项目信息：
- 书名：{project.title}
- 主题：{project.theme or '未设定'}
- 类型：{project.genre or '未设定'}
- 时间背景：{project.world_time_period or '未设定'}
- 地理位置：{project.world_location or '未设定'}
- 氛围基调：{project.world_atmosphere or '未设定'}
- 世界规则：{project.world_rules or '未设定'}
{existing_chars_info}
{careers_info}
"""
            
            user_input = f"""
用户要求：
- 角色名称：{request.name or '请AI生成'}
- 角色定位：{request.role_type or 'supporting'}
- 背景设定：{request.background or '无特殊要求'}
- 其他要求：{request.requirements or '无'}
"""
            
            yield await tracker.loading("项目上下文准备完成", 0.7)
            yield await tracker.preparing("构建AI提示词...")
            
            # 获取自定义提示词模板
            template = await PromptService.get_template("SINGLE_CHARACTER_GENERATION", user_id, db)
            # 格式化提示词
            prompt = PromptService.format_prompt(
                template,
                project_context=project_context,
                user_input=user_input
            )
            
            yield await tracker.generating(0, max(3000, len(prompt) * 8), "调用AI服务生成角色...")
            logger.info(f"🎯 开始为项目 {request.project_id} 生成角色（SSE流式）")
            
            try:
                # 直接使用 AIService 流式生成
                ai_response = ""
                chunk_count = 0
                estimated_total = max(3000, len(prompt) * 8)
                
                logger.info(f"🎯 开始生成角色（流式模式）...")
                yield await tracker.generating(0, estimated_total, "开始生成角色...")
                
                async for chunk in wrap_stream_with_heartbeat(
                    user_ai_service.generate_text_stream(
                        prompt=prompt,
                        tool_choice="auto" if request.enable_mcp else None,
                        auto_mcp=request.enable_mcp,
                    ),
                    heartbeat_interval=15.0
                ):
                    # 心跳哨兵：发送心跳保活，不混入AI响应
                    if chunk is HEARTBEAT:
                        yield await tracker.heartbeat()
                        continue

                    # chunk 现在可能是 dict 或 str，提取 content 字段
                    if isinstance(chunk, dict):
                        content = chunk.get("content", "")
                    else:
                        content = chunk
                    
                    if content:
                        ai_response += content
                        
                        # 发送内容块
                        yield await SSEResponse.send_chunk(content)
                        
                        # 定期更新进度（每收到约500字符更新一次，避免过于频繁）
                        current_len = len(ai_response)
                        if current_len >= chunk_count * 500:
                            chunk_count += 1
                            yield await tracker.generating(current_len, estimated_total)
                        
                        # 心跳
                        if chunk_count % 20 == 0:
                            yield await tracker.heartbeat()
                        
            except Exception as ai_error:
                logger.error(f"❌ AI服务调用异常：{str(ai_error)}")
                yield await tracker.error(f"AI服务调用失败：{str(ai_error)}")
                return
            
            if not ai_response or not ai_response.strip():
                yield await tracker.error("AI服务返回空响应")
                return
            
            yield await tracker.parsing("解析AI响应...", 0.5)
            
            # ✅ 使用统一的 JSON 清洗方法
            try:
                cleaned_response = user_ai_service._clean_json_response(ai_response)
                character_data = loads_json(cleaned_response)
                logger.info(f"✅ 角色JSON解析成功")
            except json.JSONDecodeError as e:
                logger.error(f"❌ 角色JSON解析失败: {e}")
                logger.error(f"   原始响应预览: {ai_response[:200]}")
                yield await tracker.error(f"AI返回的内容无法解析为JSON：{str(e)}")
                return
            
            yield await tracker.saving("创建角色记录...", 0.3)
            
            # 转换traits
            traits_json = json.dumps(character_data.get("traits", []), ensure_ascii=False) if character_data.get("traits") else None
            is_organization = character_data.get("is_organization", False)
            
            # 提取职业信息（支持通过名称匹配）
            career_info = character_data.get("career_info", {})
            raw_main_career_name = career_info.get("main_career_name") if career_info else None
            main_career_stage = career_info.get("main_career_stage", 1) if career_info else None
            raw_sub_careers_data = career_info.get("sub_careers", []) if career_info else []
            
            # 调试日志：输出职业信息
            logger.info(f"🔍 提取职业信息 - career_info: {career_info}")
            logger.info(f"🔍 raw_main_career_name: {raw_main_career_name}, main_career_stage: {main_career_stage}")
            logger.info(f"🔍 raw_sub_careers_data类型: {type(raw_sub_careers_data)}, 内容: {raw_sub_careers_data}")
            
            # 🔧 通过职业名称匹配数据库中的职业ID
            from app.models.career import Career
            main_career_id = None
            sub_careers_data = []
            
            # 匹配主职业名称
            if raw_main_career_name and not is_organization:
                career_check = await db.execute(
                    select(Career).where(
                        Career.name == raw_main_career_name,
                        Career.project_id == request.project_id,
                        Career.type == 'main'
                    )
                )
                matched_career = career_check.scalar_one_or_none()
                if matched_career:
                    main_career_id = matched_career.id
                    logger.info(f"✅ 主职业名称匹配成功: {raw_main_career_name} -> ID: {main_career_id}")
                else:
                    logger.warning(f"⚠️ AI返回的主职业名称未找到: {raw_main_career_name}")
            
            # 匹配副职业名称
            if raw_sub_careers_data and not is_organization and isinstance(raw_sub_careers_data, list):
                for sub_data in raw_sub_careers_data[:2]:
                    if isinstance(sub_data, dict):
                        career_name = sub_data.get('career_name')
                        if career_name:
                            career_check = await db.execute(
                                select(Career).where(
                                    Career.name == career_name,
                                    Career.project_id == request.project_id,
                                    Career.type == 'sub'
                                )
                            )
                            matched_career = career_check.scalar_one_or_none()
                            if matched_career:
                                # 转换为包含ID的格式
                                sub_careers_data.append({
                                    'career_id': matched_career.id,
                                    'stage': sub_data.get('stage', 1)
                                })
                                logger.info(f"✅ 副职业名称匹配成功: {career_name} -> ID: {matched_career.id}")
                            else:
                                logger.warning(f"⚠️ AI返回的副职业名称未找到: {career_name}")
            
            # 创建角色（不再写入 relationships 文本字段，关系统一由 character_relationships 表管理）
            character = Character(
                project_id=request.project_id,
                name=character_data.get("name", request.name or "未命名角色"),
                age=str(character_data.get("age", "")),
                gender=character_data.get("gender"),
                is_organization=is_organization,
                role_type=request.role_type or "supporting",
                personality=character_data.get("personality", ""),
                background=character_data.get("background", ""),
                appearance=character_data.get("appearance", ""),
                organization_type=character_data.get("organization_type") if is_organization else None,
                organization_purpose=character_data.get("organization_purpose") if is_organization else None,
                traits=traits_json,
                main_career_id=main_career_id,
                main_career_stage=main_career_stage if main_career_id else None,
                sub_careers=json.dumps(sub_careers_data, ensure_ascii=False) if sub_careers_data else None
            )
            db.add(character)
            await db.flush()
            
            logger.info(f"✅ 角色创建成功：{character.name} (ID: {character.id})")
            
            # 处理主职业关联
            if main_career_id and not is_organization:
                from app.models.career import CharacterCareer, Career
                
                career_result = await db.execute(
                    select(Career).where(
                        Career.id == main_career_id,
                        Career.project_id == request.project_id,
                        Career.type == 'main'
                    )
                )
                career = career_result.scalar_one_or_none()
                
                if career:
                    char_career = CharacterCareer(
                        character_id=character.id,
                        career_id=main_career_id,
                        career_type='main',
                        current_stage=main_career_stage,
                        stage_progress=0
                    )
                    db.add(char_career)
                    logger.info(f"✅ AI生成角色-创建主职业关联：{character.name} -> {career.name}")
                else:
                    logger.warning(f"⚠️ AI返回的主职业ID不存在: {main_career_id}")
            
            # 处理副职业关联
            if sub_careers_data and not is_organization:
                from app.models.career import CharacterCareer, Career
                
                logger.info(f"🔍 开始处理副职业关联，数据: {sub_careers_data}")
                
                # 确保sub_careers_data是列表
                if not isinstance(sub_careers_data, list):
                    logger.warning(f"⚠️ sub_careers_data不是列表类型: {type(sub_careers_data)}")
                    sub_careers_data = []
                
                for idx, sub_data in enumerate(sub_careers_data[:2]):  # 最多2个副职业
                    logger.info(f"🔍 处理第{idx+1}个副职业，数据: {sub_data}, 类型: {type(sub_data)}")
                    
                    # 兼容不同的数据格式
                    if isinstance(sub_data, dict):
                        career_id = sub_data.get('career_id')
                        stage = sub_data.get('stage', 1)
                    else:
                        logger.warning(f"⚠️ 副职业数据格式错误，应为dict: {sub_data}")
                        continue
                    
                    if not career_id:
                        logger.warning(f"⚠️ 副职业数据缺少career_id字段")
                        continue
                    
                    logger.info(f"🔍 查询副职业: career_id={career_id}, project_id={request.project_id}")
                    
                    career_result = await db.execute(
                        select(Career).where(
                            Career.id == career_id,
                            Career.project_id == request.project_id,
                            Career.type == 'sub'
                        )
                    )
                    career = career_result.scalar_one_or_none()
                    
                    if career:
                        char_career = CharacterCareer(
                            character_id=character.id,
                            career_id=career_id,
                            career_type='sub',
                            current_stage=stage,
                            stage_progress=0
                        )
                        db.add(char_career)
                        logger.info(f"✅ AI生成角色-创建副职业关联：{character.name} -> {career.name} (阶段{stage})")
                    else:
                        logger.warning(f"⚠️ AI返回的副职业ID不存在: {career_id} (项目ID: {request.project_id})")
            
            # 如果是组织，创建Organization详情
            if is_organization:
                yield await tracker.saving("创建组织详情...", 0.6)
                
                org_check = await db.execute(
                    select(Organization).where(Organization.character_id == character.id)
                )
                existing_org = org_check.scalar_one_or_none()
                
                if not existing_org:
                    organization = Organization(
                        character_id=character.id,
                        project_id=request.project_id,
                        member_count=0,
                        power_level=character_data.get("power_level", 50),
                        location=character_data.get("location"),
                        motto=character_data.get("motto"),
                        color=character_data.get("color")
                    )
                    db.add(organization)
                    await db.flush()
            
            project_characters_result = await db.execute(
                select(Character).where(Character.project_id == request.project_id)
            )
            project_characters = project_characters_result.scalars().all()
            name_authority = build_name_authority(project_characters)
            character_by_name = {
                canonical_name: item
                for item in project_characters
                if not item.is_organization
                for canonical_name in [name_authority.resolve_name(item.name, keep_unknown=False)]
                if canonical_name
            }
            organization_char_by_name = {
                canonical_name: item
                for item in project_characters
                if item.is_organization
                for canonical_name in [name_authority.resolve_name(item.name, keep_unknown=False)]
                if canonical_name
            }

            # 处理结构化关系数据（仅针对非组织角色）
            if not is_organization:
                relationships_data = character_data.get("relationships", [])
                if relationships_data and isinstance(relationships_data, list):
                    logger.info(f"📊 开始处理 {len(relationships_data)} 条关系数据")
                    created_rels = 0
                    
                    for rel in relationships_data:
                        try:
                            target_name = rel.get("target_character_name")
                            if not target_name:
                                logger.debug(f"  ⚠️  关系缺少target_character_name，跳过")
                                continue

                            canonical_target_name = name_authority.resolve_name(target_name, keep_unknown=False)
                            if not canonical_target_name:
                                logger.debug(f"  ⚠️  关系目标不是稳定角色名，跳过：{target_name}")
                                continue

                            target_char = character_by_name.get(canonical_target_name)
                            
                            if target_char:
                                if target_char.id == character.id:
                                    logger.debug(f"  ℹ️  跳过自指关系：{character.name} -> {canonical_target_name}")
                                    continue
                                # 检查是否已存在相同关系
                                existing_rel = await db.execute(
                                    select(CharacterRelationship).where(
                                        CharacterRelationship.project_id == request.project_id,
                                        CharacterRelationship.character_from_id == character.id,
                                        CharacterRelationship.character_to_id == target_char.id
                                    )
                                )
                                if existing_rel.scalar_one_or_none():
                                    logger.debug(f"  ℹ️  关系已存在：{character.name} -> {canonical_target_name}")
                                    continue
                                
                                relationship = CharacterRelationship(
                                    project_id=request.project_id,
                                    character_from_id=character.id,
                                    character_to_id=target_char.id,
                                    relationship_name=rel.get("relationship_type", "未知关系"),
                                    intimacy_level=rel.get("intimacy_level", 50),
                                    description=rel.get("description", ""),
                                    started_at=rel.get("started_at"),
                                    source="ai"
                                )
                                
                                # 匹配预定义关系类型
                                rel_type_result = await db.execute(
                                    select(RelationshipType).where(
                                        RelationshipType.name == rel.get("relationship_type")
                                    )
                                )
                                rel_type = rel_type_result.scalar_one_or_none()
                                if rel_type:
                                    relationship.relationship_type_id = rel_type.id
                                
                                db.add(relationship)
                                created_rels += 1
                                logger.info(f"  ✅ 创建关系：{character.name} -> {canonical_target_name} ({rel.get('relationship_type')})")
                            else:
                                logger.warning(f"  ⚠️  目标角色不存在：{target_name}")
                                
                        except Exception as rel_error:
                            logger.warning(f"  ❌ 创建关系失败：{str(rel_error)}")
                            continue
                    
                    logger.info(f"✅ 成功创建 {created_rels} 条关系记录")
            
            # 处理组织成员关系（仅针对非组织角色）
            if not is_organization:
                org_memberships = character_data.get("organization_memberships", [])
                if org_memberships and isinstance(org_memberships, list):
                    logger.info(f"🏢 开始处理 {len(org_memberships)} 条组织成员关系")
                    created_members = 0
                    
                    for membership in org_memberships:
                        try:
                            org_name = membership.get("organization_name")
                            if not org_name:
                                logger.debug(f"  ⚠️  组织成员关系缺少organization_name，跳过")
                                continue

                            canonical_org_name = name_authority.resolve_name(org_name, keep_unknown=False)
                            if not canonical_org_name:
                                logger.debug(f"  ⚠️  组织引用不是稳定组织名，跳过：{org_name}")
                                continue

                            org_char = organization_char_by_name.get(canonical_org_name)
                            
                            if org_char:
                                # 获取或创建Organization记录
                                org_result = await db.execute(
                                    select(Organization).where(Organization.character_id == org_char.id)
                                )
                                org = org_result.scalar_one_or_none()
                                
                                if not org:
                                    # 如果组织Character存在但Organization不存在，自动创建
                                    org = Organization(
                                        character_id=org_char.id,
                                        project_id=request.project_id,
                                        member_count=0
                                    )
                                    db.add(org)
                                    await db.flush()
                                    logger.info(f"  ℹ️  自动创建缺失的组织详情：{canonical_org_name}")
                                
                                # 检查是否已存在成员关系
                                existing_member = await db.execute(
                                    select(OrganizationMember).where(
                                        OrganizationMember.organization_id == org.id,
                                        OrganizationMember.character_id == character.id
                                    )
                                )
                                if existing_member.scalar_one_or_none():
                                    logger.debug(f"  ℹ️  成员关系已存在：{character.name} -> {canonical_org_name}")
                                    continue
                                
                                # 创建成员关系
                                member = OrganizationMember(
                                    organization_id=org.id,
                                    character_id=character.id,
                                    position=membership.get("position", "成员"),
                                    rank=membership.get("rank", 0),
                                    loyalty=membership.get("loyalty", 50),
                                    joined_at=membership.get("joined_at"),
                                    status=membership.get("status", "active"),
                                    source="ai"
                                )
                                db.add(member)
                                
                                # 更新组织成员计数
                                org.member_count += 1
                                
                                created_members += 1
                                logger.info(f"  ✅ 添加成员：{character.name} -> {canonical_org_name} ({membership.get('position')})")
                            else:
                                logger.warning(f"  ⚠️  组织不存在：{org_name}")
                                
                        except Exception as org_error:
                            logger.warning(f"  ❌ 添加组织成员失败：{str(org_error)}")
                            continue
                    
                    logger.info(f"✅ 成功创建 {created_members} 条组织成员记录")
            
            yield await tracker.saving("保存生成历史...", 0.9)
            
            # 记录生成历史
            history = GenerationHistory(
                project_id=request.project_id,
                prompt=prompt,
                generated_content=ai_response,
                model=user_ai_service.default_model
            )
            db.add(history)
            
            await db.commit()
            await db.refresh(character)
            
            logger.info(f"🎉 成功生成角色: {character.name}")
            
            yield await tracker.complete("角色生成完成！")
            
            # 发送结果数据
            yield await tracker.result({
                "character": {
                    "id": character.id,
                    "name": character.name,
                    "role_type": character.role_type,
                    "is_organization": character.is_organization
                }
            })
            
            yield await tracker.done()
            
        except HTTPException as he:
            logger.error(f"HTTP异常: {he.detail}")
            yield await tracker.error(he.detail, he.status_code)
        except Exception as e:
            logger.error(f"生成角色失败: {str(e)}")
            yield await tracker.error(f"生成角色失败: {str(e)}")
    
    return create_sse_response(generate())


@router.post("/analyze-from-text-stream", summary="从已有全文分析并编排角色卡（流式）")
async def analyze_characters_from_text_stream(
    request: CharacterAnalyzeFromTextRequest,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
    user_ai_service: AIService = Depends(get_user_ai_service)
):
    """
    从项目现有大纲和章节内容中识别角色，并创建/更新角色卡。

    这是角色管理页的全文分析入口，不替代章节分析中的状态/关系更新：
    - 章节分析负责随章节推进更新角色状态、关系、职业与伏笔；
    - 本接口负责从已有正文中发现角色并整理基础角色设定。
    """
    async def generate() -> AsyncGenerator[str, None]:
        tracker = WizardProgressTracker("全文角色分析")
        try:
            user_id = getattr(http_request.state, 'user_id', None)
            project = await verify_project_access(request.project_id, user_id, db)

            yield await tracker.start("开始分析全文角色...")
            yield await tracker.loading("加载已有角色与章节上下文...", 0.35)

            existing_result = await db.execute(
                select(Character)
                .where(Character.project_id == request.project_id)
                .order_by(Character.created_at.asc())
            )
            existing_entities = existing_result.scalars().all()
            existing_characters = [item for item in existing_entities if not item.is_organization]
            existing_by_name = {item.name.strip(): item for item in existing_characters if item.name}

            existing_info = "暂无已有角色卡"
            if existing_characters:
                lines = []
                for char in existing_characters[:80]:
                    lines.append(
                        f"- {char.name}（{char.role_type or '未定位'}）"
                        f" 性格:{_compact_character_text(char.personality, 120)}"
                        f" 背景:{_compact_character_text(char.background, 120)}"
                    )
                existing_info = "\n".join(lines)

            story_context = await build_project_story_context(
                db,
                request.project_id,
                max_chars=52000,
                outline_limit=160,
                chapter_limit=180,
                prefer_chapter_content=True,
                chapter_excerpt_chars=520,
            )

            if "暂无可用内容" in story_context and not existing_characters:
                yield await tracker.error("项目没有可分析的大纲或章节内容")
                return

            yield await tracker.preparing("构建角色分析提示词...")

            extra_requirements = (request.requirements or "").strip() or "无"
            project_context = "\n".join([
                f"- 书名：{project.title}",
                f"- 类型：{project.genre or '未设定'}",
                f"- 主题：{project.theme or '未设定'}",
                f"- 简介：{project.description or '未设定'}",
            ])
            template = await PromptService.get_template("CHARACTER_TEXT_ANALYSIS", user_id, db)
            prompt = PromptService.format_prompt(
                template,
                project_context=project_context,
                existing_info=existing_info,
                story_context=story_context,
                extra_requirements=extra_requirements,
                max_characters=request.max_characters,
            )

            yield await tracker.generating(0, max(6000, len(prompt) * 4), "调用AI分析全文角色...")
            ai_response = ""
            chunk_count = 0

            async for chunk in wrap_stream_with_heartbeat(
                user_ai_service.generate_text_stream(
                    prompt=prompt,
                    temperature=0.45,
                    max_tokens=24000,
                    auto_mcp=False,
                ),
                heartbeat_interval=15.0,
            ):
                if chunk is HEARTBEAT:
                    yield await tracker.heartbeat()
                    continue

                content = chunk.get("content", "") if isinstance(chunk, dict) else chunk
                if not content:
                    continue

                ai_response += content
                yield await SSEResponse.send_chunk(content)

                current_len = len(ai_response)
                if current_len >= chunk_count * 800:
                    chunk_count += 1
                    yield await tracker.generating(current_len, max(6000, len(prompt) * 4))

            if not ai_response.strip():
                yield await tracker.error("AI服务返回空响应")
                return

            yield await tracker.parsing("解析角色分析结果...", 0.55)
            try:
                cleaned_response = user_ai_service._clean_json_response(ai_response)
                parsed_data = loads_json(cleaned_response)
                character_items = _extract_character_items(parsed_data)[:request.max_characters]
            except Exception as parse_error:
                logger.error(f"❌ 全文角色分析JSON解析失败: {parse_error}")
                logger.error(f"   原始响应预览: {ai_response[:300]}")
                yield await tracker.error(f"AI返回的角色分析无法解析为JSON：{parse_error}")
                return

            if not character_items:
                yield await tracker.error("AI没有识别到可写入的角色")
                return

            yield await tracker.saving("写入角色卡...", 0.45)

            created: List[str] = []
            updated: List[str] = []
            skipped: List[str] = []

            for item in character_items:
                name = _compact_character_text(item.get("name"), 100)
                if not name:
                    continue

                # 明显是组织/地点的条目交给组织管理，不在角色卡入口混写。
                if item.get("is_organization") is True:
                    skipped.append(name)
                    continue

                existing = existing_by_name.get(name)
                if existing:
                    if _apply_character_analysis(
                        existing,
                        item,
                        overwrite_existing=request.overwrite_existing,
                    ):
                        updated.append(name)
                    else:
                        skipped.append(name)
                    continue

                character = Character(
                    project_id=request.project_id,
                    name=name,
                    age=_compact_character_text(item.get("age"), 50),
                    gender=_compact_character_text(item.get("gender"), 50),
                    is_organization=False,
                    role_type=_normalize_role_type(item.get("role_type")),
                    personality=_compact_character_text(item.get("personality"), 2000),
                    background=_compact_character_text(item.get("background"), 2000),
                    appearance=_compact_character_text(item.get("appearance"), 1200),
                    traits=_normalize_traits(item.get("traits")),
                )
                db.add(character)
                existing_by_name[name] = character
                created.append(name)

            history = GenerationHistory(
                project_id=request.project_id,
                prompt=prompt[:8000],
                generated_content=ai_response,
                model=user_ai_service.default_model,
            )
            db.add(history)
            await db.commit()

            yield await tracker.complete("全文角色分析完成")
            yield await tracker.result({
                "created_count": len(created),
                "updated_count": len(updated),
                "skipped_count": len(skipped),
                "created": created,
                "updated": updated,
                "skipped": skipped,
            })
            yield await tracker.done()

        except HTTPException as he:
            logger.error(f"全文角色分析HTTP异常: {he.detail}")
            yield await tracker.error(he.detail, he.status_code)
        except Exception as exc:
            logger.error(f"全文角色分析失败: {exc}", exc_info=True)
            yield await tracker.error(f"全文角色分析失败: {exc}")

    return create_sse_response(generate())


@router.post("/export", summary="批量导出角色/组织")
async def export_characters(
    export_request: CharactersExportRequest,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """
    批量导出角色/组织为JSON格式
    
    - 支持单个或多个角色/组织导出
    - 包含角色的所有信息（基础信息、职业、组织详情等）
    - 返回JSON文件供下载
    """
    user_id = getattr(request.state, 'user_id', None)
    if not user_id:
        raise HTTPException(status_code=401, detail="未登录")
    
    if not export_request.character_ids:
        raise HTTPException(status_code=400, detail="请至少选择一个角色/组织")
    
    try:
        # 验证所有角色的权限
        for char_id in export_request.character_ids:
            result = await db.execute(
                select(Character).where(Character.id == char_id)
            )
            character = result.scalar_one_or_none()
            
            if not character:
                raise HTTPException(status_code=404, detail=f"角色不存在: {char_id}")
            
            # 验证项目权限
            await verify_project_access(character.project_id, user_id, db)
        
        # 执行导出
        export_data = await ImportExportService.export_characters(
            character_ids=export_request.character_ids,
            db=db
        )
        
        # 生成文件名
        from datetime import datetime
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        count = len(export_request.character_ids)
        filename = f"characters_export_{count}_{timestamp}.json"
        
        logger.info(f"用户 {user_id} 导出了 {count} 个角色/组织")
        
        # 返回JSON文件
        return JSONResponse(
            content=export_data,
            headers={
                "Content-Disposition": f"attachment; filename={filename}",
                "Content-Type": "application/json; charset=utf-8"
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"导出角色/组织失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"导出失败: {str(e)}")


@router.post("/import", response_model=CharactersImportResult, summary="导入角色/组织")
async def import_characters(
    project_id: str,
    file: UploadFile = File(...),
    request: Request = None,
    db: AsyncSession = Depends(get_db)
):
    """
    从JSON文件导入角色/组织
    
    - 支持导入之前导出的角色/组织JSON文件
    - 自动处理重复名称（跳过）
    - 验证职业ID的有效性
    - 自动创建组织详情记录
    """
    user_id = getattr(request.state, 'user_id', None)
    if not user_id:
        raise HTTPException(status_code=401, detail="未登录")
    
    # 验证项目权限
    await verify_project_access(project_id, user_id, db)
    
    # 验证文件类型
    if not file.filename.endswith('.json'):
        raise HTTPException(status_code=400, detail="只支持JSON格式文件")
    
    try:
        # 读取文件内容
        content = await file.read()
        data = json.loads(content.decode('utf-8'))
        
        # 执行导入
        result = await ImportExportService.import_characters(
            data=data,
            project_id=project_id,
            user_id=user_id,
            db=db
        )
        
        logger.info(f"用户 {user_id} 导入角色/组织到项目 {project_id}: {result['message']}")
        
        return result
        
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f"JSON格式错误: {str(e)}")
    except Exception as e:
        logger.error(f"导入角色/组织失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"导入失败: {str(e)}")


@router.post("/validate-import", summary="验证导入文件")
async def validate_import(
    file: UploadFile = File(...),
    request: Request = None
):
    """
    验证角色/组织导入文件的格式和内容
    
    - 检查文件格式
    - 验证版本兼容性
    - 统计数据量
    - 返回验证结果和警告信息
    """
    user_id = getattr(request.state, 'user_id', None)
    if not user_id:
        raise HTTPException(status_code=401, detail="未登录")
    
    # 验证文件类型
    if not file.filename.endswith('.json'):
        raise HTTPException(status_code=400, detail="只支持JSON格式文件")
    
    try:
        # 读取文件内容
        content = await file.read()
        data = json.loads(content.decode('utf-8'))
        
        # 验证数据
        validation_result = ImportExportService.validate_characters_import(data)
        
        logger.info(f"用户 {user_id} 验证导入文件: {file.filename}")
        
        return validation_result
        
    except json.JSONDecodeError as e:
        return {
            "valid": False,
            "version": "",
            "statistics": {"characters": 0, "organizations": 0},
            "errors": [f"JSON格式错误: {str(e)}"],
            "warnings": []
        }
    except Exception as e:
        logger.error(f"验证导入文件失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"验证失败: {str(e)}")
