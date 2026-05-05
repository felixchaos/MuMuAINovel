"""Build a compact read-only story timeline from existing project records."""
from __future__ import annotations

from collections import Counter
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.character import Character
from app.models.chapter import Chapter
from app.models.foreshadow import Foreshadow
from app.models.memory import PlotAnalysis, StoryMemory
from app.schemas.story_timeline import StoryTimelineChapter, StoryTimelineEvent, StoryTimelineResponse
from app.services.name_authority_service import NameAuthority, build_name_authority


MEMORY_TYPE_MAP: dict[str, tuple[str, str]] = {
    "plot_point": ("plot", "情节"),
    "character_event": ("character", "角色"),
    "scene": ("scene", "场景"),
    "world_detail": ("world", "世界观"),
    "foreshadow": ("foreshadow", "伏笔"),
    "hook": ("hook", "钩子"),
    "organization_event": ("organization", "组织"),
    "dialogue": ("dialogue", "对话"),
    "chapter_summary": ("plot", "章节摘要"),
}


def _compact_text(text: Optional[str], max_len: int = 360) -> str:
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


def _resolve_entities(values: Any, name_authority: NameAuthority) -> list[str]:
    return name_authority.resolve_names(_as_list(values), keep_unknown=True)


def _event_matches(
    event: StoryTimelineEvent,
    *,
    event_types: set[str],
    search_text: str,
    min_importance: float,
) -> bool:
    if event_types and event.event_type not in event_types:
        return False
    if event.importance < min_importance:
        return False
    if not search_text:
        return True
    haystack = " ".join([
        event.title,
        event.content,
        " ".join(event.tags),
        " ".join(event.entities),
        " ".join(event.locations),
    ]).lower()
    return search_text in haystack


def _sort_key(event: StoryTimelineEvent) -> tuple[int, int, float, str]:
    chapter_number = event.chapter_number or 999999
    position = event.position if event.position is not None else 999999
    return (chapter_number, position, -event.importance, event.id)


def _memory_event(
    memory: StoryMemory,
    *,
    chapter_by_id: dict[str, Chapter],
    name_authority: NameAuthority,
) -> StoryTimelineEvent:
    event_type, label = MEMORY_TYPE_MAP.get(memory.memory_type, ("other", "事实"))
    chapter = chapter_by_id.get(memory.chapter_id or "")
    return StoryTimelineEvent(
        id=f"memory:{memory.id}",
        event_type=event_type,
        label=label,
        title=memory.title or label,
        content=_compact_text(memory.content, 420),
        chapter_id=memory.chapter_id,
        chapter_number=chapter.chapter_number if chapter else memory.story_timeline,
        source_type="story_memory",
        source_id=memory.id,
        importance=max(0.0, min(float(memory.importance_score or 0.5), 1.0)),
        tags=_string_list(memory.tags),
        entities=_resolve_entities(memory.related_characters, name_authority),
        locations=_string_list(memory.related_locations),
        status="resolved" if memory.is_foreshadow == 2 else "planted" if memory.is_foreshadow == 1 else None,
        position=memory.chapter_position,
        created_at=_created_at(memory.created_at),
    )


def _foreshadow_events(foreshadow: Foreshadow, name_authority: NameAuthority) -> list[StoryTimelineEvent]:
    base = {
        "source_type": "foreshadow",
        "source_id": foreshadow.id,
        "importance": max(0.0, min(float(foreshadow.importance or 0.5), 1.0)),
        "tags": _string_list(foreshadow.tags) + [
            tag for tag in [foreshadow.category, "长线" if foreshadow.is_long_term else None] if tag
        ],
        "entities": _resolve_entities(foreshadow.related_characters, name_authority),
        "locations": [],
        "created_at": _created_at(foreshadow.created_at),
    }
    events: list[StoryTimelineEvent] = []

    if foreshadow.plant_chapter_number:
        events.append(
            StoryTimelineEvent(
                id=f"foreshadow:{foreshadow.id}:plant",
                event_type="foreshadow",
                label="伏笔",
                title=f"埋下伏笔：{foreshadow.title}",
                content=_compact_text(foreshadow.hint_text or foreshadow.content, 420),
                chapter_id=foreshadow.plant_chapter_id,
                chapter_number=foreshadow.plant_chapter_number,
                status="planted",
                **base,
            )
        )

    if foreshadow.target_resolve_chapter_number:
        events.append(
            StoryTimelineEvent(
                id=f"foreshadow:{foreshadow.id}:target",
                event_type="foreshadow",
                label="计划回收",
                title=f"计划回收：{foreshadow.title}",
                content=_compact_text(foreshadow.resolution_notes or foreshadow.content, 420),
                chapter_id=foreshadow.target_resolve_chapter_id,
                chapter_number=foreshadow.target_resolve_chapter_number,
                status="target",
                **base,
            )
        )

    if foreshadow.actual_resolve_chapter_number:
        events.append(
            StoryTimelineEvent(
                id=f"foreshadow:{foreshadow.id}:resolve",
                event_type="foreshadow",
                label="回收",
                title=f"回收伏笔：{foreshadow.title}",
                content=_compact_text(foreshadow.resolution_text or foreshadow.content, 420),
                chapter_id=foreshadow.actual_resolve_chapter_id,
                chapter_number=foreshadow.actual_resolve_chapter_number,
                status="resolved",
                created_at=_created_at(foreshadow.resolved_at or foreshadow.updated_at),
                **{key: value for key, value in base.items() if key != "created_at"},
            )
        )

    if not events:
        events.append(
            StoryTimelineEvent(
                id=f"foreshadow:{foreshadow.id}:pending",
                event_type="foreshadow",
                label="伏笔",
                title=f"未定位伏笔：{foreshadow.title}",
                content=_compact_text(foreshadow.content, 420),
                chapter_number=None,
                status=foreshadow.status,
                **base,
            )
        )

    return events


