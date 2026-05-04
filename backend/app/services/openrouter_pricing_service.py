"""OpenRouter 模型价格缓存服务。

OpenRouter 的模型列表接口会返回模型 pricing 字段。这里仅把它用作
Token 参考价估算，不做真实计费。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, Optional

import httpx

from app.logger import get_logger

logger = get_logger(__name__)

OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"


@dataclass
class ModelPricing:
    model: str
    prompt: Optional[float]
    completion: Optional[float]
    currency: str
    updated_at: datetime


class OpenRouterPricingService:
    """轻量价格缓存，避免每次 AI 调用都访问 OpenRouter。"""

    def __init__(self, ttl: timedelta = timedelta(hours=6)):
        self.ttl = ttl
        self._prices: Dict[str, ModelPricing] = {}
        self._updated_at: Optional[datetime] = None

    def _cache_valid(self) -> bool:
        if self._updated_at is None:
            return False
        return datetime.utcnow() - self._updated_at < self.ttl

    async def refresh(self) -> int:
        """刷新模型价格缓存，返回缓存条目数。"""
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.get(
                OPENROUTER_MODELS_URL,
                headers={
                    "Accept": "application/json",
                    "User-Agent": "MuMuAINovel-App",
                },
            )
            response.raise_for_status()
            payload = response.json()

        now = datetime.utcnow()
        prices: Dict[str, ModelPricing] = {}
        for item in payload.get("data") or []:
            model_id = str(item.get("id") or "").strip()
            if not model_id:
                continue
            pricing = item.get("pricing") or {}
            prices[model_id.lower()] = ModelPricing(
                model=model_id,
                prompt=self._to_float(pricing.get("prompt")),
                completion=self._to_float(pricing.get("completion")),
                currency="USD",
                updated_at=now,
            )

        self._prices = prices
        self._updated_at = now
        logger.info(f"OpenRouter 模型价格缓存已刷新: {len(prices)} 个模型")
        return len(prices)

    async def get_pricing(self, model: Optional[str]) -> Optional[ModelPricing]:
        """获取模型价格，找不到时返回 None。"""
        model_key = (model or "").strip().lower()
        if not model_key:
            return None

        if not self._cache_valid():
            try:
                await self.refresh()
            except Exception as e:
                logger.warning(f"刷新 OpenRouter 价格缓存失败: {e}")
                if not self._prices:
                    return None

        return self._prices.get(model_key)

    async def estimate_cost(
        self,
        model: Optional[str],
        prompt_tokens: Optional[int],
        completion_tokens: Optional[int],
    ) -> tuple[Optional[ModelPricing], Optional[float]]:
        """估算参考费用。OpenRouter 单价为每 token 美元价。"""
        pricing = await self.get_pricing(model)
        if not pricing:
            return None, None

        prompt_cost = (prompt_tokens or 0) * (pricing.prompt or 0)
        completion_cost = (completion_tokens or 0) * (pricing.completion or 0)
        return pricing, prompt_cost + completion_cost

    @staticmethod
    def _to_float(value) -> Optional[float]:
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None


openrouter_pricing_service = OpenRouterPricingService()
