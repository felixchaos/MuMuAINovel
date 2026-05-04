"""TXT 解析服务：编码识别、文本清洗与章节切分"""
from __future__ import annotations

import re
from typing import Optional

from app.logger import get_logger

logger = get_logger(__name__)


class TxtParserService:
    """TXT 解析服务（规则优先）"""

    NUMBER_TOKEN = r"一二三四五六七八九十百千万零〇两\d"
    SECTION_MARKER_PATTERN = re.compile(rf"^[（(]\s*([{NUMBER_TOKEN}]{{1,8}})\s*[）)]$")
    PAGINATION_HEADING_PATTERN = re.compile(r"^(.{1,60}?)[（(]\s*(\d{1,5})\s*[）)]$")
    ACT_HEADING_PATTERN = re.compile(
        rf"^(?:.{{0,80}}?\s+)?(第[{NUMBER_TOKEN}]+[幕卷部集篇](?:\s*[：:、.．\-—]\s*.+|.+)?)$"
    )

    STRONG_CHAPTER_PATTERNS = [
        re.compile(
            rf"^第[{NUMBER_TOKEN}]+"
            r"(?:[章回卷集部篇幕场].*|节(?:$|[\s　:：、.．\-—]).*)$"
        ),
        re.compile(r"^(?:楔子|引子|序[章言曲]?|后记|尾声|终章|完本感言|番外)(?:$|[\s　:：、.．\-—].*)$"),
        re.compile(r"^#{1,3}\s+\S.+$"),
        re.compile(r"^(?:chapter|chap\.|part)\s*[\divxlcdm]+.*$", re.IGNORECASE),
        re.compile(r"^(?:prologue|epilogue).*$", re.IGNORECASE),
    ]

    SPLIT_MODE_LABELS = {
        "empty": "空文本",
        "numbered_sections": "篇章小节",
        "pagination_headings": "分页标题",
        "strong_headings": "标准章节标题",
        "weak_headings": "弱标题推断",
        "fallback_window": "固定窗口兜底",
        "quality_fallback_window": "质量兜底窗口",
    }

    def decode_bytes(self, content: bytes) -> tuple[str, str]:
        """
        尝试解码 TXT 字节流

        Returns:
            (text, encoding)
        """
        encodings = ["utf-8", "utf-8-sig", "gb18030", "gbk", "big5"]
        for enc in encodings:
            try:
                return content.decode(enc), enc
            except UnicodeDecodeError:
                continue

        # 最后兜底：不抛错，尽量读出内容
        logger.warning("TXT 编码自动识别失败，使用 utf-8(ignore) 兜底")
        return content.decode("utf-8", errors="ignore"), "utf-8(ignore)"

    def clean_text(self, text: str) -> str:
        """基础清洗：换行归一、去除异常空白、压缩多余空行"""
        normalized = text.replace("\r\n", "\n").replace("\r", "\n").replace("\ufeff", "")
        normalized = normalized.replace("\u3000", "  ")
        normalized = re.sub(r"[ \t]+\n", "\n", normalized)
        normalized = re.sub(r"\n{4,}", "\n\n\n", normalized)
        return normalized.strip()

    def split_chapters(self, text: str) -> list[dict]:
        """
        章节切分（规则优先，失败兜底）

        Returns:
            [{title, content, chapter_number}]
        """
        chapters, _report = self.split_chapters_with_report(text)
        return chapters

    def split_chapters_with_report(self, text: str) -> tuple[list[dict], dict]:
        """章节切分，并返回可展示的切分诊断报告。"""
        chapters, split_mode = self._split_chapters_internal(text)
        return chapters, self._build_split_report(
            chapters=chapters,
            split_mode=split_mode,
            source_text=text,
        )

    def _split_chapters_internal(self, text: str) -> tuple[list[dict], str]:
        if not text.strip():
            return [], "empty"

        lines = text.split("\n")
        strong_heading_indexes: list[int] = []
        weak_heading_indexes: list[int] = []

        for idx, line in enumerate(lines):
            stripped = line.strip()
            if not stripped:
                continue
            if self._is_strong_heading(stripped):
                strong_heading_indexes.append(idx)
            elif self._is_weak_heading(lines, idx):
                weak_heading_indexes.append(idx)

        # 有些正文使用“第一幕：xxx”作为篇章标题，真正的章节边界是独立行“（1）/（2）”。
        # 这种格式不应走固定字数兜底，否则会把一节拆成多个 5000 字窗口。
        section_heading_indexes = self._collect_numbered_section_headings(lines)
        if section_heading_indexes and (
            len(strong_heading_indexes) < 2 or len(section_heading_indexes) >= len(strong_heading_indexes) * 2
        ):
            section_chapters = self._split_numbered_sections(lines, section_heading_indexes)
            if section_chapters:
                return self._post_process_chapters(section_chapters), "numbered_sections"

        # 兼容导出文本常见的“书名(1) / 书名(2)”分页标题。
        if len(strong_heading_indexes) < 2:
            pagination_heading_indexes = self._collect_pagination_headings(lines)
            if pagination_heading_indexes:
                pagination_chapters = self._split_standard_headings(lines, pagination_heading_indexes)
                if pagination_chapters:
                    return self._post_process_chapters(pagination_chapters), "pagination_headings"

        # 标准章节标题足够多时，弱标题只会增加对白/短句误判。
        has_strong_mode = len(strong_heading_indexes) >= 2
        heading_indexes = strong_heading_indexes if has_strong_mode else (strong_heading_indexes + weak_heading_indexes)
        heading_indexes = sorted(set(heading_indexes))

        # 如果一个标题都识别不到，走固定窗口兜底
        if not heading_indexes:
            return self._fallback_split(text), "fallback_window"

        chapters = self._split_standard_headings(lines, heading_indexes)
        processed = self._post_process_chapters(chapters)
        if processed and self._has_reasonable_chapter_quality(processed):
            return processed, "strong_headings" if has_strong_mode else "weak_headings"

        return self._fallback_split(text), "quality_fallback_window"

    def _build_split_report(self, *, chapters: list[dict], split_mode: str, source_text: str) -> dict:
        lengths = [len((chapter.get("content") or "").strip()) for chapter in chapters]
        chapter_count = len(chapters)
        total_words = sum(lengths)
        average_words = int(total_words / chapter_count) if chapter_count else 0
        min_words = min(lengths) if lengths else 0
        max_words = max(lengths) if lengths else 0
        short_numbers = [
            int(chapter.get("chapter_number") or idx)
            for idx, chapter in enumerate(chapters, start=1)
            if len((chapter.get("content") or "").strip()) < 300
        ]
        long_numbers = [
            int(chapter.get("chapter_number") or idx)
            for idx, chapter in enumerate(chapters, start=1)
            if len((chapter.get("content") or "").strip()) > 12000
        ]

        reasons: list[str] = []
        confidence = {
            "numbered_sections": 0.86,
            "strong_headings": 0.88,
            "pagination_headings": 0.78,
            "weak_headings": 0.58,
            "fallback_window": 0.38,
            "quality_fallback_window": 0.34,
            "empty": 0.0,
        }.get(split_mode, 0.5)

        if split_mode in {"fallback_window", "quality_fallback_window"}:
            reasons.append("未找到可靠章节标题，已按固定字数窗口兜底切分")
        if split_mode == "weak_headings":
            reasons.append("仅识别到弱标题，建议人工确认章节边界")
        if split_mode == "pagination_headings":
            reasons.append("检测到分页式标题，已按同名连续页码切分")
        if split_mode == "numbered_sections":
            reasons.append("检测到篇章标题下的独立小节编号，已按小节编号切分")

        if chapter_count <= 1 and len(source_text) > 5000:
            confidence -= 0.25
            reasons.append("长文本只识别到一个章节，可能存在漏切")
        if short_numbers:
            confidence -= min(0.2, len(short_numbers) / max(1, chapter_count) * 0.25)
            reasons.append(f"有 {len(short_numbers)} 个章节短于300字，建议检查是否误切")
        if long_numbers:
            confidence -= min(0.16, len(long_numbers) / max(1, chapter_count) * 0.2)
            reasons.append(f"有 {len(long_numbers)} 个章节超过12000字，建议检查是否漏切")
        if chapter_count >= 3 and min_words > 0 and max_words / max(1, min_words) >= 8:
            confidence -= 0.12
            reasons.append("章节长度差异较大，可能存在边界异常")
        if not chapters and source_text.strip():
            reasons.append("文本存在内容，但未能识别有效章节")

        confidence = max(0.0, min(0.99, confidence))
        abnormal_numbers = sorted(set(short_numbers + long_numbers))[:80]

        return {
            "mode": split_mode,
            "mode_label": self.SPLIT_MODE_LABELS.get(split_mode, split_mode),
            "confidence": round(confidence, 2),
            "chapter_count": chapter_count,
            "total_words": total_words,
            "average_words": average_words,
            "min_words": min_words,
            "max_words": max_words,
            "short_chapter_count": len(short_numbers),
            "long_chapter_count": len(long_numbers),
            "abnormal_chapter_numbers": abnormal_numbers,
            "reasons": reasons,
        }

    def _is_strong_heading(self, line: str) -> bool:
        if len(line) > 120:
            return False
        if len(line) > 80 and re.search(r"[。！？!?；;]", line):
            return False
        return any(pattern.match(line) for pattern in self.STRONG_CHAPTER_PATTERNS)

    def _split_standard_headings(self, lines: list[str], heading_indexes: list[int]) -> list[dict]:
        """按已识别出的标题行切分章节，并保留较长前言。"""
        chapters: list[dict] = []
        chapter_no = 1

        first_heading = heading_indexes[0]
        if first_heading > 0:
            preface = "\n".join(lines[:first_heading]).strip()
            if len(preface) >= 200:
                chapters.append(
                    {
                        "title": "前言",
                        "content": preface,
                        "chapter_number": chapter_no,
                    }
                )
                chapter_no += 1

        for i, start_idx in enumerate(heading_indexes):
            end_idx = heading_indexes[i + 1] if i + 1 < len(heading_indexes) else len(lines)
            title = lines[start_idx].strip()[:200] or f"第{chapter_no}章"
            body = "\n".join(lines[start_idx + 1 : end_idx]).strip()
            # 防止空标题/空正文完全丢失
            if not body and i + 1 < len(heading_indexes):
                next_line = lines[start_idx + 1].strip() if start_idx + 1 < len(lines) else ""
                body = next_line

            chapters.append(
                {
                    "title": title,
                    "content": body,
                    "chapter_number": chapter_no,
                }
            )
            chapter_no += 1

        return [c for c in chapters if c["title"] or c["content"]]

    def _collect_pagination_headings(self, lines: list[str]) -> list[int]:
        """识别“书名(1) / 书名(2)”这类分页式章节标题。"""
        candidates: list[tuple[int, str, int]] = []
        for idx, line in enumerate(lines):
            stripped = line.strip()
            match = self.PAGINATION_HEADING_PATTERN.match(stripped)
            if not match:
                continue

            title = match.group(1).strip()
            page_no = int(match.group(2))
            if not title or page_no <= 0:
                continue
            if len(title) > 40 or re.search(r"[。！？!?；;]", title):
                continue

            next_idx = self._next_nonempty_line_index(lines, idx + 1)
            if next_idx is None:
                continue
            if len(lines[next_idx].strip()) < 20:
                continue

            candidates.append((idx, title, page_no))

        if len(candidates) < 3:
            return []

        title_counts: dict[str, int] = {}
        for _, title, _ in candidates:
            title_counts[title] = title_counts.get(title, 0) + 1

        dominant_title, dominant_count = max(title_counts.items(), key=lambda item: item[1])
        if dominant_count < max(3, int(len(candidates) * 0.6)):
            return []

        filtered = [(idx, page_no) for idx, title, page_no in candidates if title == dominant_title]
        page_numbers = [page_no for _, page_no in filtered]
        unique_pages = sorted(set(page_numbers))
        if len(unique_pages) < 3:
            return []
        if unique_pages[0] != 1:
            return []
        if max(unique_pages) - min(unique_pages) + 1 > len(unique_pages) + 2:
            return []

        return [idx for idx, _ in filtered]

    def _collect_numbered_section_headings(self, lines: list[str]) -> list[int]:
        """识别“（1）/（2）”这类独立小节标题，并过滤普通列表项误判。"""
        candidates: list[int] = []
        for idx, line in enumerate(lines):
            if self._is_numbered_section_heading(lines, idx):
                candidates.append(idx)

        if len(candidates) < 2:
            return []

        section_lengths: list[int] = []
        for i, start_idx in enumerate(candidates):
            next_idx = candidates[i + 1] if i + 1 < len(candidates) else len(lines)
            end_idx = self._trim_trailing_act_heading(lines, start_idx + 1, next_idx)
            section_text = "\n".join(lines[start_idx + 1 : end_idx]).strip()
            if section_text:
                section_lengths.append(len(section_text))

        if len(section_lengths) < 2:
            return []

        # 正文小节通常会有成段内容；普通说明里的“（1）（2）”列表往往很短。
        long_sections = sum(length >= 500 for length in section_lengths)
        if long_sections < max(2, len(section_lengths) // 2):
            return []

        return candidates

    def _is_numbered_section_heading(self, lines: list[str], idx: int) -> bool:
        line = lines[idx].strip()
        match = self.SECTION_MARKER_PATTERN.match(line)
        if not match:
            return False

        next_idx = self._next_nonempty_line_index(lines, idx + 1)
        if next_idx is None:
            return False

        next_line = lines[next_idx].strip()
        if len(next_line) < 20:
            return False
        if self._is_strong_heading(next_line):
            return False

        return True

    def _split_numbered_sections(self, lines: list[str], heading_indexes: list[int]) -> list[dict]:
        chapters: list[dict] = []
        chapter_no = 1
        current_act_title: Optional[str] = None
        scan_from = 0

        first_heading = heading_indexes[0]
        if first_heading > 0:
            preface_lines: list[str] = []
            for idx in range(first_heading):
                stripped = lines[idx].strip()
                act_title = self._extract_act_heading(stripped)
                if act_title:
                    current_act_title = act_title
                elif stripped:
                    preface_lines.append(lines[idx])

            preface = "\n".join(preface_lines).strip()
            if len(preface) >= 200:
                chapters.append(
                    {
                        "title": "前言",
                        "content": preface,
                        "chapter_number": chapter_no,
                    }
                )
                chapter_no += 1
            scan_from = first_heading + 1

        for i, start_idx in enumerate(heading_indexes):
            for idx in range(scan_from, start_idx):
                act_title = self._extract_act_heading(lines[idx].strip())
                if act_title:
                    current_act_title = act_title

            raw_marker = lines[start_idx].strip()
            marker = re.sub(r"\s+", "", raw_marker)
            title = f"{current_act_title}{marker}" if current_act_title else marker

            raw_end_idx = heading_indexes[i + 1] if i + 1 < len(heading_indexes) else len(lines)
            end_idx = self._trim_trailing_act_heading(lines, start_idx + 1, raw_end_idx)
            body = "\n".join(lines[start_idx + 1 : end_idx]).strip()

            if body:
                normalized_title = title[:200] or f"第{chapter_no}章"
                if chapters:
                    previous = chapters[-1]
                    previous_body = re.sub(r"\s+", "", previous.get("content") or "")
                    current_body = re.sub(r"\s+", "", body)
                    if previous.get("title") == normalized_title and previous_body == current_body:
                        scan_from = start_idx + 1
                        continue

                chapters.append(
                    {
                        "title": normalized_title,
                        "content": body,
                        "chapter_number": chapter_no,
                    }
                )
                chapter_no += 1

            scan_from = start_idx + 1

        return chapters

    def _extract_act_heading(self, line: str) -> Optional[str]:
        if not line or len(line) > 120:
            return None
        if re.search(r"[。！？!?；;]", line):
            return None
        match = self.ACT_HEADING_PATTERN.match(line)
        if not match:
            return None
        return match.group(1).strip()

    def _next_nonempty_line_index(self, lines: list[str], start_idx: int) -> Optional[int]:
        for idx in range(start_idx, len(lines)):
            if lines[idx].strip():
                return idx
        return None

    def _trim_trailing_act_heading(self, lines: list[str], start_idx: int, end_idx: int) -> int:
        idx = end_idx - 1
        while idx >= start_idx and not lines[idx].strip():
            idx -= 1
        if idx >= start_idx and self._extract_act_heading(lines[idx].strip()):
            return idx
        return end_idx

    def _is_weak_heading(self, lines: list[str], idx: int) -> bool:
        """
        弱模式：短行 + 前后空行 + 避免普通句子误判
        """
        line = lines[idx].strip()
        if not line:
            return False
        if len(line) > 25:
            return False
        if re.search(r"[，。！？；：,.!?;:]", line):
            return False
        if line.startswith(("“", "‘", "\"", "'", "「", "『", "（", "(", "《")):
            return False
        if line.endswith(("”", "’", "\"", "'", "」", "』", "）", ")", "》")):
            return False

        prev_blank = idx == 0 or not lines[idx - 1].strip()
        next_blank = idx == len(lines) - 1 or not lines[idx + 1].strip()
        return prev_blank and next_blank

    def _post_process_chapters(self, chapters: list[dict]) -> list[dict]:
        """章节后处理：去空、去连续重复、超大章节再按自然边界拆小。"""
        cleaned: list[dict] = []
        for chapter in chapters:
            title = str(chapter.get("title") or "").strip()[:200]
            content = str(chapter.get("content") or "").strip()
            if not title and not content:
                continue

            if content and len(content) > 50000:
                sub_chapters = self._fallback_split(content, min_window=6000, max_window=9000)
                for idx, sub_chapter in enumerate(sub_chapters, start=1):
                    cleaned.append(
                        {
                            "title": f"{title or '章节'}（{idx}）"[:200],
                            "content": sub_chapter["content"],
                            "chapter_number": len(cleaned) + 1,
                        }
                    )
                continue

            if cleaned:
                previous = cleaned[-1]
                previous_body = re.sub(r"\s+", "", previous.get("content") or "")
                current_body = re.sub(r"\s+", "", content)
                if previous.get("title") == title and previous_body == current_body:
                    continue

            cleaned.append(
                {
                    "title": title or f"第{len(cleaned) + 1}章",
                    "content": content,
                    "chapter_number": len(cleaned) + 1,
                }
            )

        for idx, chapter in enumerate(cleaned, start=1):
            chapter["chapter_number"] = idx
        return cleaned

    def _has_reasonable_chapter_quality(self, chapters: list[dict]) -> bool:
        """用轻量评分过滤误把对白/列表项当章节标题的切分结果。"""
        if not chapters:
            return False
        if len(chapters) <= 2:
            return True

        lengths = [len((chapter.get("content") or "").strip()) for chapter in chapters]
        total_length = sum(lengths)
        if total_length < 3000:
            return True

        nonempty_lengths = [length for length in lengths if length > 0]
        if len(nonempty_lengths) < max(2, len(chapters) // 2):
            return False

        tiny_count = sum(length < 200 for length in nonempty_lengths)
        if tiny_count / len(nonempty_lengths) > 0.45:
            return False

        sorted_lengths = sorted(nonempty_lengths)
        median_length = sorted_lengths[len(sorted_lengths) // 2]
        if len(chapters) >= 8 and median_length < 350:
            return False

        return True

    def _fallback_split(self, text: str, min_window: int = 3000, max_window: int = 5000) -> list[dict]:
        """
        固定窗口 + 标点边界切分
        """
        chapters: list[dict] = []
        n = len(text)
        start = 0
        chapter_no = 1
        boundary_punctuations = "。！？!?\n"

        while start < n:
            ideal_end = min(start + max_window, n)
            if ideal_end >= n:
                end = n
            else:
                search_from = min(start + min_window, n)
                segment = text[search_from:ideal_end]
                offset = max(segment.rfind(p) for p in boundary_punctuations)
                end = search_from + offset + 1 if offset >= 0 else ideal_end

            chunk = text[start:end].strip()
            if chunk:
                chapters.append(
                    {
                        "title": f"第{chapter_no}章",
                        "content": chunk,
                        "chapter_number": chapter_no,
                    }
                )
                chapter_no += 1

            start = end

        return chapters


txt_parser_service = TxtParserService()
