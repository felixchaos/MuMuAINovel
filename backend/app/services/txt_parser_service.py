"""TXT 解析服务：编码识别、文本清洗与章节切分"""
from __future__ import annotations

import re
from typing import Optional

from app.logger import get_logger

logger = get_logger(__name__)


class TxtParserService:
    """TXT 解析服务（规则优先）"""

    STRONG_CHAPTER_PATTERNS = [
        re.compile(
            r"^第[一二三四五六七八九十百千万零〇两\d]+"
            r"(?:[章回卷集部篇].*|节(?:$|[\s　:：、.．\-—]).*)$"
        ),
        re.compile(r"^chapter\s*\d+.*$", re.IGNORECASE),
        re.compile(r"^chap\.\s*\d+.*$", re.IGNORECASE),
    ]

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
        if not text.strip():
            return []

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

        # 标准章节标题足够多时，弱标题只会增加对白/短句误判。
        heading_indexes = strong_heading_indexes if len(strong_heading_indexes) >= 2 else (
            strong_heading_indexes + weak_heading_indexes
        )
        heading_indexes = sorted(set(heading_indexes))

        # 如果一个标题都识别不到，走固定窗口兜底
        if not heading_indexes:
            return self._fallback_split(text)

        # 如果第一个标题前有较长正文，作为前言章节保留
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

        # 过滤掉明显噪音章节
        filtered = [c for c in chapters if c["title"] or c["content"]]
        if filtered:
            return filtered

        return self._fallback_split(text)

    def _is_strong_heading(self, line: str) -> bool:
        return any(pattern.match(line) for pattern in self.STRONG_CHAPTER_PATTERNS)

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
