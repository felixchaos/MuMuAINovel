"""Public runtime metadata APIs."""
from __future__ import annotations

import time
from typing import Any

import httpx
from fastapi import APIRouter

from app.config import settings
from app.logger import get_logger

router = APIRouter(prefix="/public", tags=["public"])
logger = get_logger(__name__)

_AUTHOR_PROFILE_CACHE: dict[str, Any] = {"expires_at": 0.0, "data": None}
_AUTHOR_PROFILE_TTL_SECONDS = 6 * 60 * 60


def _fallback_author_profile() -> dict[str, str | None]:
    return {
        "display_name": settings.AUTHOR_DISPLAY_NAME,
        "profile_url": settings.AUTHOR_PROFILE_URL,
        "avatar_url": None,
    }


@router.get("/author-profile")
async def get_author_profile() -> dict[str, str | None]:
    """Return public maintainer profile metadata without exposing API keys."""

    now = time.time()
    cached = _AUTHOR_PROFILE_CACHE.get("data")
    if cached and float(_AUTHOR_PROFILE_CACHE.get("expires_at", 0.0)) > now:
        return cached

    fallback = _fallback_author_profile()
    identifier = (settings.GRAVATAR_PROFILE_IDENTIFIER or "").strip()
    if not identifier:
        _AUTHOR_PROFILE_CACHE.update({"data": fallback, "expires_at": now + _AUTHOR_PROFILE_TTL_SECONDS})
        return fallback

    url = f"https://api.gravatar.com/v3/profiles/{identifier}"
    headers = {}
    if settings.GRAVATAR_API_KEY:
        headers["Authorization"] = f"Bearer {settings.GRAVATAR_API_KEY}"

    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("Gravatar author profile fetch failed: %s", exc)
        _AUTHOR_PROFILE_CACHE.update({"data": fallback, "expires_at": now + 10 * 60})
        return fallback

    data = {
        "display_name": payload.get("display_name") or fallback["display_name"],
        "profile_url": settings.AUTHOR_PROFILE_URL or payload.get("profile_url") or fallback["profile_url"],
        "avatar_url": payload.get("avatar_url"),
    }
    _AUTHOR_PROFILE_CACHE.update({"data": data, "expires_at": now + _AUTHOR_PROFILE_TTL_SECONDS})
    return data
