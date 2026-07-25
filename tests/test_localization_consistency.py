from __future__ import annotations

import re
import json
from pathlib import Path

from zz.web.localization import card_translations, force_translations
from zz.web.server import RULEBOOK_FILES


ROOT = Path(__file__).resolve().parents[1]
APP_JS = ROOT / "zz" / "web" / "static" / "app.js"
RULES_ROOT = ROOT / "docs" / "rules"


def _ui_keys_by_language() -> dict[str, set[str]]:
    source = APP_JS.read_text(encoding="utf-8")
    start = source.index("const UI_TEXT = {")
    end = source.index("\n};", start)
    block = source[start:end]
    result: dict[str, set[str]] = {}
    for language in ("zh", "ja", "en"):
        language_start = block.index(f"  {language}: {{")
        next_starts = [
            block.find(f"  {candidate}: {{", language_start + 1)
            for candidate in ("zh", "ja", "en")
        ]
        language_end = min(value for value in next_starts if value >= 0) if any(
            value >= 0 for value in next_starts
        ) else len(block)
        result[language] = set(re.findall(
            r"(?m)^    ([A-Za-z0-9_]+):",
            block[language_start:language_end],
        ))
    return result


def test_all_ui_languages_define_the_same_keys() -> None:
    keys = _ui_keys_by_language()
    assert keys["zh"] == keys["ja"] == keys["en"]


def test_frontend_does_not_fall_back_to_another_content_language() -> None:
    source = APP_JS.read_text(encoding="utf-8")
    localized_name = source.split("function localizedName", 1)[1].split("\n}", 1)[0]
    localized_ability = source.split("function localizedAbility", 1)[1].split("\n}", 1)[0]

    assert "item.nameZh || item.nameJp" not in localized_name
    assert "item.nameEn || item.nameJp" not in localized_name
    assert "item.abilityZh || item.abilityJp" not in localized_ability
    assert "item.abilityEn || item.abilityJp" not in localized_ability
    assert 'return `/rules/${currentLanguage()}`' in source


def test_packaged_translations_are_available_without_external_workspace_files() -> None:
    cards = card_translations()
    forces = force_translations()

    assert len(cards) == 219
    assert all(row.get("name_zh") for row in cards.values())
    assert len(forces) == 10
    assert all(row.get("name_zh") and row.get("ability_zh") for row in forces.values())
    assert all(row.get("name_en") and row.get("ability_en") for row in forces.values())


def test_selectable_characters_have_names_in_all_three_languages() -> None:
    manifest = json.loads((
        ROOT / "asserts" / "images" / "clean_graph" / "chara" / "characters.json"
    ).read_text(encoding="utf-8"))
    selectable = [
        row for row in manifest["characters"]
        if row.get("role") in {"codeman", "guest_character"}
    ]

    assert selectable
    assert all(row.get("name_ja") for row in selectable)
    assert all(row.get("name_zh") for row in selectable)
    assert all(row.get("name_en") for row in selectable)


def test_each_language_has_its_own_rulebook_with_shared_rules_invariants() -> None:
    assert RULEBOOK_FILES == {
        "zh": "zz_rulebook_zh.md",
        "ja": "zz_rulebook_ja.md",
        "en": "zz_rulebook_en.md",
    }
    texts = {
        language: (RULES_ROOT / filename).read_text(encoding="utf-8")
        for language, filename in RULEBOOK_FILES.items()
    }
    invariants = {
        "zh": ["40 张", "2 张 Force", "玩家生命 = 12", "Base 上限为 10", "Field 上限为 5", "手牌上限为 10", "先攻第 1 回合不抽卡", "先攻第 1 回合不能攻击"],
        "ja": ["40枚", "フォース2枚", "プレイヤーライフ = 12", "ベースの上限は10", "フィールドの上限は5", "手札の上限は10", "先攻1ターン目はドローしない", "先攻1ターン目は攻撃できない"],
        "en": ["40-card", "two Forces", "Player life = 12", "Base limit is 10", "Field limit is five", "hand limit is 10", "first player does not draw on turn 1", "first player cannot attack on turn 1"],
    }
    for language, phrases in invariants.items():
        assert all(phrase in texts[language] for phrase in phrases), language
        assert len(re.findall(r"(?m)^## \d+\.", texts[language])) == 14
