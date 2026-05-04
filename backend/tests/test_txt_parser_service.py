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


def test_split_report_exposes_mode_and_quality() -> None:
    parser = TxtParserService()
    text = "\n".join(
        [
            "异象旅馆 第一幕：来自异国的求助信号",
            "",
            "（1）",
            _paragraph("午后的阳光穿过图书馆顶层的彩绘玻璃。"),
            "",
            "（2）",
            _paragraph("魔法屏障像水纹一样恢复，艾米瑟娅听见警报。"),
            "",
            "（3）",
            _paragraph("诺森把地图摊开，旅馆大厅里只剩下钟表声。"),
        ]
    )

    chapters, report = parser.split_chapters_with_report(parser.clean_text(text))

    assert len(chapters) == 3
    assert report["mode"] == "numbered_sections"
    assert report["mode_label"] == "篇章小节"
    assert report["confidence"] >= 0.75
    assert report["chapter_count"] == 3
    assert report["reasons"]


def test_ground_truth_regression_cases() -> None:
    parser = TxtParserService()
    cases = [
        {
            "name": "standard_chinese_chapters",
            "text": "\n".join([
                "第1章 初遇",
                _paragraph("少女在雨夜里推开门。", 28),
                "第2章 线索",
                _paragraph("旧照片背后藏着新的线索。", 28),
                "第3章 追踪",
                _paragraph("他们沿着河岸一路追踪。", 28),
            ]),
            "titles": ["第1章 初遇", "第2章 线索", "第3章 追踪"],
            "min_confidence": 0.75,
        },
        {
            "name": "tomato_like_title_pages",
            "text": "\n".join([
                "异象旅馆(1)",
                _paragraph("午后的阳光穿过图书馆顶层的彩绘玻璃。", 28),
                "异象旅馆(2)",
                _paragraph("魔法屏障像水纹一样恢复。", 28),
                "异象旅馆(3)",
                _paragraph("诺森把地图摊开。", 28),
            ]),
            "titles": ["异象旅馆(1)", "异象旅馆(2)", "异象旅馆(3)"],
            "min_confidence": 0.70,
        },
        {
            "name": "act_sections",
            "text": "\n".join([
                "异象旅馆 第一幕：来自异国的求助信号",
                "（1）",
                _paragraph("少女的睫毛轻轻颤动。", 30),
                "（2）",
                _paragraph("胆小的诺雪立刻聚到了诺森的身后。", 30),
                "（3）",
                _paragraph("旅馆大厅里只剩下钟表声。", 30),
            ]),
            "titles": [
                "第一幕：来自异国的求助信号（1）",
                "第一幕：来自异国的求助信号（2）",
                "第一幕：来自异国的求助信号（3）",
            ],
            "min_confidence": 0.75,
        },
    ]

    for case in cases:
        chapters, report = parser.split_chapters_with_report(parser.clean_text(case["text"]))

        assert [chapter["title"] for chapter in chapters] == case["titles"], case["name"]
        assert report["chapter_count"] == len(case["titles"]), case["name"]
        assert report["confidence"] >= case["min_confidence"], case["name"]
        assert report["abnormal_chapter_numbers"] == [], case["name"]


def test_low_confidence_fallback_is_reported() -> None:
    parser = TxtParserService()
    text = _paragraph("没有章节标题的长文本。", 180)

    chapters, report = parser.split_chapters_with_report(parser.clean_text(text))

    assert len(chapters) >= 1
    assert report["mode"] == "fallback_window"
    assert report["confidence"] < 0.55
    assert report["reasons"]


if __name__ == "__main__":
    test_act_numbered_sections_are_chapters()
    test_book_title_pagination_is_split()
    test_markdown_headings_are_split()
    test_real_act_sample_keeps_numbered_sections()
    test_split_report_exposes_mode_and_quality()
    test_ground_truth_regression_cases()
    test_low_confidence_fallback_is_reported()
