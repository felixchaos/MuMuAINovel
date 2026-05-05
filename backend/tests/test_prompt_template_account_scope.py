"""Prompt template account isolation checks.

These tests avoid importing SQLAlchemy so they can run in the lightweight
repository test environment while still exercising PromptService.get_template.
"""
import asyncio
import re
import sys
import types
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.services.prompt_service import PromptService  # noqa: E402


class _Column:
    def __init__(self, name: str):
        self.name = name

    def __eq__(self, value):  # noqa: D105
        return (self.name, value)


class _PromptTemplateModel:
    user_id = _Column("user_id")
    template_key = _Column("template_key")
    is_active = _Column("is_active")


class _TemplateRecord:
    def __init__(self, content: str, name: str = "custom"):
        self.template_content = content
        self.template_name = name


class _Query:
    def __init__(self, model):
        self.model = model
        self.conditions = {}

    def where(self, *conditions):
        self.conditions = dict(conditions)
        return self


class _Result:
    def __init__(self, record):
        self.record = record

    def scalar_one_or_none(self):
        return self.record


class _Db:
    def __init__(self, records):
        self.records = records
        self.executed_filters = []

    async def execute(self, query):
        self.executed_filters.append(query.conditions)
        key = (query.conditions.get("user_id"), query.conditions.get("template_key"))
        if query.conditions.get("is_active") is not True:
            return _Result(None)
        return _Result(self.records.get(key))


def _install_sqlalchemy_stubs():
    sqlalchemy_mod = types.ModuleType("sqlalchemy")
    sqlalchemy_mod.select = lambda model: _Query(model)

    models_mod = types.ModuleType("app.models")
    prompt_template_mod = types.ModuleType("app.models.prompt_template")
    prompt_template_mod.PromptTemplate = _PromptTemplateModel
    models_mod.prompt_template = prompt_template_mod

    names = {
        "sqlalchemy": sqlalchemy_mod,
        "app.models": models_mod,
        "app.models.prompt_template": prompt_template_mod,
    }
    previous = {name: sys.modules.get(name) for name in names}
    sys.modules.update(names)
    return previous


def _restore_modules(previous):
    for name, module in previous.items():
        if module is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = module


def test_prompt_service_reads_only_current_account_template() -> None:
    previous = _install_sqlalchemy_stubs()
    try:
        db = _Db(
            {
                ("user_a", "AI_DENOISING"): _TemplateRecord("A account template"),
                ("user_b", "AI_DENOISING"): _TemplateRecord("B account template"),
            }
        )

        a_template = asyncio.run(PromptService.get_template("AI_DENOISING", "user_a", db))
        b_template = asyncio.run(PromptService.get_template("AI_DENOISING", "user_b", db))
        missing_template = asyncio.run(PromptService.get_template("AI_DENOISING", "user_c", db))

        assert a_template == "A account template"
        assert b_template == "B account template"
        assert missing_template == PromptService.AI_DENOISING
        assert all(filters.get("user_id") in {"user_a", "user_b", "user_c"} for filters in db.executed_filters)
    finally:
        _restore_modules(previous)


def test_prompt_template_response_does_not_expose_account_id() -> None:
    schema_source = (BACKEND_ROOT / "app/schemas/prompt_template.py").read_text(encoding="utf-8")
    response_block = re.search(
        r"class PromptTemplateResponse\(PromptTemplateBase\):(?P<body>.*?)(?:\n\nclass |\Z)",
        schema_source,
        re.S,
    )
    assert response_block is not None
    assert "user_id" not in response_block.group("body")


if __name__ == "__main__":
    test_prompt_service_reads_only_current_account_template()
    test_prompt_template_response_does_not_expose_account_id()
