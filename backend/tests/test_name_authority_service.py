import json
from types import SimpleNamespace

from app.services.name_authority_service import (
    build_name_authority,
    is_generic_reference,
    normalize_name,
)


def test_filters_generic_references():
    assert is_generic_reference("她")
    assert is_generic_reference("那个人")
    assert is_generic_reference("前辈")
    assert not is_generic_reference("晓卡")


def test_resolves_ids_aliases_and_middle_dot_names():
    character = SimpleNamespace(
        id="char-1",
        project_id="project-1",
        name="阿尔伯特·爱因斯坦",
        traits=json.dumps({"aliases": ["爱因斯坦博士", "老爱"]}, ensure_ascii=False),
        is_organization=False,
    )
    authority = build_name_authority([character])

    assert authority.resolve_name("char-1") == "阿尔伯特·爱因斯坦"
    assert authority.resolve_name("爱因斯坦") == "阿尔伯特·爱因斯坦"
    assert authority.resolve_name("爱因斯坦博士") == "阿尔伯特·爱因斯坦"
    assert authority.resolve_name("「老爱」") == "阿尔伯特·爱因斯坦"


def test_ambiguous_alias_keeps_unknown_or_drops_in_strict_mode():
    first = SimpleNamespace(
        id="c1",
        project_id="p",
        name="威廉二世",
        traits=json.dumps({"aliases": ["威廉"]}, ensure_ascii=False),
        is_organization=False,
    )
    second = SimpleNamespace(
        id="c2",
        project_id="p",
        name="威廉三世",
        traits=json.dumps({"aliases": ["威廉"]}, ensure_ascii=False),
        is_organization=False,
    )
    authority = build_name_authority([first, second])

    assert authority.resolve_name("威廉") == "威廉"
    assert authority.resolve_name("威廉", keep_unknown=False) is None


def test_plain_trait_list_is_not_treated_as_aliases():
    character = SimpleNamespace(
        id="c1",
        project_id="p",
        name="晓卡",
        traits=json.dumps(["勇敢", "聪明"], ensure_ascii=False),
        is_organization=False,
    )
    authority = build_name_authority([character])

    assert authority.resolve_name("勇敢", keep_unknown=False) is None


def test_normalize_name_strips_wrappers_and_spaces():
    assert normalize_name(" 「 晓 卡 」 ") == "晓卡"


if __name__ == "__main__":
    test_filters_generic_references()
    test_resolves_ids_aliases_and_middle_dot_names()
    test_ambiguous_alias_keeps_unknown_or_drops_in_strict_mode()
    test_plain_trait_list_is_not_treated_as_aliases()
    test_normalize_name_strips_wrappers_and_spaces()
