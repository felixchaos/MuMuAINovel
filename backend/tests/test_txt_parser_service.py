"""TXT parser regression tests for import chapter splitting."""
from __future__ import annotations

from app.services.txt_parser_service import TxtParserService


def _paragraph(seed: str, repeat: int = 45) -> str:
    return (seed + "这是一个用于模拟正文长度的段落，包含叙事、动作和对话，避免被误判成普通列表项。") * repeat


def test_act_numbered_sections_are_chapters() -> None:
    parser = TxtParserService()
    text = "\n".join(
        [
            "异象旅馆 第一幕：来自异国的求助信号",
            "",
            "（1）",
            _paragraph("诺森站在彩绘玻璃下，听见远方传来的求助信号。"),
            "",
            "（2）",
            _paragraph("魔法屏障缓慢恢复，队伍开始确认异国来客的身份。"),
            "",
            "（3）",
            _paragraph("众人在图书馆里交换情报，新的线索指向海港。"),
        ]
    )

    chapters = parser.split_chapters(parser.clean_text(text))

    assert len(chapters) == 3
    assert chapters[0]["title"].endswith("（1）")
    assert chapters[1]["title"].endswith("（2）")
    assert chapters[2]["title"].endswith("（3）")


def test_book_title_pagination_is_split() -> None:
    parser = TxtParserService()
    text = "\n".join(
        [
            "异象旅馆(1)",
            _paragraph("午后的阳光穿过图书馆顶层的彩绘玻璃。"),
            "",
            "异象旅馆(2)",
            _paragraph("魔法屏障像水纹一样恢复，艾米瑟娅听见警报。"),
            "",
            "异象旅馆(3)",
            _paragraph("诺森把地图摊开，旅馆大厅里只剩下钟表声。"),
        ]
    )

    chapters = parser.split_chapters(parser.clean_text(text))

    assert [chapter["title"] for chapter in chapters] == ["异象旅馆(1)", "异象旅馆(2)", "异象旅馆(3)"]


def test_markdown_headings_are_split() -> None:
    parser = TxtParserService()
    text = "\n".join(
        [
            "# 第一章 风起",
            _paragraph("第一章正文。", 20),
            "## 第二章 雨落",
            _paragraph("第二章正文。", 20),
        ]
    )

    chapters = parser.split_chapters(parser.clean_text(text))

    assert len(chapters) == 2
    assert chapters[0]["title"] == "# 第一章 风起"
    assert chapters[1]["title"] == "## 第二章 雨落"


def test_real_act_sample_keeps_numbered_sections() -> None:
    parser = TxtParserService()
    sample = "\n".join(
        [
            "异象旅馆 第一幕：来自异国的求助信号",
            "",
            "（1）",
            _paragraph("少女的睫毛轻轻颤动，嘴角还带着一丝疲惫。", 60),
            "",
            "（2）",
            _paragraph("胆小的诺雪立刻聚到了诺森的身后，紧张地抓着她的手臂。", 60),
            "",
            "（3）",
            _paragraph("那些声音听起来相当弱气，话语中还带着一丝怀疑与不安。", 60),
            "",
            "（4）",
            _paragraph("她的声音听起来很虚弱，不过语气却是还出乎意料的冷静。", 60),
            "",
            "（5）",
            _paragraph("金鸢尾兰帝国与咖菲洛亚王国之间并没有直达飞机。", 60),
        ]
    )

    chapters = parser.split_chapters(parser.clean_text(sample))

    assert len(chapters) == 5
    assert all("第一幕" in chapter["title"] for chapter in chapters)
    assert [chapter["chapter_number"] for chapter in chapters] == [1, 2, 3, 4, 5]


if __name__ == "__main__":
    test_act_numbered_sections_are_chapters()
    test_book_title_pagination_is_split()
    test_markdown_headings_are_split()
    test_real_act_sample_keeps_numbered_sections()
