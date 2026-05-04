"""Story engineering snapshot schemas."""
from typing import List, Optional
from pydantic import BaseModel, Field


class StoryEngineMetric(BaseModel):
    """A compact metric for the story-engine dashboard."""
    key: str
    label: str
    value: int
    total: Optional[int] = None
    status: str = Field("neutral", description="ok/warning/empty/neutral")
    description: Optional[str] = None


class StoryEngineItem(BaseModel):
    """A preview item from an existing project resource."""
    id: str
    title: str
    subtitle: Optional[str] = None
    summary: Optional[str] = None
    tags: List[str] = Field(default_factory=list)


class StoryEngineSection(BaseModel):
    """A grouped section in the story-engine snapshot."""
    key: str
    title: str
    description: Optional[str] = None
    status: str = Field("neutral", description="ok/warning/empty/neutral")
    total: int = 0
    coverage: int = Field(0, ge=0, le=100)
    items: List[StoryEngineItem] = Field(default_factory=list)


class StoryEngineRecommendation(BaseModel):
    """Next-step recommendation derived from the current project state."""
    key: str
    title: str
    detail: str
    priority: str = Field("medium", description="high/medium/low")
    source: str = "system"


class StoryEngineLane(BaseModel):
    """A derived story line built from official-compatible project data."""
    key: str
    title: str
    lane_type: str = Field("plot", description="plot/character/faction/promise/continuity")
    status: str = Field("neutral", description="ok/warning/empty/neutral")
    progress: int = Field(0, ge=0, le=100)
    summary: str
    items: List[StoryEngineItem] = Field(default_factory=list)
    tags: List[str] = Field(default_factory=list)


class StoryEngineBeat(BaseModel):
    """A lightweight timeline beat derived from outlines, chapters, and analysis."""
    id: str
    title: str
    beat_type: str = Field("chapter", description="outline/chapter/analysis")
    chapter_number: Optional[int] = None
    progress: int = Field(0, ge=0, le=100)
    status: str = Field("neutral", description="ok/warning/empty/neutral")
    stage: Optional[str] = None
    conflict_level: Optional[int] = None
    emotional_tone: Optional[str] = None
    summary: Optional[str] = None
    tags: List[str] = Field(default_factory=list)


class StoryEngineCardDraft(BaseModel):
    """A ddys-style plot-card draft derived without creating fork-only tables."""
    id: str
    title: str
    card_type: str = Field("plot", description="plot/character/scene/conflict/hook/promise")
    source: str = Field("outline", description="outline/chapter/analysis")
    source_title: Optional[str] = None
    chapter_number: Optional[int] = None
    content: str
    tags: List[str] = Field(default_factory=list)


class StoryEngineFact(BaseModel):
    """A normalized read-only fact derived from existing official-compatible tables."""
    id: str
    fact_type: str = Field(..., description="event/character_state/relationship/scene/world_detail/foreshadow/organization_event")
    source_type: str = Field(..., description="plot_analysis/story_memory/foreshadow/relationship/organization_member")
    source_id: str
    chapter_id: Optional[str] = None
    chapter_number: Optional[int] = None
    title: str
    content: str
    entities: List[str] = Field(default_factory=list)
    locations: List[str] = Field(default_factory=list)
    tags: List[str] = Field(default_factory=list)
    importance: float = Field(0.5, ge=0.0, le=1.0)
    confidence: float = Field(0.75, ge=0.0, le=1.0)
    evidence: Optional[str] = None
    created_at: Optional[str] = None


class StoryEngineFactsResponse(BaseModel):
    """Read-only fact view over existing project records."""
    project_id: str
    total: int
    counts_by_type: dict[str, int]
    facts: List[StoryEngineFact] = Field(default_factory=list)


class StoryEngineMatrixCell(BaseModel):
    """Character/entity appearance in a chapter."""
    chapter_number: int
    count: int = 1
    evidence: Optional[str] = None


class StoryEngineMatrixRow(BaseModel):
    """Character/entity appearance matrix row."""
    entity: str
    total: int
    chapters: List[StoryEngineMatrixCell] = Field(default_factory=list)


class StoryEngineTimelineItem(BaseModel):
    """Timeline item derived from normalized facts."""
    id: str
    timeline_type: str = Field(..., description="relationship/foreshadow/organization/world/fact")
    chapter_number: Optional[int] = None
    title: str
    content: str
    entities: List[str] = Field(default_factory=list)
    tags: List[str] = Field(default_factory=list)
    importance: float = Field(0.5, ge=0.0, le=1.0)
    source_type: str


class StoryEngineVisualizationResponse(BaseModel):
    """Read-only visualization data derived from existing facts."""
    project_id: str
    character_chapter_matrix: List[StoryEngineMatrixRow] = Field(default_factory=list)
    relationship_timeline: List[StoryEngineTimelineItem] = Field(default_factory=list)
    foreshadow_timeline: List[StoryEngineTimelineItem] = Field(default_factory=list)
    organization_timeline: List[StoryEngineTimelineItem] = Field(default_factory=list)
    world_timeline: List[StoryEngineTimelineItem] = Field(default_factory=list)


class StoryEngineSnapshotResponse(BaseModel):
    """Read-only story-engine snapshot built from official-compatible data."""
    project_id: str
    title: str
    generated_at: str
    readiness_score: int = Field(0, ge=0, le=100)
    metrics: List[StoryEngineMetric]
    sections: List[StoryEngineSection]
    lanes: List[StoryEngineLane] = Field(default_factory=list)
    beats: List[StoryEngineBeat] = Field(default_factory=list)
    cards: List[StoryEngineCardDraft] = Field(default_factory=list)
    recommendations: List[StoryEngineRecommendation]
    context_text: str
