"""Read-only project timeline API."""
from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.common import verify_project_access_from_request
from app.database import get_db
from app.schemas.story_timeline import StoryTimelineResponse
from app.services.story_timeline_service import build_story_timeline

router = APIRouter(prefix="/projects/{project_id}/timeline", tags=["时间线"])


@router.get("", response_model=StoryTimelineResponse)
async def get_story_timeline(
    project_id: str,
    request: Request,
    types: str | None = Query(None, description="逗号分隔的事件类型过滤"),
    search: str | None = Query(None, description="标题、内容、标签、角色和地点搜索"),
    min_importance: float = Query(0.0, ge=0.0, le=1.0, description="最低重要性"),
    limit: int = Query(1000, ge=50, le=3000, description="最多返回事件数"),
    db: AsyncSession = Depends(get_db),
):
    project = await verify_project_access_from_request(project_id, request, db)
    event_types = {
        item.strip()
        for item in (types or "").split(",")
        if item.strip()
    }
    return await build_story_timeline(
        db,
        project.id,
        event_types=event_types,
        search=search,
        min_importance=min_importance,
        limit=limit,
    )
