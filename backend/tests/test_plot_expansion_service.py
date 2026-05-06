from app.services.plot_expansion_service import PlotExpansionService


def test_expansion_plan_sub_indexes_are_normalized() -> None:
    plans = [
        {"sub_index": 1, "title": "第一节"},
        {"sub_index": 1, "title": "第二节"},
        {"sub_index": 9, "title": "第三节"},
    ]

    normalized = PlotExpansionService._normalize_plan_sub_indexes(plans)

    assert [plan["sub_index"] for plan in normalized] == [1, 2, 3]
