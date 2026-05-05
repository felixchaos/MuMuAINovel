"""Read-only story timeline schemas."""
from typing import List, Optional

from pydantic import BaseModel, Field


class StoryTimelineEvent(BaseModel):
    id: str
    event_type: str = Field(..., description="plot/character/scene/world/foreshadow/organization/hook/dialogue/other")
    label: str
    title: str
    content: str
    chapter_id: Optional[str] = None
    chapter_number: Optional[int] = None
    source_type: str
    source_id: str
    importance: float = Field(0.5, ge=0.0, le=1.0)
    tags: List[str] = Field(default_factory=list)
    entities: List[str] = Field(default_factory=list)
    locations: List[str] = Field(default_factory=list)
    status: Optional[str] = None
    position: Optional[int] = None
    created_at: Optional[str] = None


class StoryTimelineChapter(BaseModel):
    id: str
    chapter_number: int
    title: str
    status: str = "draft"
    word_count: int = 0
    summary: Optional[str] = None
    has_analysis: bool = False
    plot_stage: Optional[str] = None
    conflict_level: Optional[int] = None
    emotional_tone: Optional[str] = None
    coherence_score: Optional[float] = None
    events: List[StoryTimelineEvent] = Field(default_factory=list)


class StoryTimelineResponse(BaseModel):
    project_id: str
    total_chapters: int
    analyzed_chapters: int
    total_events: int
    event_counts: dict[str, int]
    chapters: List[StoryTimelineChapter] = Field(default_factory=list)
    unplaced_events: List[StoryTimelineEvent] = Field(default_factory=list)
