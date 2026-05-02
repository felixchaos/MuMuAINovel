"""组织管理API"""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from typing import List, Optional, AsyncGenerator
from pydantic import BaseModel, Field
import json

from app.database import get_db
from app.utils.sse_response import SSEResponse, create_sse_response, WizardProgressTracker, wrap_stream_with_heartbeat, HEARTBEAT
from app.models.relationship import Organization, OrganizationMember
from app.models.character import Character
from app.models.project import Project
from app.models.generation_history import GenerationHistory
from app.schemas.relationship import (
    OrganizationCreate,
    OrganizationUpdate,
    OrganizationResponse,
    OrganizationDetailResponse,
    OrganizationMemberCreate,
    OrganizationMemberUpdate,
    OrganizationMemberResponse,
    OrganizationMemberDetailResponse
)
from app.schemas.character import CharacterResponse
from app.services.ai_service import AIService
from app.services.json_helper import loads_json
from app.services.prompt_service import prompt_service, PromptService
from app.services.project_story_context import build_project_story_context
from app.logger import get_logger
from app.api.settings import get_user_ai_service
from app.api.common import verify_project_access

router = APIRouter(prefix="/organizations", tags=["组织管理"])
logger = get_logger(__name__)


class OrganizationGenerateRequest(BaseModel):
    """AI生成组织的请求模型"""
    project_id: str = Field(..., description="项目ID")
    name: Optional[str] = Field(None, description="组织名称")
    organization_type: Optional[str] = Field(None, description="组织类型")
    background: Optional[str] = Field(None, description="组织背景")
    requirements: Optional[str] = Field(None, description="特殊要求")
    enable_mcp: bool = Field(True, description="是否启用MCP工具增强（搜索组织架构参考）")


