"""关系管理API"""
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_
from typing import List, Optional, AsyncGenerator
from pydantic import BaseModel, Field
import json

from app.database import get_db
from app.utils.sse_response import SSEResponse, create_sse_response, WizardProgressTracker, wrap_stream_with_heartbeat, HEARTBEAT
from app.models.relationship import (
    RelationshipType,
    CharacterRelationship,
    Organization,
    OrganizationMember
)
from app.models.character import Character
from app.models.generation_history import GenerationHistory
from app.schemas.relationship import (
    RelationshipTypeResponse,
    CharacterRelationshipCreate,
    CharacterRelationshipUpdate,
    CharacterRelationshipResponse,
    RelationshipGraphData,
    RelationshipGraphNode,
    RelationshipGraphLink
)
from app.logger import get_logger
from app.api.common import verify_project_access
from app.api.settings import get_user_ai_service
from app.services.ai_service import AIService
from app.services.json_helper import loads_json
from app.services.project_story_context import build_project_story_context

router = APIRouter(prefix="/relationships", tags=["关系管理"])
logger = get_logger(__name__)


class RelationshipGenerateRequest(BaseModel):
    """AI生成角色关系的请求模型"""
    project_id: str = Field(..., description="项目ID")
    relationship_count: int = Field(8, ge=1, le=50, description="生成关系数量")
    requirements: Optional[str] = Field(None, description="额外要求")


@router.get("/types", response_model=List[RelationshipTypeResponse], summary="获取关系类型列表")
async def get_relationship_types(db: AsyncSession = Depends(get_db)):
    """获取所有预定义的关系类型"""
    result = await db.execute(select(RelationshipType).order_by(RelationshipType.category, RelationshipType.id))
    types = result.scalars().all()
    return types


@router.get("/project/{project_id}", response_model=List[CharacterRelationshipResponse], summary="获取项目的所有关系")
async def get_project_relationships(
    project_id: str,
    request: Request,
    character_id: Optional[str] = Query(None, description="筛选特定角色的关系"),
    db: AsyncSession = Depends(get_db)
):
    # 验证用户权限
    user_id = getattr(request.state, 'user_id', None)
    await verify_project_access(project_id, user_id, db)
    
    """
    获取项目中的所有角色关系
    
    - 如果提供character_id，则只返回与该角色相关的关系（作为发起方或接收方）
    - 否则返回项目中的所有关系
    """
    query = select(CharacterRelationship).where(
        CharacterRelationship.project_id == project_id
    )
    
    if character_id:
        query = query.where(
            or_(
                CharacterRelationship.character_from_id == character_id,
                CharacterRelationship.character_to_id == character_id
            )
        )
    
    query = query.order_by(CharacterRelationship.created_at.desc())
    result = await db.execute(query)
    relationships = result.scalars().all()
    
    logger.info(f"获取项目 {project_id} 的关系列表，共 {len(relationships)} 条")
    return relationships


