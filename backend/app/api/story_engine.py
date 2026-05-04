"""Story engineering read-only APIs."""
from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.common import verify_project_access_from_request
from app.database import get_db
from app.schemas.story_engine import (
    StoryEngineFactsResponse,
    StoryEngineSnapshotResponse,
    StoryEngineVisualizationResponse,
)
from app.services.story_fact_adapter import story_fact_adapter
from app.services.story_engine_service import build_story_engine_snapshot, build_story_engine_visualization

router = APIRouter(prefix="/projects/{project_id}/story-engine", tags=["剧情工程"])


@router.get("/snapshot", response_model=StoryEngineSnapshotResponse)
async def get_story_engine_snapshot(
    project_id: str,
    request: Request,
    context_limit: int = Query(12000, ge=2000, le=24000, description="返回上下文文本的最大字符数"),
    db: AsyncSession = Depends(get_db),
):
    """Return an official-compatible story-engine snapshot for the project."""
    project = await verify_project_access_from_request(project_id, request, db)
    return await build_story_engine_snapshot(db, project, context_limit=context_limit)


@router.get("/facts", response_model=StoryEngineFactsResponse)
async def get_story_engine_facts(
    project_id: str,
    request: Request,
    fact_type: str | None = Query(None, description="可选事实类型过滤"),
    limit: int = Query(300, ge=1, le=1000, description="返回事实数量上限"),
    db: AsyncSession = Depends(get_db),
):
    """Return normalized read-only facts derived from existing project records."""
    await verify_project_access_from_request(project_id, request, db)
    return await story_fact_adapter.build_facts(db, project_id, fact_type=fact_type, limit=limit)


@router.get("/visualization", response_model=StoryEngineVisualizationResponse)
async def get_story_engine_visualization(
    project_id: str,
    request: Request,
    limit: int = Query(1000, ge=50, le=3000, description="参与可视化聚合的事实数量上限"),
    db: AsyncSession = Depends(get_db),
):
    """Return matrix/timeline data derived from existing fact views."""
    await verify_project_access_from_request(project_id, request, db)
    return await build_story_engine_visualization(db, project_id, limit=limit)