@router.get("/project/{project_id}", response_model=List[OrganizationDetailResponse], summary="获取项目的所有组织")
async def get_project_organizations(
    project_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    # 验证用户权限
    user_id = getattr(request.state, 'user_id', None)
    await verify_project_access(project_id, user_id, db)
    
    """
    获取项目中的所有组织及其详情
    
    返回组织的基本信息和统计数据
    """
    result = await db.execute(
        select(Organization).where(Organization.project_id == project_id)
    )
    organizations = result.scalars().all()
    
    # 获取每个组织的角色信息
    org_list = []
    for org in organizations:
        char_result = await db.execute(
            select(Character).where(Character.id == org.character_id)
        )
        char = char_result.scalar_one_or_none()
        
        if char:
            org_list.append(OrganizationDetailResponse(
                id=org.id,
                character_id=org.character_id,
                name=char.name,
                type=char.organization_type,
                purpose=char.organization_purpose,
                member_count=org.member_count,
                power_level=org.power_level,
                location=org.location,
                motto=org.motto,
                color=org.color
            ))
    
    logger.info(f"获取项目 {project_id} 的组织列表，共 {len(org_list)} 个")
    return org_list


@router.get("/{org_id}", response_model=OrganizationResponse, summary="获取组织详情")
async def get_organization(
    org_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """获取组织的详细信息"""
    result = await db.execute(
        select(Organization).where(Organization.id == org_id)
    )
    org = result.scalar_one_or_none()
    
    if not org:
        raise HTTPException(status_code=404, detail="组织不存在")
    
    # 验证用户权限
    user_id = getattr(request.state, 'user_id', None)
    await verify_project_access(org.project_id, user_id, db)
    
    return org


@router.post("", response_model=OrganizationResponse, summary="创建组织")
async def create_organization(
    organization: OrganizationCreate,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """
    创建新组织
    
    - 需要关联到一个已存在的角色记录（is_organization=True）
    - 可以设置父组织、势力等级等属性
    """
    # 验证用户权限
    user_id = getattr(request.state, 'user_id', None)
    await verify_project_access(organization.project_id, user_id, db)
    
    # 验证角色是否存在且是组织
    char_result = await db.execute(
        select(Character).where(Character.id == organization.character_id)
    )
    char = char_result.scalar_one_or_none()
    
    if not char:
        raise HTTPException(status_code=404, detail="关联的角色不存在")
    if not char.is_organization:
        raise HTTPException(status_code=400, detail="关联的角色不是组织类型")
    
    # 检查是否已存在
    existing = await db.execute(
        select(Organization).where(Organization.character_id == organization.character_id)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="该角色已有组织详情记录")
    
    # 创建组织
    db_org = Organization(**organization.model_dump())
    db.add(db_org)
    await db.commit()
    await db.refresh(db_org)
    
    logger.info(f"创建组织成功：{db_org.id} - {char.name}")
    return db_org


@router.put("/{org_id}", response_model=OrganizationResponse, summary="更新组织")
async def update_organization(
    org_id: str,
    organization: OrganizationUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """更新组织的属性"""
    result = await db.execute(
        select(Organization).where(Organization.id == org_id)
    )
    db_org = result.scalar_one_or_none()
    
    if not db_org:
        raise HTTPException(status_code=404, detail="组织不存在")
    
    # 验证用户权限
    user_id = getattr(request.state, 'user_id', None)
    await verify_project_access(db_org.project_id, user_id, db)
    
    # 更新 Organization 表字段
    update_data = organization.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(db_org, field, value)
    
    await db.commit()
    await db.refresh(db_org)
    
    logger.info(f"更新组织成功：{org_id}")
    return db_org


@router.delete("/{org_id}", summary="删除组织")
async def delete_organization(
    org_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """删除组织（会级联删除所有成员关系）"""
    result = await db.execute(
        select(Organization).where(Organization.id == org_id)
    )
    db_org = result.scalar_one_or_none()
    
    if not db_org:
        raise HTTPException(status_code=404, detail="组织不存在")
    
    # 验证用户权限
    user_id = getattr(request.state, 'user_id', None)
    await verify_project_access(db_org.project_id, user_id, db)
    
    await db.delete(db_org)
    await db.commit()
    
    logger.info(f"删除组织成功：{org_id}")
    return {"message": "组织删除成功", "id": org_id}


# ============ 组织成员管理 ============

@router.get("/{org_id}/members", response_model=List[OrganizationMemberDetailResponse], summary="获取组织成员")
async def get_organization_members(
    org_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """
    获取组织的所有成员
    
    按职位等级（rank）降序排列
    """
    # 验证组织存在
    org_result = await db.execute(
        select(Organization).where(Organization.id == org_id)
    )
    org = org_result.scalar_one_or_none()
    if not org:
        raise HTTPException(status_code=404, detail="组织不存在")
    
    # 验证用户权限
    user_id = getattr(request.state, 'user_id', None)
    await verify_project_access(org.project_id, user_id, db)
    
    # 获取成员列表
    result = await db.execute(
        select(OrganizationMember)
        .where(OrganizationMember.organization_id == org_id)
        .order_by(OrganizationMember.rank.desc(), OrganizationMember.created_at)
    )
    members = result.scalars().all()
    
    # 获取成员角色信息
    member_list = []
    for member in members:
        char_result = await db.execute(
            select(Character).where(Character.id == member.character_id)
        )
        char = char_result.scalar_one_or_none()
        
        if char:
            member_list.append(OrganizationMemberDetailResponse(
                id=member.id,
                character_id=member.character_id,
                character_name=char.name,
                position=member.position,
                rank=member.rank,
                loyalty=member.loyalty,
                contribution=member.contribution,
                status=member.status,
                joined_at=member.joined_at,
                left_at=member.left_at,
                notes=member.notes
            ))
    
    logger.info(f"获取组织 {org_id} 的成员列表，共 {len(member_list)} 人")
    return member_list


@router.post("/{org_id}/members", response_model=OrganizationMemberResponse, summary="添加组织成员")
async def add_organization_member(
    org_id: str,
    member: OrganizationMemberCreate,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """
    添加角色到组织
    
    - 一个角色在同一组织中只能有一个职位
    - 会自动更新组织的成员计数
    """
    # 验证组织存在
    org_result = await db.execute(
        select(Organization).where(Organization.id == org_id)
    )
    org = org_result.scalar_one_or_none()
    if not org:
        raise HTTPException(status_code=404, detail="组织不存在")
    
    # 验证用户权限
    user_id = getattr(request.state, 'user_id', None)
    await verify_project_access(org.project_id, user_id, db)
    
    # 验证角色存在
    char_result = await db.execute(
        select(Character).where(Character.id == member.character_id)
    )
    char = char_result.scalar_one_or_none()
    if not char:
        raise HTTPException(status_code=404, detail="角色不存在")
    if char.is_organization:
        raise HTTPException(status_code=400, detail="不能将组织添加为成员")
    
    # 检查是否已存在
    existing = await db.execute(
        select(OrganizationMember).where(
            and_(
                OrganizationMember.organization_id == org_id,
                OrganizationMember.character_id == member.character_id
            )
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="该角色已在组织中")
    
    # 创建成员关系
    db_member = OrganizationMember(
        organization_id=org_id,
        **member.model_dump(),
        source="manual"
    )
    db.add(db_member)
    
    # 更新组织成员计数
    org.member_count += 1
    
    await db.commit()
    await db.refresh(db_member)
    
    logger.info(f"添加成员成功：{char.name} 加入组织 {org_id}")
    return db_member


@router.put("/members/{member_id}", response_model=OrganizationMemberResponse, summary="更新成员信息")
async def update_organization_member(
    member_id: str,
    member: OrganizationMemberUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """更新组织成员的职位、忠诚度等信息"""
    result = await db.execute(
        select(OrganizationMember).where(OrganizationMember.id == member_id)
    )
    db_member = result.scalar_one_or_none()
    
    if not db_member:
        raise HTTPException(status_code=404, detail="成员记录不存在")
    
    # 通过成员所属的组织验证用户权限
    org_result = await db.execute(
        select(Organization).where(Organization.id == db_member.organization_id)
    )
    org = org_result.scalar_one()
    user_id = getattr(request.state, 'user_id', None)
    await verify_project_access(org.project_id, user_id, db)
    
    # 更新字段
    update_data = member.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(db_member, field, value)
    
    await db.commit()
    await db.refresh(db_member)
    
    logger.info(f"更新成员信息成功：{member_id}")
    return db_member


@router.delete("/members/{member_id}", summary="移除组织成员")
async def remove_organization_member(
    member_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """
    从组织中移除成员
    
    会自动更新组织的成员计数
    """
    result = await db.execute(
        select(OrganizationMember).where(OrganizationMember.id == member_id)
    )
    db_member = result.scalar_one_or_none()
    
    if not db_member:
        raise HTTPException(status_code=404, detail="成员记录不存在")
    
    # 更新组织成员计数
    org_result = await db.execute(
        select(Organization).where(Organization.id == db_member.organization_id)
    )
    org = org_result.scalar_one()
    
    # 验证用户权限
    user_id = getattr(request.state, 'user_id', None)
    await verify_project_access(org.project_id, user_id, db)
    org.member_count = max(0, org.member_count - 1)
    
    await db.delete(db_member)
    await db.commit()
    
    logger.info(f"移除成员成功：{member_id}")
    return {"message": "成员移除成功", "id": member_id}

@router.post("/generate-stream", summary="AI生成组织（流式）")
async def generate_organization_stream(
    gen_request: OrganizationGenerateRequest,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
    user_ai_service: AIService = Depends(get_user_ai_service)
):
    """
    使用AI生成组织设定（支持SSE流式进度显示）
    
    通过Server-Sent Events返回实时进度信息
    """
    async def generate() -> AsyncGenerator[str, None]:
        tracker = WizardProgressTracker("组织")
        try:
            # 验证用户权限和项目是否存在
            user_id = getattr(http_request.state, 'user_id', None)
            project = await verify_project_access(gen_request.project_id, user_id, db)
            
            yield await tracker.start()
            
            # 获取已存在的角色和组织列表
            yield await tracker.loading("获取项目上下文...", 0.3)
            
            existing_chars_result = await db.execute(
                select(Character)
                .where(Character.project_id == gen_request.project_id)
                .order_by(Character.created_at.desc())
            )
            existing_characters = existing_chars_result.scalars().all()
            
            # 构建现有角色和组织信息摘要
            existing_info = ""
            character_list = []
            organization_list = []
            
            if existing_characters:
                for c in existing_characters[:10]:
                    if c.is_organization:
                        organization_list.append(f"- {c.name} [{c.organization_type or '组织'}]")
                    else:
                        character_list.append(f"- {c.name}（{c.role_type or '未知'}）")
                
                if character_list:
                    existing_info += "\n已有角色：\n" + "\n".join(character_list)
                if organization_list:
                    existing_info += "\n\n已有组织：\n" + "\n".join(organization_list)
            
            # 构建项目上下文
            story_context = await build_project_story_context(db, gen_request.project_id)
            project_context = f"""
项目信息：
- 书名：{project.title}
- 主题：{project.theme or '未设定'}
- 类型：{project.genre or '未设定'}
- 时间背景：{project.world_time_period or '未设定'}
- 地理位置：{project.world_location or '未设定'}
- 氛围基调：{project.world_atmosphere or '未设定'}
- 世界规则：{project.world_rules or '未设定'}
{existing_info}

{story_context}
"""
            
            user_input = f"""
用户要求：
- 组织名称：{gen_request.name or '请AI生成'}
- 组织类型：{gen_request.organization_type or '请AI根据世界观决定'}
- 背景设定：{gen_request.background or '无特殊要求'}
- 其他要求：{gen_request.requirements or '无'}
"""
            
            yield await tracker.loading("项目上下文准备完成", 0.7)
            yield await tracker.preparing("构建AI提示词...")
            
            # 获取自定义提示词模板
            template = await PromptService.get_template("SINGLE_ORGANIZATION_GENERATION", user_id, db)
            # 格式化提示词
            prompt = PromptService.format_prompt(
                template,
                project_context=project_context,
                user_input=user_input
            )
            
            yield await tracker.generating(0, max(3000, len(prompt) * 8), "调用AI服务生成组织...")
            logger.info(f"🎯 开始为项目 {gen_request.project_id} 生成组织（SSE流式）")
            
            try:
                # 使用流式生成替代非流式
                ai_content = ""
                chunk_count = 0
                estimated_total = max(3000, len(prompt) * 8)
                
                async for chunk in wrap_stream_with_heartbeat(
                    user_ai_service.generate_text_stream(prompt=prompt),
                    heartbeat_interval=15.0
                ):
                    # 心跳哨兵：发送心跳保活，不混入AI响应
                    if chunk is HEARTBEAT:
                        yield await tracker.heartbeat()
                        continue

                    chunk_count += 1
                    ai_content += chunk
                    
                    # 发送内容块
                    yield await SSEResponse.send_chunk(chunk)
                    
                    # 定期更新字数（避免过于频繁）
                    if chunk_count % 5 == 0:
                        yield await tracker.generating(len(ai_content), estimated_total)
                    
                    # 心跳
                    if chunk_count % 20 == 0:
                        yield await tracker.heartbeat()
                        
            except Exception as ai_error:
                logger.error(f"❌ AI服务调用异常：{str(ai_error)}")
                yield await tracker.error(f"AI服务调用失败：{str(ai_error)}")
                return
            
            if not ai_content or not ai_content.strip():
                yield await tracker.error("AI服务返回空响应")
                return
            
            yield await tracker.parsing("解析AI响应...", 0.5)
            
            # ✅ 使用统一的 JSON 清洗方法
            try:
                cleaned_response = user_ai_service._clean_json_response(ai_content)
                organization_data = loads_json(cleaned_response)
                logger.info(f"✅ 组织JSON解析成功")
            except json.JSONDecodeError as e:
                logger.error(f"❌ 组织JSON解析失败: {e}")
                logger.error(f"   原始响应预览: {ai_content[:200]}")
                yield await tracker.error(f"AI返回的内容无法解析为JSON：{str(e)}")
                return
            
            yield await tracker.saving("创建组织记录...", 0.3)
            
            # 创建角色记录（组织也是角色的一种）
            character = Character(
                project_id=gen_request.project_id,
                name=organization_data.get("name", gen_request.name or "未命名组织"),
                is_organization=True,
                role_type="supporting",
                personality=organization_data.get("personality", ""),
                background=organization_data.get("background", ""),
                appearance=organization_data.get("appearance", ""),
                organization_type=organization_data.get("organization_type"),
                organization_purpose=organization_data.get("organization_purpose"),
                traits=json.dumps(
                    organization_data.get("traits", []), 
                    ensure_ascii=False
                )
            )
            db.add(character)
            await db.flush()
            
            logger.info(f"✅ 组织角色创建成功：{character.name} (ID: {character.id})")
            
            yield await tracker.saving("创建组织详情...", 0.6)
            
            # 自动创建Organization详情记录
            organization = Organization(
                character_id=character.id,
                project_id=gen_request.project_id,
                member_count=0,
                power_level=organization_data.get("power_level", 50),
                location=organization_data.get("location"),
                motto=organization_data.get("motto"),
                color=organization_data.get("color")
            )
            db.add(organization)
            await db.flush()
            
            logger.info(f"✅ 组织详情创建成功：{character.name} (Org ID: {organization.id})")
            
            yield await tracker.saving("保存生成历史...", 0.9)
            
            # 记录生成历史
            history = GenerationHistory(
                project_id=gen_request.project_id,
                prompt=prompt,
                generated_content=ai_content,
                model=user_ai_service.default_model
            )
            db.add(history)
            
            await db.commit()
            await db.refresh(character)
            
            logger.info(f"🎉 成功生成组织: {character.name}")
            
            yield await tracker.complete("组织生成完成！")
            
            # 发送结果数据
            yield await tracker.result({
                "character": {
                    "id": character.id,
                    "name": character.name,
                    "organization_type": character.organization_type,
                    "is_organization": character.is_organization
                }
            })
            
            yield await tracker.done()
            
        except HTTPException as he:
            logger.error(f"HTTP异常: {he.detail}")
            yield await tracker.error(he.detail, he.status_code)
        except Exception as e:
            logger.error(f"生成组织失败: {str(e)}")
            yield await tracker.error(f"生成组织失败: {str(e)}")
    
    return create_sse_response(generate())
