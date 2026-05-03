"""Story engineering read-only APIs."""
from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.common import verify_project_access_from_request
from app.database import get_db
from app.schemas.story_engine import StoryEngineSnapshotResponse
from app.services.story_engine_service import build_story_engine_snapshot

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
