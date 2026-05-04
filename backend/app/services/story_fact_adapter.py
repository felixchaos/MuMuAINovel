"""Read-only normalized story facts derived from existing project tables.

The adapter intentionally does not introduce new persistence. It gives story
engineering features a stable fact-shaped view while keeping the upstream data
model intact.
"""
from __future__ import annotations

from collections import Counter
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.character import Character
from app.models.chapter import Chapter
from app.models.foreshadow import Foreshadow
from app.models.memory import PlotAnalysis, StoryMemory
from app.models.relationship import CharacterRelationship, Organization, OrganizationMember
from app.schemas.story_engine import StoryEngineFact, StoryEngineFactsResponse


def _compact_text(text: Optional[str], max_len: int = 240) -> str:
    cleaned = " ".join((text or "").split())
    if len(cleaned) <= max_len:
        return cleaned
    return f"{cleaned[:max_len].rstrip()}..."


def _as_list(value: Any) -> list[Any]:
    if not value:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, dict):
        return [value]
    return [value]


def _string_list(value: Any) -> list[str]:
    result: list[str] = []
    for item in _as_list(value):
        text = str(item).strip()
        if text and text not in result:
            result.append(text)
    return result


def _json_text(item: Any, *keys: str, max_len: int = 260) -> str:
    if isinstance(item, dict):
        for key in keys:
            value = item.get(key)
            if value:
                return _compact_text(str(value), max_len)
        return ""
    return _compact_text(str(item), max_len) if item is not None else ""


def _json_number(item: Any, key: str, default: float = 0.5) -> float:
    if not isinstance(item, dict):
        return default
    try:
        return float(item.get(key, default) or default)
    except (TypeError, ValueError):
        return default


def _created_at(value: Any) -> Optional[str]:
    return value.isoformat() if value else None


def _entity_names(values: Any, character_names: dict[str, str]) -> list[str]:
    names: list[str] = []
    for value in _as_list(values):
        text = str(value).strip()
        if not text:
            continue
        text = character_names.get(text, text)
        if text not in names:
            names.append(text)
    return names


