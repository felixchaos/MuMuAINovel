"""Read-only story engineering snapshot builder.

This module intentionally reuses the official data model. It does not create
new tables or replace existing workflows, so fork-specific story engineering
features can grow without breaking upstream compatibility.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.career import Career
from app.models.character import Character
from app.models.chapter import Chapter
from app.models.foreshadow import Foreshadow
from app.models.memory import PlotAnalysis, StoryMemory
from app.models.outline import Outline
from app.models.project import Project
from app.models.relationship import CharacterRelationship
from app.schemas.story_engine import (
    StoryEngineItem,
    StoryEngineMetric,
    StoryEngineRecommendation,
    StoryEngineSection,
    StoryEngineSnapshotResponse,
)
from app.services.project_story_context import build_project_story_context


def _compact_text(text: Optional[str], max_len: int = 180) -> str:
    cleaned = " ".join((text or "").split())
    if len(cleaned) <= max_len:
        return cleaned
    return f"{cleaned[:max_len].rstrip()}..."


def _metric_status(value: int, *, warning_min: int = 1) -> str:
    if value <= 0:
        return "empty"
    if value < warning_min:
        return "warning"
    return "ok"


def _coverage(*, value: int, target: int) -> int:
    if target <= 0:
        return 100 if value > 0 else 0
    return min(100, int(round((value / target) * 100)))


def _section_status(total: int, coverage: int) -> str:
    if total <= 0:
        return "empty"
    if coverage < 50:
        return "warning"
    return "ok"


async def _count(db: AsyncSession, model, *conditions) -> int:
    result = await db.execute(select(func.count()).select_from(model).where(*conditions))
    return int(result.scalar_one() or 0)


def _project_profile_items(project: Project) -> list[StoryEngineItem]:
    rows = [
        ("简介", project.description),
        ("主题", project.theme),
        ("类型", project.genre),
        ("时间背景", project.world_time_period),
        ("地理位置", project.world_location),
        ("氛围基调", project.world_atmosphere),
        ("世界规则", project.world_rules),
    ]
    return [
        StoryEngineItem(
            id=f"profile:{label}",
            title=label,
            summary=_compact_text(value, 220),
        )
        for label, value in rows
        if _compact_text(value, 220)
    ]


def _append_section(
    sections: list[StoryEngineSection],
    *,
    key: str,
    title: str,
    total: int,
    target: int,
    description: str,
    items: Iterable[StoryEngineItem],
) -> None:
    coverage = _coverage(value=total, target=target)
    sections.append(
        StoryEngineSection(
            key=key,
            title=title,
            description=description,
            status=_section_status(total, coverage),
            total=total,
            coverage=coverage,
            items=list(items),
        )
    )


def _build_context_text(
    project: Project,
    story_context: str,
    characters: list[Character],
    organizations: list[Character],
    careers: list[Career],
    foreshadows: list[Foreshadow],
) -> str:
    lines: list[str] = [
        f"【项目】{project.title}",
    ]
    if project.description:
        lines.append(f"简介：{_compact_text(project.description, 400)}")
    if project.theme:
        lines.append(f"主题：{_compact_text(project.theme, 260)}")
    if project.genre:
        lines.append(f"类型：{project.genre}")
    world_parts = [
        part for part in [
            project.world_time_period,
            project.world_location,
            project.world_atmosphere,
            project.world_rules,
        ]
        if part
    ]
    if world_parts:
        lines.append(f"世界设定：{_compact_text(' / '.join(world_parts), 700)}")

    if characters:
        lines.append("")
        lines.append("【核心角色】")
        for character in characters[:10]:
            role = character.role_type or "角色"
            summary = _compact_text(character.personality or character.background or character.current_state, 180)
            lines.append(f"- {character.name}（{role}）：{summary or '暂无摘要'}")

    if organizations:
        lines.append("")
        lines.append("【组织势力】")
        for organization in organizations[:8]:
            summary = _compact_text(
                organization.organization_purpose
                or organization.personality
                or organization.background,
                160,
            )
            lines.append(f"- {organization.name}：{summary or '暂无摘要'}")

    if careers:
        lines.append("")
        lines.append("【职业/力量体系】")
        for career in careers[:8]:
            lines.append(f"- {career.name}：{_compact_text(career.description or career.special_abilities, 160) or '暂无摘要'}")

    if foreshadows:
        lines.append("")
        lines.append("【活跃伏笔】")
        for foreshadow in foreshadows[:8]:
            lines.append(f"- {foreshadow.title}（{foreshadow.status}）：{_compact_text(foreshadow.content, 160)}")

    lines.append("")
    lines.append(story_context)
    return "\n".join(line for line in lines if line is not None)


def _recommendations(
    *,
    project: Project,
    outline_count: int,
    chapter_count: int,
    content_chapter_count: int,
    character_count: int,
    organization_count: int,
    relationship_count: int,
    career_count: int,
    foreshadow_count: int,
    analysis_count: int,
) -> list[StoryEngineRecommendation]:
    recs: list[StoryEngineRecommendation] = []

    world_fields = [
        project.world_time_period,
        project.world_location,
        project.world_atmosphere,
        project.world_rules,
    ]
    if sum(1 for item in world_fields if item) < 3:
        recs.append(
            StoryEngineRecommendation(
                key="complete-world-profile",
                title="先补齐世界设定骨架",
                detail="时间、地点、氛围、规则不足时，后续剧情线和章节生成会更容易漂移。",
                priority="high",
                source="world-setting",
            )
        )

    if outline_count == 0:
        recs.append(
            StoryEngineRecommendation(
                key="create-outline",
                title="建立主线大纲",
                detail="剧情工程层需要先知道故事的大方向，建议先生成或导入基础大纲。",
                priority="high",
                source="outline",
            )
        )

    if character_count < 3:
        recs.append(
            StoryEngineRecommendation(
                key="expand-characters",
                title="补足主要角色卡",
                detail="角色少于 3 个时，关系网、冲突推进和章节一致性检查会缺少支点。",
                priority="medium",
                source="characters",
            )
        )

    if relationship_count == 0 and character_count >= 2:
        recs.append(
            StoryEngineRecommendation(
                key="derive-relationships",
                title="从现有大纲/章节分析角色关系",
                detail="已有角色但没有关系记录，后续可接入现有 AI 关系生成流程来补全关系网。",
                priority="medium",
                source="relationships",
            )
        )

    if career_count == 0:
        recs.append(
            StoryEngineRecommendation(
                key="derive-careers",
                title="沉淀职业/力量体系",
                detail="职业、能力和规则应作为独立设定留存，避免章节生成时临时编造。",
                priority="medium",
                source="careers",
            )
        )

    if organization_count == 0:
        recs.append(
            StoryEngineRecommendation(
                key="derive-organizations",
                title="补一层组织/势力结构",
                detail="组织结构能把角色、冲突、阵营和地图串起来，是剧情线管理的重要支架。",
                priority="low",
                source="organizations",
            )
        )

    if content_chapter_count > 0 and analysis_count < content_chapter_count:
        recs.append(
            StoryEngineRecommendation(
                key="analyze-chapters",
                title="补齐章节分析覆盖率",
                detail=f"已有正文章节 {content_chapter_count} 章，完成分析 {analysis_count} 章；剧情工程会优先使用分析结果。",
                priority="high" if analysis_count == 0 else "medium",
                source="chapter-analysis",
            )
        )

    if foreshadow_count == 0 and analysis_count > 0:
        recs.append(
            StoryEngineRecommendation(
                key="sync-foreshadows",
                title="把分析出的伏笔同步成可管理条目",
                detail="剧情分析里的伏笔如果不进入伏笔管理，后续章节生成时很难稳定提醒和回收。",
                priority="medium",
                source="foreshadows",
            )
        )

    if chapter_count > 0 and outline_count > 0:
        recs.append(
            StoryEngineRecommendation(
                key="next-plot-cards",
                title="下一步适合接入剧情卡",
                detail="现有大纲和章节已经可作为上下文，后续可以按章节/大纲生成剧情卡与剧情线，而不是替换原流程。",
                priority="low",
                source="story-engine",
            )
        )

    return recs[:8]


async def build_story_engine_snapshot(
    db: AsyncSession,
    project: Project,
    *,
    context_limit: int = 12000,
) -> StoryEngineSnapshotResponse:
    """Build a read-only story-engine snapshot for a project."""
    project_id = project.id

    outline_count = await _count(db, Outline, Outline.project_id == project_id)
    chapter_count = await _count(db, Chapter, Chapter.project_id == project_id)
    content_chapter_count = await _count(
        db,
        Chapter,
        Chapter.project_id == project_id,
        Chapter.content.is_not(None),
        func.length(func.trim(Chapter.content)) > 0,
    )
    character_count = await _count(
        db,
        Character,
        Character.project_id == project_id,
        Character.is_organization.is_(False),
    )
    organization_count = await _count(
        db,
        Character,
        Character.project_id == project_id,
        Character.is_organization.is_(True),
    )
    relationship_count = await _count(db, CharacterRelationship, CharacterRelationship.project_id == project_id)
    career_count = await _count(db, Career, Career.project_id == project_id)
    foreshadow_count = await _count(db, Foreshadow, Foreshadow.project_id == project_id)
    analysis_count = await _count(db, PlotAnalysis, PlotAnalysis.project_id == project_id)
    memory_count = await _count(db, StoryMemory, StoryMemory.project_id == project_id)

    outline_rows = (
        await db.execute(
            select(Outline)
            .where(Outline.project_id == project_id)
            .order_by(Outline.order_index.asc(), Outline.created_at.asc())
            .limit(8)
        )
    ).scalars().all()
    chapter_rows = (
        await db.execute(
            select(Chapter)
            .where(Chapter.project_id == project_id)
            .order_by(Chapter.chapter_number.desc(), Chapter.created_at.desc())
            .limit(8)
        )
    ).scalars().all()
    character_rows = (
        await db.execute(
            select(Character)
            .where(Character.project_id == project_id, Character.is_organization.is_(False))
            .order_by(Character.created_at.asc())
            .limit(10)
        )
    ).scalars().all()
    organization_rows = (
        await db.execute(
            select(Character)
            .where(Character.project_id == project_id, Character.is_organization.is_(True))
            .order_by(Character.created_at.asc())
            .limit(8)
        )
    ).scalars().all()
    career_rows = (
        await db.execute(
            select(Career)
            .where(Career.project_id == project_id)
            .order_by(Career.created_at.asc())
            .limit(8)
        )
    ).scalars().all()
    foreshadow_rows = (
        await db.execute(
            select(Foreshadow)
            .where(Foreshadow.project_id == project_id)
            .order_by(Foreshadow.urgency.desc(), Foreshadow.importance.desc(), Foreshadow.created_at.desc())
            .limit(8)
        )
    ).scalars().all()

    profile_items = _project_profile_items(project)
    sections: list[StoryEngineSection] = []
    _append_section(
        sections,
        key="profile",
        title="项目与世界骨架",
        total=len(profile_items),
        target=7,
        description="用于锁定题材、主题、世界规则和生成基调。",
        items=profile_items,
    )
    _append_section(
        sections,
        key="outlines",
        title="大纲结构",
        total=outline_count,
        target=max(1, int(project.chapter_count or 12)),
        description="现有官方大纲，后续剧情卡和剧情线会优先从这里派生。",
        items=[
            StoryEngineItem(
                id=outline.id,
                title=outline.title,
                subtitle=f"序号 {outline.order_index if outline.order_index is not None else '-'}",
                summary=_compact_text(outline.content or outline.structure, 180),
            )
            for outline in outline_rows
        ],
    )
    _append_section(
        sections,
        key="chapters",
        title="章节正文",
        total=content_chapter_count,
        target=max(1, chapter_count),
        description="已有正文是剧情状态、伏笔和一致性审计的事实来源。",
        items=[
            StoryEngineItem(
                id=chapter.id,
                title=f"第{chapter.chapter_number}章：{chapter.title}",
                subtitle=f"{chapter.word_count or 0}字 · {chapter.status}",
                summary=_compact_text(chapter.summary or chapter.content, 180),
            )
            for chapter in chapter_rows
        ],
    )
    _append_section(
        sections,
        key="characters",
        title="角色卡",
        total=character_count,
        target=max(3, int(project.character_count or 5)),
        description="角色动机、状态和关系网的基础资料。",
        items=[
            StoryEngineItem(
                id=character.id,
                title=character.name,
                subtitle=character.role_type or "角色",
                summary=_compact_text(character.personality or character.background or character.current_state, 180),
                tags=[tag for tag in [character.status, character.gender] if tag],
            )
            for character in character_rows
        ],
    )
    _append_section(
        sections,
        key="organizations",
        title="组织势力",
        total=organization_count,
        target=3,
        description="阵营、组织、势力结构，可承接冲突与长期剧情线。",
        items=[
            StoryEngineItem(
                id=organization.id,
                title=organization.name,
                subtitle=organization.organization_type or "组织",
                summary=_compact_text(
                    organization.organization_purpose
                    or organization.personality
                    or organization.background,
                    180,
                ),
                tags=[tag for tag in [organization.status] if tag],
            )
            for organization in organization_rows
        ],
    )
    _append_section(
        sections,
        key="systems",
        title="职业/力量体系",
        total=career_count,
        target=2,
        description="能力成长、规则限制、阶段 progression 的结构化来源。",
        items=[
            StoryEngineItem(
                id=career.id,
                title=career.name,
                subtitle=f"{career.type} · {career.category or '未分类'}",
                summary=_compact_text(career.description or career.special_abilities or career.worldview_rules, 180),
            )
            for career in career_rows
        ],
    )
    _append_section(
        sections,
        key="foreshadows",
        title="伏笔与回收",
        total=foreshadow_count,
        target=3,
        description="长线悬念、回收提醒和章节生成时的约束来源。",
        items=[
            StoryEngineItem(
                id=foreshadow.id,
                title=foreshadow.title,
                subtitle=f"{foreshadow.status} · 强度{foreshadow.strength or 0}",
                summary=_compact_text(foreshadow.content, 180),
                tags=[tag for tag in [foreshadow.category, "长线" if foreshadow.is_long_term else None] if tag],
            )
            for foreshadow in foreshadow_rows
        ],
    )

    metrics = [
        StoryEngineMetric(
            key="outlines",
            label="大纲",
            value=outline_count,
            status=_metric_status(outline_count),
            description="现有大纲条目",
        ),
        StoryEngineMetric(
            key="chapters",
            label="正文章节",
            value=content_chapter_count,
            total=chapter_count,
            status=_metric_status(content_chapter_count),
            description="已有正文 / 总章节",
        ),
        StoryEngineMetric(
            key="characters",
            label="角色",
            value=character_count,
            status=_metric_status(character_count, warning_min=3),
            description="非组织角色卡",
        ),
        StoryEngineMetric(
            key="organizations",
            label="组织",
            value=organization_count,
            status=_metric_status(organization_count),
            description="组织/势力卡",
        ),
        StoryEngineMetric(
            key="relationships",
            label="关系",
            value=relationship_count,
            status=_metric_status(relationship_count),
            description="角色关系记录",
        ),
        StoryEngineMetric(
            key="systems",
            label="职业体系",
            value=career_count,
            status=_metric_status(career_count),
            description="职业/力量体系条目",
        ),
        StoryEngineMetric(
            key="analysis",
            label="已分析章节",
            value=analysis_count,
            total=content_chapter_count,
            status="ok" if content_chapter_count and analysis_count >= content_chapter_count else _metric_status(analysis_count),
            description="剧情分析覆盖",
        ),
        StoryEngineMetric(
            key="memories",
            label="长期记忆",
            value=memory_count,
            status=_metric_status(memory_count),
            description="向量化故事记忆",
        ),
    ]

    section_scores = [section.coverage for section in sections]
    readiness_score = int(round(sum(section_scores) / len(section_scores))) if section_scores else 0

    story_context = await build_project_story_context(
        db,
        project_id,
        max_chars=max(2000, min(context_limit, 24000)),
        outline_limit=80,
        chapter_limit=80,
    )
    context_text = _build_context_text(
        project,
        story_context,
        character_rows,
        organization_rows,
        career_rows,
        foreshadow_rows,
    )
    if len(context_text) > context_limit:
        suffix = "..."
        context_text = f"{context_text[:max(0, context_limit - len(suffix))].rstrip()}{suffix}"

    return StoryEngineSnapshotResponse(
        project_id=project_id,
        title=project.title,
        generated_at=datetime.now(timezone.utc).isoformat(),
        readiness_score=readiness_score,
        metrics=metrics,
        sections=sections,
        recommendations=_recommendations(
            project=project,
            outline_count=outline_count,
            chapter_count=chapter_count,
            content_chapter_count=content_chapter_count,
            character_count=character_count,
            organization_count=organization_count,
            relationship_count=relationship_count,
            career_count=career_count,
            foreshadow_count=foreshadow_count,
            analysis_count=analysis_count,
        ),
        context_text=context_text,
    )
