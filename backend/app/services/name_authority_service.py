"""Name authority helpers for existing character/organization data.

This module deliberately stays read-only: it builds a resolver from the current
Character rows and avoids introducing a separate alias table. Downstream
analysis can use it to filter generic references and map aliases to canonical
character names.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Iterable, Optional

if TYPE_CHECKING:
    from app.models.character import Character


GENERIC_REFERENCES = {
    "他", "她", "它", "他们", "她们", "它们", "自己", "本人", "对方", "那人", "这个人", "那个人",
    "男人", "女人", "男孩", "女孩", "少年", "少女", "青年", "老人", "老者", "中年人", "孩子",
    "大家", "众人", "所有人", "旁人", "路人", "敌人", "同伴", "队友", "船员", "士兵", "军官",
    "老师", "同学", "前辈", "后辈", "大哥", "大姐", "叔叔", "阿姨", "父亲", "母亲",
    "哥哥", "姐姐", "弟弟", "妹妹", "老板", "店员", "医生", "护士", "警察", "司机",
    "某人", "此人", "这人", "那人", "这位", "那位", "那个男人", "那个女人", "年轻人",
    "年轻男子", "年轻女子", "青年男子", "青年女子", "中年男子", "中年女子",
    "女子", "男子", "姑娘", "小姐", "公子", "少爷", "先生", "夫人", "掌柜", "小二",
    "店主", "店家", "客人", "客官", "使者", "信使", "弟子", "师父", "师傅", "师兄",
    "师弟", "师姐", "师妹", "道友", "仙子", "仙师", "小友", "阁下", "老夫", "在下",
    "妾身", "主人", "大人", "长老", "掌门", "帮主", "教主", "堂主", "队长", "领队",
}


def normalize_name(value: Any) -> str:
    """Normalize whitespace and quote-like wrappers without changing semantics."""
    text = str(value or "").strip()
    text = re.sub(r"\s+", "", text)
    return text.strip("「」『』“”‘’\"'`（）()[]【】<>《》")


def is_generic_reference(value: Any) -> bool:
    """Return true for pronouns and role-like placeholders that should not become entities."""
    text = normalize_name(value)
    if not text:
        return True
    if text in GENERIC_REFERENCES:
        return True
    if len(text) <= 1:
        return True
    return bool(
        re.fullmatch(
            r"(?:这|那|某)?(?:个|位|名|些)?"
            r"(?:人|男人|女人|男孩|女孩|少年|少女|青年|老人|老者|孩子|老师|同学|前辈|后辈|"
            r"大哥|大姐|叔叔|阿姨|父亲|母亲|哥哥|姐姐|弟弟|妹妹|队友|同伴|敌人|船员|士兵|军官)",
            text,
        )
    )


def _safe_json(value: Any) -> Any:
    if not value:
        return None
    if isinstance(value, (list, dict)):
        return value
    if not isinstance(value, str):
        return None
    try:
        return json.loads(value)
    except Exception:
        return None


def _iter_alias_values(value: Any, *, trusted: bool = False) -> Iterable[str]:
    """Extract likely alias values from flexible JSON/list structures."""
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if trusted else []
    if isinstance(value, list):
        items: list[str] = []
        for item in value:
            items.extend(_iter_alias_values(item, trusted=trusted))
        return items
    if isinstance(value, dict):
        items: list[str] = []
        for key, item in value.items():
            key_text = str(key).lower()
            if key_text in {"alias", "aliases", "别名", "昵称", "称呼", "称号", "name_aliases"}:
                items.extend(_iter_alias_values(item, trusted=True))
        return items
    return []


def extract_character_aliases(character: "Character") -> set[str]:
    """Build conservative aliases for a character without guessing too much."""
    aliases = {normalize_name(character.name)}

    for value in _iter_alias_values(_safe_json(character.traits)):
        aliases.add(normalize_name(value))

    name = normalize_name(character.name)
    if "·" in name or "•" in name or "・" in name:
        parts = [part for part in re.split(r"[·•・]", name) if part]
        aliases.add("".join(parts))
        if parts and len(parts[-1]) >= 2:
            aliases.add(parts[-1])

    return {alias for alias in aliases if alias and not is_generic_reference(alias)}


@dataclass
class NameAuthority:
    id_to_name: dict[str, str] = field(default_factory=dict)
    canonical_names: set[str] = field(default_factory=set)
    alias_to_name: dict[str, str] = field(default_factory=dict)
    ambiguous_aliases: set[str] = field(default_factory=set)

    def resolve_name(self, value: Any, *, keep_unknown: bool = True) -> Optional[str]:
        text = normalize_name(value)
        if not text or is_generic_reference(text):
            return None
        if text in self.id_to_name:
            return self.id_to_name[text]
        if text in self.canonical_names:
            return text
        if text in self.ambiguous_aliases:
            return text if keep_unknown else None
        canonical = self.alias_to_name.get(text)
        if canonical:
            return canonical
        return text if keep_unknown else None

    def resolve_names(self, values: Any, *, keep_unknown: bool = True) -> list[str]:
        if not values:
            return []
        if not isinstance(values, (list, tuple, set)):
            values = [values]

        result: list[str] = []
        for value in values:
            resolved = self.resolve_name(value, keep_unknown=keep_unknown)
            if resolved and resolved not in result:
                result.append(resolved)
        return result


def build_name_authority(characters: Iterable["Character"], *, include_organizations: bool = True) -> NameAuthority:
    """Build a canonical name resolver from current project characters."""
    authority = NameAuthority()
    alias_candidates: dict[str, set[str]] = {}

    for character in characters:
        if character.is_organization and not include_organizations:
            continue
        canonical = normalize_name(character.name)
        if not canonical or is_generic_reference(canonical):
            continue

        authority.id_to_name[character.id] = canonical
        authority.canonical_names.add(canonical)
        for alias in extract_character_aliases(character):
            alias_candidates.setdefault(alias, set()).add(canonical)

    for alias, canonical_names in alias_candidates.items():
        if len(canonical_names) == 1:
            authority.alias_to_name[alias] = next(iter(canonical_names))
        else:
            authority.ambiguous_aliases.add(alias)

    return authority
