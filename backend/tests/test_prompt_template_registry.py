import importlib
import sys
import types
from string import Formatter

from app.services.ai_service import AIService
from app.services.prompt_service import PromptService


def _template_fields(content: str) -> set[str]:
    return {
        field.split(".")[0].split("[")[0]
        for _, field, _, _ in Formatter().parse(content)
        if field
    }


def _load_plot_analyzer_with_sqlalchemy_stub():
    sqlalchemy_mod = types.ModuleType("sqlalchemy")
    ext_mod = types.ModuleType("sqlalchemy.ext")
    asyncio_mod = types.ModuleType("sqlalchemy.ext.asyncio")
    asyncio_mod.AsyncSession = object
    ext_mod.asyncio = asyncio_mod
    sqlalchemy_mod.ext = ext_mod

    previous = {
        "sqlalchemy": sys.modules.get("sqlalchemy"),
        "sqlalchemy.ext": sys.modules.get("sqlalchemy.ext"),
        "sqlalchemy.ext.asyncio": sys.modules.get("sqlalchemy.ext.asyncio"),
    }
    sys.modules["sqlalchemy"] = sqlalchemy_mod
    sys.modules["sqlalchemy.ext"] = ext_mod
    sys.modules["sqlalchemy.ext.asyncio"] = asyncio_mod
    try:
        return importlib.import_module("app.services.plot_analyzer").PlotAnalyzer
    finally:
        for name, module in previous.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module


def test_polish_optimization_templates_are_registered() -> None:
    templates = {
        item["template_key"]: item
        for item in PromptService.get_all_system_templates()
    }

    for key in ("OUTLINE_OPTIMIZE", "CHARACTER_OPTIMIZE", "ORGANIZATION_OPTIMIZE"):
        assert key in templates
        assert templates[key]["category"] == "AI优化"
        assert templates[key]["parameters"] == ["source"]
        assert _template_fields(templates[key]["content"]) == {"source"}


def test_user_facing_generation_templates_are_registered() -> None:
    templates = {
        item["template_key"]: item
        for item in PromptService.get_all_system_templates()
    }

    expected = {
        "CHARACTER_TEXT_ANALYSIS": {
            "project_context",
            "existing_info",
            "story_context",
            "extra_requirements",
            "max_characters",
        },
        "RELATIONSHIP_INCREMENTAL_GENERATION": {
            "project_context",
            "character_context",
            "existing_context",
            "story_context",
            "requirements",
            "relationship_count",
        },
        "CAREER_INCREMENTAL_GENERATION": {"project_context", "generation_requirements"},
    }
    for key, params in expected.items():
        assert key in templates
        assert set(templates[key]["parameters"]) == params
        assert _template_fields(templates[key]["content"]) == params


def test_template_registry_parameters_match_default_placeholders() -> None:
    for item in PromptService.get_all_system_templates():
        assert set(item["parameters"]) == _template_fields(item["content"]), item["template_key"]


def test_prompt_constants_and_registry_stay_in_sync() -> None:
    constants = {
        key
        for key, value in vars(PromptService).items()
        if key.isupper() and isinstance(value, str)
    }
    templates = {item["template_key"] for item in PromptService.get_all_system_templates()}

    assert constants == templates


def test_unused_planning_templates_are_not_exposed() -> None:
    templates = {item["template_key"] for item in PromptService.get_all_system_templates()}

    assert "MCP_WORLD_BUILDING_PLANNING" not in templates
    assert "MCP_CHARACTER_PLANNING" not in templates
    assert "AUTO_CHARACTER_ANALYSIS" not in templates
    assert "AUTO_ORGANIZATION_ANALYSIS" not in templates


def test_system_prompt_merge_keeps_global_and_call_scopes_once() -> None:
    service = AIService.__new__(AIService)
    service.default_system_prompt = "全局规则"

    assert service._merge_system_prompt(None) == "全局规则"
    assert service._merge_system_prompt("本次任务") == "全局规则\n\n本次任务"
    assert service._merge_system_prompt("全局规则") == "全局规则"
    assert service._merge_system_prompt("全局规则\n\n本次任务") == "全局规则\n\n本次任务"


def test_long_chapter_analysis_content_keeps_head_middle_and_tail() -> None:
    PlotAnalyzer = _load_plot_analyzer_with_sqlalchemy_stub()
    analyzer = PlotAnalyzer(ai_service=None)  # type: ignore[arg-type]
    content = ("A" * 7000) + ("B" * 6000) + ("C" * 7000)

    prepared = analyzer._prepare_analysis_content(content, max_chars=16000)

    assert prepared.startswith("A" * 6000)
    assert "B" * 1000 in prepared
    assert prepared.endswith("C" * 6000)
    assert "中段节选" in prepared
    assert "末尾节选" in prepared
    assert len(prepared) < len(content)


if __name__ == "__main__":
    test_polish_optimization_templates_are_registered()
    test_user_facing_generation_templates_are_registered()
    test_template_registry_parameters_match_default_placeholders()
    test_prompt_constants_and_registry_stay_in_sync()
    test_unused_planning_templates_are_not_exposed()
    test_system_prompt_merge_keeps_global_and_call_scopes_once()
    test_long_chapter_analysis_content_keeps_head_middle_and_tail()