class StoryFactAdapter:
    """Project facts projected from official-compatible tables."""

    async def build_facts(
        self,
        db: AsyncSession,
        project_id: str,
        *,
        fact_type: Optional[str] = None,
        limit: int = 300,
    ) -> StoryEngineFactsResponse:
        chapters = (
            await db.execute(
                select(Chapter)
                .where(Chapter.project_id == project_id)
                .order_by(Chapter.chapter_number.asc(), Chapter.created_at.asc())
            )
        ).scalars().all()
        chapter_by_id = {chapter.id: chapter for chapter in chapters}

        characters = (
            await db.execute(
                select(Character)
                .where(Character.project_id == project_id)
                .order_by(Character.created_at.asc())
            )
        ).scalars().all()
        character_names = {character.id: character.name for character in characters}

        analyses = (
            await db.execute(
                select(PlotAnalysis)
                .join(Chapter, PlotAnalysis.chapter_id == Chapter.id)
                .where(PlotAnalysis.project_id == project_id)
                .order_by(Chapter.chapter_number.asc(), PlotAnalysis.created_at.asc())
            )
        ).scalars().all()
        memories = (
            await db.execute(
                select(StoryMemory)
                .where(StoryMemory.project_id == project_id)
                .order_by(StoryMemory.story_timeline.asc(), StoryMemory.importance_score.desc())
            )
        ).scalars().all()
        foreshadows = (
            await db.execute(
                select(Foreshadow)
                .where(Foreshadow.project_id == project_id)
                .order_by(Foreshadow.plant_chapter_number.asc(), Foreshadow.importance.desc())
            )
        ).scalars().all()
        relationships = (
            await db.execute(
                select(CharacterRelationship)
                .where(CharacterRelationship.project_id == project_id)
                .order_by(CharacterRelationship.created_at.asc())
            )
        ).scalars().all()
        organizations = (
            await db.execute(
                select(Organization)
                .where(Organization.project_id == project_id)
                .order_by(Organization.created_at.asc())
            )
        ).scalars().all()
        org_by_id = {organization.id: organization for organization in organizations}
        org_ids = list(org_by_id)
        organization_members = []
        if org_ids:
            organization_members = (
                await db.execute(
                    select(OrganizationMember)
                    .where(OrganizationMember.organization_id.in_(org_ids))
                    .order_by(OrganizationMember.created_at.asc())
                )
            ).scalars().all()

        facts: list[StoryEngineFact] = []
        self._add_analysis_facts(facts, analyses, chapter_by_id)
        self._add_memory_facts(facts, memories, chapter_by_id, character_names)
        self._add_foreshadow_facts(facts, foreshadows)
        self._add_relationship_facts(facts, relationships, character_names)
        self._add_organization_member_facts(facts, organization_members, org_by_id, character_names)

        if fact_type:
            facts = [fact for fact in facts if fact.fact_type == fact_type]

        facts.sort(key=lambda fact: (
            fact.chapter_number is None,
            fact.chapter_number or 999999,
            fact.source_type,
            fact.id,
        ))
        counts = Counter(fact.fact_type for fact in facts)

        return StoryEngineFactsResponse(
            project_id=project_id,
            total=len(facts),
            counts_by_type=dict(counts),
            facts=facts[:limit],
        )

    def _add_analysis_facts(
        self,
        facts: list[StoryEngineFact],
        analyses: list[PlotAnalysis],
        chapter_by_id: dict[str, Chapter],
    ) -> None:
        for analysis in analyses:
            chapter = chapter_by_id.get(analysis.chapter_id)
            chapter_number = chapter.chapter_number if chapter else None
            chapter_title = chapter.title if chapter else "未知章节"

            for index, plot_point in enumerate(_as_list(analysis.plot_points)):
                content = _json_text(plot_point, "content", "description")
                if not content:
                    continue
                fact_type = str(plot_point.get("type", "情节点")) if isinstance(plot_point, dict) else "情节点"
                facts.append(
                    StoryEngineFact(
                        id=f"analysis:{analysis.id}:plot:{index}",
                        fact_type="event",
                        source_type="plot_analysis",
                        source_id=analysis.id,
                        chapter_id=analysis.chapter_id,
                        chapter_number=chapter_number,
                        title=f"第{chapter_number or '-'}章情节点",
                        content=f"{content}。影响: {_json_text(plot_point, 'impact')}",
                        entities=[],
                        tags=["情节点", fact_type],
                        importance=max(0.0, min(_json_number(plot_point, "importance", 0.6), 1.0)),
                        evidence=_json_text(plot_point, "keyword", max_len=80) or chapter_title,
                        created_at=_created_at(analysis.created_at),
                    )
                )

            for index, char_state in enumerate(_as_list(analysis.character_states)):
                char_name = _json_text(char_state, "character_name", max_len=80) or "未知角色"
                content_parts = [
                    _json_text(char_state, "key_event"),
                    f"{_json_text(char_state, 'state_before')} -> {_json_text(char_state, 'state_after')}",
                    _json_text(char_state, "psychological_change"),
                ]
                content = "；".join(part for part in content_parts if part and part != " -> ")
                if content:
                    facts.append(
                        StoryEngineFact(
                            id=f"analysis:{analysis.id}:character:{index}",
                            fact_type="character_state",
                            source_type="plot_analysis",
                            source_id=analysis.id,
                            chapter_id=analysis.chapter_id,
                            chapter_number=chapter_number,
                            title=f"{char_name}状态变化",
                            content=content,
                            entities=[char_name],
                            tags=["角色", "状态变化"],
                            importance=0.7,
                            confidence=0.78,
                            evidence=_json_text(char_state, "key_event", max_len=100) or chapter_title,
                            created_at=_created_at(analysis.created_at),
                        )
                    )

                if isinstance(char_state, dict):
                    relationship_changes = char_state.get("relationship_changes") or {}
                    if isinstance(relationship_changes, dict):
                        for target_name, change in relationship_changes.items():
                            facts.append(
                                StoryEngineFact(
                                    id=f"analysis:{analysis.id}:rel:{index}:{target_name}",
                                    fact_type="relationship",
                                    source_type="plot_analysis",
                                    source_id=analysis.id,
                                    chapter_id=analysis.chapter_id,
                                    chapter_number=chapter_number,
                                    title=f"{char_name} 与 {target_name}",
                                    content=_compact_text(str(change), 220),
                                    entities=[char_name, str(target_name)],
                                    tags=["关系", "变化"],
                                    importance=0.65,
                                    confidence=0.72,
                                    evidence=chapter_title,
                                    created_at=_created_at(analysis.created_at),
                                )
                            )

            for index, scene in enumerate(_as_list(analysis.scenes)):
                location = _json_text(scene, "location", max_len=80)
                atmosphere = _json_text(scene, "atmosphere", max_len=120)
                duration = _json_text(scene, "duration", max_len=80)
                content = "；".join(part for part in [location, atmosphere, duration] if part)
                if not content:
                    continue
                facts.append(
                    StoryEngineFact(
                        id=f"analysis:{analysis.id}:scene:{index}",
                        fact_type="scene",
                        source_type="plot_analysis",
                        source_id=analysis.id,
                        chapter_id=analysis.chapter_id,
                        chapter_number=chapter_number,
                        title=f"场景 - {location or chapter_title}",
                        content=content,
                        locations=[location] if location else [],
                        tags=["场景", atmosphere] if atmosphere else ["场景"],
                        importance=0.55,
                        confidence=0.72,
                        evidence=chapter_title,
                        created_at=_created_at(analysis.created_at),
                    )
                )

            for index, foreshadow in enumerate(_as_list(analysis.foreshadows)):
                content = _json_text(foreshadow, "content")
                if not content:
                    continue
                facts.append(
                    StoryEngineFact(
                        id=f"analysis:{analysis.id}:foreshadow:{index}",
                        fact_type="foreshadow",
                        source_type="plot_analysis",
                        source_id=analysis.id,
                        chapter_id=analysis.chapter_id,
                        chapter_number=chapter_number,
                        title=f"伏笔 - {_json_text(foreshadow, 'type', max_len=40) or 'planted'}",
                        content=content,
                        entities=_string_list(foreshadow.get("related_characters")) if isinstance(foreshadow, dict) else [],
                        tags=[tag for tag in ["伏笔", _json_text(foreshadow, "type", max_len=40)] if tag],
                        importance=max(0.0, min(_json_number(foreshadow, "strength", 5) / 10, 1.0)),
                        evidence=_json_text(foreshadow, "keyword", max_len=100) or chapter_title,
                        created_at=_created_at(analysis.created_at),
                    )
                )

    def _add_memory_facts(
        self,
        facts: list[StoryEngineFact],
        memories: list[StoryMemory],
        chapter_by_id: dict[str, Chapter],
        character_names: dict[str, str],
    ) -> None:
        type_map = {
            "plot_point": "event",
            "character_event": "character_state",
            "foreshadow": "foreshadow",
            "scene": "scene",
            "world_detail": "world_detail",
            "organization_event": "organization_event",
            "hook": "hook",
            "chapter_summary": "chapter_summary",
            "dialogue": "event",
        }
        for memory in memories:
            chapter = chapter_by_id.get(memory.chapter_id or "")
            fact_kind = type_map.get(memory.memory_type, "event")
            facts.append(
                StoryEngineFact(
                    id=f"memory:{memory.id}",
                    fact_type=fact_kind,
                    source_type="story_memory",
                    source_id=memory.id,
                    chapter_id=memory.chapter_id,
                    chapter_number=chapter.chapter_number if chapter else memory.story_timeline,
                    title=memory.title or memory.memory_type,
                    content=_compact_text(memory.content, 360),
                    entities=_entity_names(memory.related_characters, character_names),
                    locations=_string_list(memory.related_locations),
                    tags=_string_list(memory.tags),
                    importance=max(0.0, min(float(memory.importance_score or 0.5), 1.0)),
                    confidence=0.8,
                    evidence=chapter.title if chapter else None,
                    created_at=_created_at(memory.created_at),
                )
            )

    def _add_foreshadow_facts(
        self,
        facts: list[StoryEngineFact],
        foreshadows: list[Foreshadow],
    ) -> None:
        for foreshadow in foreshadows:
            facts.append(
                StoryEngineFact(
                    id=f"foreshadow:{foreshadow.id}",
                    fact_type="foreshadow",
                    source_type="foreshadow",
                    source_id=foreshadow.id,
                    chapter_id=foreshadow.plant_chapter_id,
                    chapter_number=foreshadow.plant_chapter_number,
                    title=foreshadow.title,
                    content=_compact_text(foreshadow.content, 360),
                    entities=_string_list(foreshadow.related_characters),
                    tags=_string_list(foreshadow.tags) + [tag for tag in [foreshadow.status, foreshadow.category] if tag],
                    importance=max(0.0, min(float(foreshadow.importance or 0.5), 1.0)),
                    confidence=0.86,
                    evidence=_compact_text(foreshadow.hint_text or foreshadow.resolution_text, 120) or None,
                    created_at=_created_at(foreshadow.created_at),
                )
            )

    def _add_relationship_facts(
        self,
        facts: list[StoryEngineFact],
        relationships: list[CharacterRelationship],
        character_names: dict[str, str],
    ) -> None:
        for relationship in relationships:
            from_name = character_names.get(relationship.character_from_id, relationship.character_from_id)
            to_name = character_names.get(relationship.character_to_id, relationship.character_to_id)
            relationship_name = relationship.relationship_name or "关系"
            facts.append(
                StoryEngineFact(
                    id=f"relationship:{relationship.id}",
                    fact_type="relationship",
                    source_type="relationship",
                    source_id=relationship.id,
                    title=f"{from_name} - {relationship_name} - {to_name}",
                    content=_compact_text(relationship.description or relationship_name, 260),
                    entities=[from_name, to_name],
                    tags=["关系", relationship.status or "active", relationship.source or "unknown"],
                    importance=max(0.0, min(abs(int(relationship.intimacy_level or 0)) / 100, 1.0)),
                    confidence=0.82,
                    created_at=_created_at(relationship.created_at),
                )
            )

    def _add_organization_member_facts(
        self,
        facts: list[StoryEngineFact],
        organization_members: list[OrganizationMember],
        organizations: dict[str, Organization],
        character_names: dict[str, str],
    ) -> None:
        for member in organization_members:
            organization = organizations.get(member.organization_id)
            org_name = character_names.get(organization.character_id, member.organization_id) if organization else member.organization_id
            char_name = character_names.get(member.character_id, member.character_id)
            facts.append(
                StoryEngineFact(
                    id=f"organization-member:{member.id}",
                    fact_type="organization_event",
                    source_type="organization_member",
                    source_id=member.id,
                    title=f"{char_name}加入/隶属{org_name}",
                    content=_compact_text(
                        member.notes
                        or f"{char_name}在{org_name}担任{member.position}，状态为{member.status}",
                        260,
                    ),
                    entities=[char_name, org_name],
                    tags=[
                        tag
                        for tag in ["组织", member.position, member.status or "active", member.source or "unknown"]
                        if tag
                    ],
                    importance=max(0.0, min(float(member.contribution or member.loyalty or 50) / 100, 1.0)),
                    confidence=0.82,
                    created_at=_created_at(member.created_at),
                )
            )


story_fact_adapter = StoryFactAdapter()