def _analysis_fallback_events(
    analysis: PlotAnalysis,
    *,
    chapter_by_id: dict[str, Chapter],
    name_authority: NameAuthority,
) -> list[StoryTimelineEvent]:
    chapter = chapter_by_id.get(analysis.chapter_id)
    chapter_number = chapter.chapter_number if chapter else None
    chapter_title = chapter.title if chapter else "未知章节"
    events: list[StoryTimelineEvent] = []

    def add_event(
        *,
        key: str,
        event_type: str,
        label: str,
        title: str,
        content: str,
        importance: float = 0.5,
        tags: list[str] | None = None,
        entities: list[str] | None = None,
        locations: list[str] | None = None,
        position: int | None = None,
    ) -> None:
        cleaned = _compact_text(content, 420)
        if not cleaned:
            return
        events.append(
            StoryTimelineEvent(
                id=f"analysis:{analysis.id}:{key}",
                event_type=event_type,
                label=label,
                title=title,
                content=cleaned,
                chapter_id=analysis.chapter_id,
                chapter_number=chapter_number,
                source_type="plot_analysis",
                source_id=analysis.id,
                importance=max(0.0, min(importance, 1.0)),
                tags=tags or [],
                entities=entities or [],
                locations=locations or [],
                position=position,
                created_at=_created_at(analysis.created_at),
            )
        )

    for index, point in enumerate(_as_list(analysis.plot_points)):
        content = _json_text(point, "content", "description")
        impact = _json_text(point, "impact", max_len=140)
        add_event(
            key=f"plot:{index}",
            event_type="plot",
            label="情节",
            title=f"情节点 - {chapter_title}",
            content=f"{content}{'。影响: ' + impact if impact else ''}",
            importance=_json_number(point, "importance", 0.65),
            tags=["情节点", _json_text(point, "type", max_len=40)],
        )

    for index, state in enumerate(_as_list(analysis.character_states)):
        if not isinstance(state, dict):
            continue
        char_name = name_authority.resolve_name(_json_text(state, "character_name", max_len=80), keep_unknown=True)
        content_parts = [
            _json_text(state, "key_event"),
            f"{_json_text(state, 'state_before')} -> {_json_text(state, 'state_after')}",
            _json_text(state, "psychological_change"),
        ]
        add_event(
            key=f"character:{index}",
            event_type="character",
            label="角色",
            title=f"{char_name or '角色'}状态变化",
            content="；".join(part for part in content_parts if part and part != " -> "),
            importance=0.7,
            tags=["角色", "状态变化"],
            entities=[char_name] if char_name else [],
        )

    for index, scene in enumerate(_as_list(analysis.scenes)):
        location = _json_text(scene, "location", max_len=80)
        atmosphere = _json_text(scene, "atmosphere", max_len=120)
        duration = _json_text(scene, "duration", max_len=80)
        add_event(
            key=f"scene:{index}",
            event_type="scene",
            label="场景",
            title=f"场景 - {location or chapter_title}",
            content="；".join(part for part in [location, atmosphere, duration] if part),
            importance=0.55,
            tags=[tag for tag in ["场景", atmosphere] if tag],
            locations=[location] if location else [],
        )

    for index, fact in enumerate(_as_list(getattr(analysis, "worldbuilding_facts", None))):
        content = _json_text(fact, "content", "description")
        category = _json_text(fact, "category", max_len=60)
        add_event(
            key=f"world:{index}",
            event_type="world",
            label="世界观",
            title=f"世界观 - {category or chapter_title}",
            content=content,
            importance=0.65,
            tags=[tag for tag in ["世界观", category] if tag],
        )

    for index, foreshadow in enumerate(_as_list(analysis.foreshadows)):
        add_event(
            key=f"foreshadow:{index}",
            event_type="foreshadow",
            label="伏笔",
            title=f"伏笔 - {_json_text(foreshadow, 'type', max_len=40) or chapter_title}",
            content=_json_text(foreshadow, "content"),
            importance=max(0.0, min(_json_number(foreshadow, "strength", 5) / 10, 1.0)),
            tags=[tag for tag in ["伏笔", _json_text(foreshadow, "type", max_len=40)] if tag],
            entities=_resolve_entities(foreshadow.get("related_characters"), name_authority) if isinstance(foreshadow, dict) else [],
        )

    return events


