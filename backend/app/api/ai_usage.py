"""AI Token 用量统计 API"""
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.ai_usage import AIUsageLog
from app.schemas.ai_usage import (
    AIUsageLogResponse,
    AIUsageModelSummary,
    AIUsageSummaryResponse,
)
from app.services.openrouter_pricing_service import openrouter_pricing_service

router = APIRouter(prefix="/ai-usage", tags=["AI用量统计"])


def _require_user_id(request: Request) -> str:
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(status_code=401, detail="未登录")
    return user_id


def _to_log_response(log: AIUsageLog) -> AIUsageLogResponse:
    return AIUsageLogResponse(
        id=log.id,
        request_mode=log.request_mode,
        provider=log.provider,
        model=log.model,
        api_base_url=log.api_base_url,
        prompt_tokens=log.prompt_tokens or 0,
        completion_tokens=log.completion_tokens or 0,
        total_tokens=log.total_tokens or 0,
        stream=bool(log.stream),
        auto_mcp=bool(log.auto_mcp),
        tools_count=log.tools_count or 0,
        tool_calls_count=log.tool_calls_count or 0,
        retry_count=log.retry_count or 0,
        success=bool(log.success),
        duration_ms=log.duration_ms,
        finish_reason=log.finish_reason,
        error_type=log.error_type,
        error_message=log.error_message,
        reference_prompt_price=log.reference_prompt_price,
        reference_completion_price=log.reference_completion_price,
        reference_estimated_cost=log.reference_estimated_cost,
        reference_currency=log.reference_currency or "USD",
        pricing_source=log.pricing_source or "openrouter",
        pricing_updated_at=log.pricing_updated_at,
        created_at=log.created_at,
    )


@router.get("/summary", response_model=AIUsageSummaryResponse, summary="获取当前用户 AI 用量汇总")
async def get_ai_usage_summary(
    request: Request,
    days: int = Query(30, ge=1, le=365, description="统计最近多少天"),
    db: AsyncSession = Depends(get_db),
):
    user_id = _require_user_id(request)
    since = datetime.utcnow() - timedelta(days=days)

    totals_result = await db.execute(
        select(
            func.count(AIUsageLog.id),
            func.sum(case((AIUsageLog.success.is_(True), 1), else_=0)),
            func.coalesce(func.sum(AIUsageLog.prompt_tokens), 0),
            func.coalesce(func.sum(AIUsageLog.completion_tokens), 0),
            func.coalesce(func.sum(AIUsageLog.total_tokens), 0),
            func.sum(AIUsageLog.reference_estimated_cost),
        ).where(
            AIUsageLog.user_id == user_id,
            AIUsageLog.created_at >= since,
        )
    )
    totals = totals_result.one()

    model_rows = await db.execute(
        select(
            AIUsageLog.provider,
            AIUsageLog.model,
            AIUsageLog.api_base_url,
            AIUsageLog.request_mode,
            func.count(AIUsageLog.id).label("calls"),
            func.sum(case((AIUsageLog.success.is_(True), 1), else_=0)).label("success_calls"),
            func.coalesce(func.sum(AIUsageLog.prompt_tokens), 0).label("prompt_tokens"),
            func.coalesce(func.sum(AIUsageLog.completion_tokens), 0).label("completion_tokens"),
            func.coalesce(func.sum(AIUsageLog.total_tokens), 0).label("total_tokens"),
            func.sum(AIUsageLog.reference_estimated_cost).label("reference_estimated_cost"),
        )
        .where(
            AIUsageLog.user_id == user_id,
            AIUsageLog.created_at >= since,
        )
        .group_by(AIUsageLog.provider, AIUsageLog.model, AIUsageLog.api_base_url, AIUsageLog.request_mode)
        .order_by(func.coalesce(func.sum(AIUsageLog.total_tokens), 0).desc())
    )

    recent_rows = await db.execute(
        select(AIUsageLog)
        .where(
            AIUsageLog.user_id == user_id,
            AIUsageLog.created_at >= since,
        )
        .order_by(AIUsageLog.created_at.desc())
        .limit(20)
    )

    return AIUsageSummaryResponse(
        days=days,
        total_calls=totals[0] or 0,
        success_calls=totals[1] or 0,
        prompt_tokens=totals[2] or 0,
        completion_tokens=totals[3] or 0,
        total_tokens=totals[4] or 0,
        reference_estimated_cost=totals[5],
        pricing_cache_updated_at=openrouter_pricing_service.updated_at,
        pricing_cache_ttl_hours=openrouter_pricing_service.ttl_hours,
        by_model=[
            AIUsageModelSummary(
                provider=row.provider,
                model=row.model,
                api_base_url=row.api_base_url,
                request_mode=row.request_mode,
                calls=row.calls or 0,
                success_calls=row.success_calls or 0,
                prompt_tokens=row.prompt_tokens or 0,
                completion_tokens=row.completion_tokens or 0,
                total_tokens=row.total_tokens or 0,
                reference_estimated_cost=row.reference_estimated_cost,
            )
            for row in model_rows
        ],
        recent_logs=[_to_log_response(log) for log in recent_rows.scalars().all()],
    )


@router.get("/logs", response_model=list[AIUsageLogResponse], summary="获取当前用户 AI 用量明细")
async def get_ai_usage_logs(
    request: Request,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    success: Optional[bool] = Query(None, description="按成功/失败过滤"),
    db: AsyncSession = Depends(get_db),
):
    user_id = _require_user_id(request)
    query = select(AIUsageLog).where(AIUsageLog.user_id == user_id)
    if success is not None:
        query = query.where(AIUsageLog.success == success)
    result = await db.execute(
        query.order_by(AIUsageLog.created_at.desc()).offset(offset).limit(limit)
    )
    return [_to_log_response(log) for log in result.scalars().all()]


@router.post("/pricing/refresh", summary="刷新 OpenRouter 参考价格缓存")
async def refresh_openrouter_pricing(request: Request):
    _require_user_id(request)
    count = await openrouter_pricing_service.refresh()
    return {
        "message": "OpenRouter服务器参考价格缓存已刷新",
        "count": count,
        "updated_at": datetime.utcnow().isoformat(),
    }
