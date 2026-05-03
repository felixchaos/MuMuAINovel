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


class StoryEngineSnapshotResponse(BaseModel):
    """Read-only story-engine snapshot built from official-compatible data."""
    project_id: str
    title: str
    generated_at: str
    readiness_score: int = Field(0, ge=0, le=100)
    metrics: List[StoryEngineMetric]
    sections: List[StoryEngineSection]
    recommendations: List[StoryEngineRecommendation]
    context_text: str
