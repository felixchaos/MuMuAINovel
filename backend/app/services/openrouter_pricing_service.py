"""OpenRouter 模型价格缓存服务。

OpenRouter 的模型列表接口会返回模型 pricing 字段。这里仅把它用作
Token 参考价估算，不做真实计费。
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Optional

import httpx

from app.config import DATA_DIR
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
    """服务器本地价格缓存，避免每次 AI 调用都访问 OpenRouter。"""

    def __init__(
        self,
        ttl: timedelta = timedelta(days=1),
        cache_path: Optional[Path] = None,
    ):
        self.ttl = ttl
        self.cache_path = cache_path or DATA_DIR / "openrouter_model_pricing_cache.json"
        self._prices: Dict[str, ModelPricing] = {}
        self._updated_at: Optional[datetime] = None
        self._disk_loaded = False

    @property
    def updated_at(self) -> Optional[datetime]:
        self._ensure_disk_loaded()
        return self._updated_at

    @property
    def ttl_hours(self) -> int:
        return int(self.ttl.total_seconds() // 3600)

    def _cache_valid(self) -> bool:
        self._ensure_disk_loaded()
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
        self._write_cache_to_disk()
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

    def _ensure_disk_loaded(self) -> None:
        if self._disk_loaded:
            return
        self._disk_loaded = True
        if not self.cache_path.exists():
            return

        try:
            payload = json.loads(self.cache_path.read_text(encoding="utf-8"))
            updated_at_raw = payload.get("updated_at")
            prices_raw = payload.get("prices") or {}
            updated_at = datetime.fromisoformat(updated_at_raw) if updated_at_raw else None
            prices: Dict[str, ModelPricing] = {}
            for model_key, item in prices_raw.items():
                model_id = str(item.get("model") or model_key).strip()
                if not model_id:
                    continue
                prices[model_key] = ModelPricing(
                    model=model_id,
                    prompt=self._to_float(item.get("prompt")),
                    completion=self._to_float(item.get("completion")),
                    currency=str(item.get("currency") or "USD"),
                    updated_at=updated_at or datetime.utcnow(),
                )
            self._prices = prices
            self._updated_at = updated_at
            logger.info(f"已加载 OpenRouter 本地价格缓存: {len(prices)} 个模型")
        except Exception as e:
            logger.warning(f"读取 OpenRouter 本地价格缓存失败: {e}")

    def _write_cache_to_disk(self) -> None:
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "updated_at": self._updated_at.isoformat() if self._updated_at else None,
                "ttl_hours": self.ttl_hours,
                "source": OPENROUTER_MODELS_URL,
                "prices": {
                    key: {
                        "model": pricing.model,
                        "prompt": pricing.prompt,
                        "completion": pricing.completion,
                        "currency": pricing.currency,
                    }
                    for key, pricing in self._prices.items()
                },
            }
            self.cache_path.write_text(
                json.dumps(payload, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception as e:
            logger.warning(f"写入 OpenRouter 本地价格缓存失败: {e}")

    @staticmethod
    def _to_float(value) -> Optional[float]:
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None


openrouter_pricing_service = OpenRouterPricingService()