async def build_story_timeline(
    db: AsyncSession,
    project_id: str,
    *,
    event_types: set[str] | None = None,
    search: str | None = None,
    min_importance: float = 0.0,
    limit: int = 1000,
) -> StoryTimelineResponse:
    event_types = event_types or set()
    search_text = (search or "").strip().lower()

    chapters = (
        await db.execute(
            select(Chapter)
            .where(Chapter.project_id == project_id)
            .order_by(Chapter.chapter_number.asc(), Chapter.created_at.asc())
        )
    ).scalars().all()
    chapter_by_id = {chapter.id: chapter for chapter in chapters}
    chapter_numbers = {chapter.chapter_number for chapter in chapters}

    analyses = (
        await db.execute(
            select(PlotAnalysis)
            .join(Chapter, PlotAnalysis.chapter_id == Chapter.id)
            .where(PlotAnalysis.project_id == project_id)
            .order_by(Chapter.chapter_number.asc(), PlotAnalysis.created_at.desc())
        )
    ).scalars().all()
    analysis_by_chapter: dict[str, PlotAnalysis] = {}
    for analysis in analyses:
        analysis_by_chapter.setdefault(analysis.chapter_id, analysis)

    characters = (
        await db.execute(
            select(Character)
            .where(Character.project_id == project_id)
            .order_by(Character.created_at.asc())
        )
    ).scalars().all()
    name_authority = build_name_authority(characters)

    memories = (
        await db.execute(
            select(StoryMemory)
            .where(StoryMemory.project_id == project_id)
            .order_by(StoryMemory.story_timeline.asc(), StoryMemory.chapter_position.asc(), StoryMemory.importance_score.desc())
            .limit(max(limit * 2, 200))
        )
    ).scalars().all()

    events: list[StoryTimelineEvent] = [
        _memory_event(memory, chapter_by_id=chapter_by_id, name_authority=name_authority)
        for memory in memories
        if _compact_text(memory.content)
    ]
    memory_chapter_ids = {memory.chapter_id for memory in memories if memory.chapter_id}

    for analysis in analyses:
        if analysis.chapter_id in memory_chapter_ids:
            continue
        events.extend(
            _analysis_fallback_events(
                analysis,
                chapter_by_id=chapter_by_id,
                name_authority=name_authority,
            )
        )

    foreshadows = (
        await db.execute(
            select(Foreshadow)
            .where(Foreshadow.project_id == project_id)
            .order_by(Foreshadow.plant_chapter_number.asc(), Foreshadow.target_resolve_chapter_number.asc(), Foreshadow.importance.desc())
        )
    ).scalars().all()
    for foreshadow in foreshadows:
        events.extend(_foreshadow_events(foreshadow, name_authority))

    filtered_events = [
        event
        for event in events
        if _event_matches(
            event,
            event_types=event_types,
            search_text=search_text,
            min_importance=min_importance,
        )
    ]
    filtered_events.sort(key=_sort_key)
    filtered_events = filtered_events[:limit]

    events_by_chapter: dict[int, list[StoryTimelineEvent]] = {number: [] for number in chapter_numbers}
    unplaced_events: list[StoryTimelineEvent] = []
    for event in filtered_events:
        if event.chapter_number in events_by_chapter:
            events_by_chapter[event.chapter_number or 0].append(event)
        else:
            unplaced_events.append(event)

    timeline_chapters = [
        StoryTimelineChapter(
            id=chapter.id,
            chapter_number=chapter.chapter_number,
            title=chapter.title,
            status=chapter.status or "draft",
            word_count=chapter.word_count or 0,
            summary=_compact_text(chapter.summary or "", 260) or None,
            has_analysis=chapter.id in analysis_by_chapter,
            plot_stage=analysis_by_chapter.get(chapter.id).plot_stage if chapter.id in analysis_by_chapter else None,
            conflict_level=analysis_by_chapter.get(chapter.id).conflict_level if chapter.id in analysis_by_chapter else None,
            emotional_tone=analysis_by_chapter.get(chapter.id).emotional_tone if chapter.id in analysis_by_chapter else None,
            coherence_score=analysis_by_chapter.get(chapter.id).coherence_score if chapter.id in analysis_by_chapter else None,
            events=events_by_chapter.get(chapter.chapter_number, []),
        )
        for chapter in chapters
    ]

    counts = Counter(event.event_type for event in filtered_events)
    return StoryTimelineResponse(
        project_id=project_id,
        total_chapters=len(chapters),
        analyzed_chapters=len(analysis_by_chapter),
        total_events=len(filtered_events),
        event_counts=dict(counts),
        chapters=timeline_chapters,
        unplaced_events=unplaced_events,
    )