@router.get("/graph/{project_id}", response_model=RelationshipGraphData, summary="获取关系图谱数据")
async def get_relationship_graph(
    project_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    # 验证用户权限
    user_id = getattr(request.state, 'user_id', None)
    await verify_project_access(project_id, user_id, db)
    
    """
    获取用于可视化的关系图谱数据
    
    返回格式：
    - nodes: 角色节点列表
    - links: 关系连线列表
    """
    # 获取所有角色（节点）
    chars_result = await db.execute(
        select(Character).where(Character.project_id == project_id)
    )
    characters = chars_result.scalars().all()
    
    nodes = [
        RelationshipGraphNode(
            id=c.id,
            name=c.name,
            type="organization" if c.is_organization else "character",
            role_type=c.role_type,
            avatar=c.avatar_url
        )
        for c in characters
    ]
    
    # 获取所有角色关系（边）
    rels_result = await db.execute(
        select(CharacterRelationship).where(
            CharacterRelationship.project_id == project_id
        )
    )
    relationships = rels_result.scalars().all()

    links = [
        RelationshipGraphLink(
            source=r.character_from_id,
            target=r.character_to_id,
            relationship=r.relationship_name or "未知关系",
            intimacy=r.intimacy_level,
            status=r.status
        )
        for r in relationships
    ]

    # 获取组织成员关系（组织 -> 成员）并追加到图谱边
    # source 使用组织对应的角色ID（Organization.character_id），确保与节点ID一致
    members_result = await db.execute(
        select(OrganizationMember, Organization).join(
            Organization,
            OrganizationMember.organization_id == Organization.id
        ).where(Organization.project_id == project_id)
    )
    org_members = members_result.all()

    member_links = [
        RelationshipGraphLink(
            source=org.character_id,
            target=member.character_id,
            relationship=f"组织成员·{member.position}",
            intimacy=member.loyalty,
            status=member.status
        )
        for member, org in org_members
    ]

    links.extend(member_links)

    logger.info(
        f"获取项目 {project_id} 的关系图谱：{len(nodes)} 个节点，"
        f"{len(relationships)} 条角色关系，{len(member_links)} 条组织成员关系"
    )
    return RelationshipGraphData(nodes=nodes, links=links)


@router.post("/generate-stream", summary="AI分析大纲/章节生成角色关系（流式）")
async def generate_relationships_stream(
    gen_request: RelationshipGenerateRequest,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
    user_ai_service: AIService = Depends(get_user_ai_service)
):
    """使用已有角色、大纲和章节分析生成角色关系，返回SSE进度。"""
    async def generate() -> AsyncGenerator[str, None]:
        tracker = WizardProgressTracker("角色关系")
        try:
            user_id = getattr(http_request.state, 'user_id', None)
            project = await verify_project_access(gen_request.project_id, user_id, db)

            yield await tracker.start()
            yield await tracker.loading("加载角色和已有关系...", 0.25)

            characters_result = await db.execute(
                select(Character)
                .where(
                    Character.project_id == gen_request.project_id,
                    Character.is_organization == False
                )
                .order_by(Character.created_at.asc())
            )
            characters = characters_result.scalars().all()
            if len(characters) < 2:
                yield await tracker.error("至少需要两个角色才能分析生成关系")
                return

            relationships_result = await db.execute(
                select(CharacterRelationship)
                .where(CharacterRelationship.project_id == gen_request.project_id)
            )
            existing_relationships = relationships_result.scalars().all()

            character_by_id = {character.id: character for character in characters}
            character_name_counts: dict[str, int] = {}
            for character in characters:
                character_name_counts[character.name] = character_name_counts.get(character.name, 0) + 1
            unique_character_by_name = {
                character.name: character
                for character in characters
                if character_name_counts.get(character.name, 0) == 1
            }
            existing_pairs = {
                frozenset((relationship.character_from_id, relationship.character_to_id))
                for relationship in existing_relationships
            }

            character_context = "\n".join(
                f"- ID:{character.id}｜{character.name}（{character.role_type or '角色'}）"
                f"：{(character.background or character.personality or '暂无设定')[:180]}"
                for character in characters[:80]
            )
            existing_context = "\n".join(
                f"- {character_by_id.get(relationship.character_from_id).name if character_by_id.get(relationship.character_from_id) else '未知'}"
                f" -> {character_by_id.get(relationship.character_to_id).name if character_by_id.get(relationship.character_to_id) else '未知'}"
                f"：{relationship.relationship_name or '关系'}，亲密度{relationship.intimacy_level}"
                for relationship in existing_relationships[:80]
            ) or "暂无已入库关系"

            yield await tracker.loading("分析已有大纲和章节...", 0.55)
            story_context = await build_project_story_context(db, gen_request.project_id)

            requirements = (gen_request.requirements or "").strip() or "无"
            prompt = f"""
你是小说人物关系分析师。请基于项目已有角色、大纲和章节，补充生成尚未入库的角色关系。

项目信息：
- 书名：{project.title}
- 类型：{project.genre or '未设定'}
- 主题：{project.theme or '未设定'}
- 世界规则：{project.world_rules or '未设定'}

【已有角色】
{character_context}

【已入库关系】
{existing_context}

{story_context}

用户要求：
{requirements}

生成要求：
- 本次最多生成 {gen_request.relationship_count} 条关系
- 只能使用【已有角色】中的角色 ID，ID 必须完全匹配
- 优先从已有大纲和章节中的同伴、敌对、上下级、旧识、亲属、师承、合作、利用等关系中提取
- 不要重复已入库关系，不要生成没有文本依据的臆测关系
- intimacy_level 使用 -100 到 100，敌对为负，疏离/复杂接近0，亲近为正
- status 只能为 active、broken、past、complicated
- 只输出 JSON，不要 Markdown，不要解释

返回格式：
{{
  "relationships": [
    {{
      "character_from_id": "角色A的ID",
      "character_to_id": "角色B的ID",
      "character_from_name": "角色A名称",
      "character_to_name": "角色B名称",
      "relationship_name": "关系名称",
      "intimacy_level": 50,
      "status": "active",
      "description": "关系依据和简述",
      "started_at": "关系开始时间或章节，可选"
    }}
  ]
}}
"""

            yield await tracker.generating(0, max(3000, len(prompt) * 8), "调用AI分析生成关系...")
            ai_content = ""
            chunk_count = 0
            estimated_total = max(3000, len(prompt) * 8)
            async for chunk in wrap_stream_with_heartbeat(
                user_ai_service.generate_text_stream(prompt=prompt),
                heartbeat_interval=15.0
            ):
                if chunk is HEARTBEAT:
                    yield await tracker.heartbeat()
                    continue

                chunk_count += 1
                ai_content += chunk
                yield await SSEResponse.send_chunk(chunk)
                if chunk_count % 8 == 0:
                    yield await tracker.generating(len(ai_content), estimated_total)

            if not ai_content.strip():
                yield await tracker.error("AI服务返回空响应")
                return

            yield await tracker.parsing("解析AI返回的关系数据...", 0.65)
            try:
                cleaned_response = user_ai_service._clean_json_response(ai_content)
                relationship_data = loads_json(cleaned_response)
            except json.JSONDecodeError as e:
                logger.error(f"关系JSON解析失败: {e}")
                yield await tracker.error(f"AI返回的内容无法解析为JSON：{str(e)}")
                return
            if not isinstance(relationship_data, dict):
                yield await tracker.error("AI返回格式不正确：应为JSON对象")
                return

            created_relationships: list[str] = []
            skipped_count = 0
            allowed_statuses = {"active", "broken", "past", "complicated"}
            relationship_items = relationship_data.get("relationships") or []
            if not isinstance(relationship_items, list):
                yield await tracker.error("AI返回格式不正确：relationships 应为数组")
                return

            def resolve_character(item: dict, id_key: str, name_key: str) -> Optional[Character]:
                character_id = str(item.get(id_key) or "").strip()
                if character_id:
                    return character_by_id.get(character_id)
                character_name = str(item.get(name_key) or "").strip()
                if character_name:
                    return unique_character_by_name.get(character_name)
                return None

            yield await tracker.saving("保存关系到数据库...", 0.8)
            for item in relationship_items[:gen_request.relationship_count]:
                if not isinstance(item, dict):
                    skipped_count += 1
                    continue
                from_character = resolve_character(item, "character_from_id", "character_from_name")
                to_character = resolve_character(item, "character_to_id", "character_to_name")
                if not from_character or not to_character or from_character.id == to_character.id:
                    skipped_count += 1
                    continue

                pair_key = frozenset((from_character.id, to_character.id))
                if pair_key in existing_pairs:
                    skipped_count += 1
                    continue

                try:
                    intimacy_level = int(item.get("intimacy_level", 50))
                except (TypeError, ValueError):
                    intimacy_level = 50
                intimacy_level = max(-100, min(100, intimacy_level))

                status = str(item.get("status") or "active").strip()
                if status not in allowed_statuses:
                    status = "active"

                relationship = CharacterRelationship(
                    project_id=gen_request.project_id,
                    character_from_id=from_character.id,
                    character_to_id=to_character.id,
                    relationship_name=str(item.get("relationship_name") or "关联").strip()[:100],
                    intimacy_level=intimacy_level,
                    status=status,
                    description=str(item.get("description") or "").strip() or None,
                    started_at=str(item.get("started_at") or "").strip() or None,
                    source="ai"
                )
                db.add(relationship)
                existing_pairs.add(pair_key)
                created_relationships.append(
                    f"{from_character.name} - {to_character.name}: {relationship.relationship_name}"
                )

            history = GenerationHistory(
                project_id=gen_request.project_id,
                prompt=prompt,
                generated_content=ai_content,
                model=user_ai_service.default_model
            )
            db.add(history)
            await db.commit()

            yield await tracker.complete(f"关系生成完成，新增 {len(created_relationships)} 条")
            yield await tracker.result({
                "created_count": len(created_relationships),
                "skipped_count": skipped_count,
                "relationships": created_relationships
            })
            yield await tracker.done()

        except HTTPException as he:
            logger.error(f"HTTP异常: {he.detail}")
            yield await tracker.error(he.detail, he.status_code)
        except Exception as e:
            logger.error(f"生成关系失败: {str(e)}", exc_info=True)
            yield await tracker.error(f"生成关系失败: {str(e)}")

    return create_sse_response(generate())


@router.post("/", response_model=CharacterRelationshipResponse, summary="创建角色关系")
async def create_relationship(
    relationship: CharacterRelationshipCreate,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """
    手动创建角色关系
    
    - 需要提供角色A和角色B的ID
    - 可以指定预定义的关系类型或自定义关系名称
    - 可以设置亲密度、状态等属性
    """
    # 验证用户权限
    user_id = getattr(request.state, 'user_id', None)
    await verify_project_access(relationship.project_id, user_id, db)
    
    # 验证角色是否存在
    char_from = await db.execute(
        select(Character).where(Character.id == relationship.character_from_id)
    )
    char_to = await db.execute(
        select(Character).where(Character.id == relationship.character_to_id)
    )
    
    if not char_from.scalar_one_or_none():
        raise HTTPException(status_code=404, detail=f"角色A（ID: {relationship.character_from_id}）不存在")
    if not char_to.scalar_one_or_none():
        raise HTTPException(status_code=404, detail=f"角色B（ID: {relationship.character_to_id}）不存在")
    
    # 创建关系
    db_relationship = CharacterRelationship(
        **relationship.model_dump(),
        source="manual"
    )
    db.add(db_relationship)
    await db.commit()
    await db.refresh(db_relationship)
    
    logger.info(f"创建关系成功：{relationship.character_from_id} -> {relationship.character_to_id}")
    return db_relationship


@router.put("/{relationship_id}", response_model=CharacterRelationshipResponse, summary="更新关系")
async def update_relationship(
    relationship_id: str,
    relationship: CharacterRelationshipUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """更新角色关系的属性（亲密度、状态等）"""
    result = await db.execute(
        select(CharacterRelationship).where(
            CharacterRelationship.id == relationship_id
        )
    )
    db_rel = result.scalar_one_or_none()
    
    if not db_rel:
        raise HTTPException(status_code=404, detail="关系不存在")
    
    # 验证用户权限
    user_id = getattr(request.state, 'user_id', None)
    await verify_project_access(db_rel.project_id, user_id, db)
    
    # 更新字段
    update_data = relationship.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(db_rel, field, value)
    
    await db.commit()
    await db.refresh(db_rel)
    
    logger.info(f"更新关系成功：{relationship_id}")
    return db_rel


@router.delete("/{relationship_id}", summary="删除关系")
async def delete_relationship(
    relationship_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """删除角色关系"""
    result = await db.execute(
        select(CharacterRelationship).where(
            CharacterRelationship.id == relationship_id
        )
    )
    db_rel = result.scalar_one_or_none()
    
    if not db_rel:
        raise HTTPException(status_code=404, detail="关系不存在")
    
    # 验证用户权限
    user_id = getattr(request.state, 'user_id', None)
    await verify_project_access(db_rel.project_id, user_id, db)
    
    await db.delete(db_rel)
    await db.commit()
    
    logger.info(f"删除关系成功：{relationship_id}")
    return {"message": "关系删除成功", "id": relationship_id}
