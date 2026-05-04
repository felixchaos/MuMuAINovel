"""AI 用量统计响应模型"""
from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, ConfigDict


class AIUsageLogResponse(BaseModel):
    id: str
    request_mode: str
    provider: str
    model: str
    api_base_url: Optional[str] = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    stream: bool = False
    auto_mcp: bool = False
    tools_count: int = 0
    tool_calls_count: int = 0
    retry_count: int = 0
    success: bool = False
    duration_ms: Optional[int] = None
    finish_reason: Optional[str] = None
    error_type: Optional[str] = None
    error_message: Optional[str] = None
    reference_prompt_price: Optional[float] = None
    reference_completion_price: Optional[float] = None
    reference_estimated_cost: Optional[float] = None
    reference_currency: str = "USD"
    pricing_source: str = "openrouter"
    pricing_updated_at: Optional[datetime] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AIUsageModelSummary(BaseModel):
    provider: str
    model: str
    api_base_url: Optional[str] = None
    request_mode: Optional[str] = None
    calls: int
    success_calls: int
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    reference_estimated_cost: Optional[float] = None


class AIUsageSummaryResponse(BaseModel):
    days: int
    total_calls: int
    success_calls: int
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    reference_estimated_cost: Optional[float] = None
    reference_currency: str = "USD"
    pricing_source: str = "openrouter"
    pricing_cache_updated_at: Optional[datetime] = None
    pricing_cache_ttl_hours: int = 24
    by_model: List[AIUsageModelSummary]
    recent_logs: List[AIUsageLogResponse]
