"""Helpers for building compact project story context from outlines and chapters."""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chapter import Chapter
from app.models.outline import Outline


def _compact_text(text: str, max_len: int) -> str:
    cleaned = " ".join((text or "").split())
    if len(cleaned) <= max_len:
        return cleaned
    return f"{cleaned[:max_len].rstrip()}..."


def _append_with_budget(lines: list[str], line: str, budget: int) -> bool:
    current_len = sum(len(item) + 1 for item in lines)
    if current_len + len(line) + 1 > budget:
        return False
    lines.append(line)
    return True


async def build_project_story_context(
    db: AsyncSession,
    project_id: str,
    *,
    max_chars: int = 12000,
    outline_limit: int = 80,
    chapter_limit: int = 80,
) -> str:
    """Build a bounded context from existing outlines and chapters for AI generation."""
    lines: list[str] = []

    outlines_result = await db.execute(
        select(Outline)
        .where(Outline.project_id == project_id)
        .order_by(Outline.order_index.asc(), Outline.created_at.asc())
        .limit(outline_limit)
    )
    outlines = outlines_result.scalars().all()

    if outlines:
        lines.append("【已有大纲摘要】")
        for outline in outlines:
            content = _compact_text(outline.content or outline.structure or "", 260)
            if not content:
                continue
            order_label = outline.order_index if outline.order_index is not None else "-"
            if not _append_with_budget(lines, f"- 第{order_label}条 {outline.title}: {content}", max_chars):
                break

    chapters_result = await db.execute(
        select(Chapter)
        .where(Chapter.project_id == project_id)
        .order_by(Chapter.chapter_number.asc(), Chapter.created_at.asc())
        .limit(chapter_limit)
    )
    chapters = chapters_result.scalars().all()

    if chapters and sum(len(item) + 1 for item in lines) < max_chars:
        if lines:
            lines.append("")
        lines.append("【已有章节摘要】")
        for chapter in chapters:
            source = chapter.summary or chapter.content or ""
            content = _compact_text(source, 320)
            if not content:
                continue
            line = f"- 第{chapter.chapter_number}章 {chapter.title}: {content}"
            if not _append_with_budget(lines, line, max_chars):
                break

    if not lines:
        return "【已有大纲和章节】暂无可用内容。"

    return "\n".join(lines)
