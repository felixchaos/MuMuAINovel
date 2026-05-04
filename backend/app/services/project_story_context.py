"""Helpers for building compact project story context from outlines and chapters."""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.character import Character
from app.models.chapter import Chapter
from app.models.outline import Outline
from app.services.name_authority_service import build_name_authority


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
    prefer_chapter_content: bool = False,
    chapter_excerpt_chars: int = 320,
    include_name_authority: bool = True,
) -> str:
    """Build a bounded context from existing outlines and chapters for AI generation."""
    lines: list[str] = []

    if include_name_authority:
        characters_result = await db.execute(
            select(Character)
            .where(Character.project_id == project_id)
            .order_by(Character.is_organization.asc(), Character.created_at.asc())
            .limit(80)
        )
        characters = characters_result.scalars().all()
        if characters:
            authority = build_name_authority(characters)
            canonical_names = sorted(authority.canonical_names)
            if canonical_names:
                lines.append("【名称权威表】")
                for name in canonical_names[:40]:
                    aliases = sorted(
                        alias
                        for alias, canonical in authority.alias_to_name.items()
                        if canonical == name and alias != name
                    )
                    alias_text = f"（别名/称呼：{'、'.join(aliases[:5])}）" if aliases else ""
                    if not _append_with_budget(lines, f"- {name}{alias_text}", max_chars):
                        break

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
            source = chapter.content if prefer_chapter_content else (chapter.summary or chapter.content or "")
            content = _compact_text(source or "", chapter_excerpt_chars)
            if not content:
                continue
            line = f"- 第{chapter.chapter_number}章 {chapter.title}: {content}"
            if not _append_with_budget(lines, line, max_chars):
                break

    if not lines:
        return "【已有大纲和章节】暂无可用内容。"

    return "\n".join(lines)
