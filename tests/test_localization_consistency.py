from __future__ import annotations

import csv
import json
import re
from pathlib import Path

from tools.run_semantic_scenario import ScenarioRunner
from zz.card_identity import explicit_card_equivalence_pairs
from zz.cards import CARD_REGISTRY
from zz.decks import is_user_deck_card_id
from zz.enums import AreaType
from zz.forces import F_CYCLOPS
from zz.model import CardInstance
from zz.web.assets import AssetIndex
from zz.web.catalog import catalog_dto
from zz.web.localization import card_translation, card_translations, force_translations
from zz.web.serialize import serialize_card
from zz.web.server import RULEBOOK_FILES
from zz.web.session import GameSession


ROOT = Path(__file__).resolve().parents[1]
APP_JS = ROOT / "zz" / "web" / "static" / "app.js"
RULES_ROOT = ROOT / "docs" / "rules"


def test_sao_reuses_equivalent_english_effects_in_catalog_details_and_prompts() -> None:
    catalog = {row["id"]: row for row in catalog_dto(AssetIndex(None))["cards"]}
    session = GameSession(seed=702, mode="god")
    owner = session.engine.state.players[0]
    pairs = explicit_card_equivalence_pairs()
    names = {CARD_REGISTRY[a].name_en: CARD_REGISTRY[b].name_jp for a, b in pairs}
    for original, variant in pairs:
        source, card = CARD_REGISTRY[original], CARD_REGISTRY[variant]
        expected = source.ability_en
        for english, japanese in sorted(names.items(), key=lambda item: len(item[0]), reverse=True):
            expected = expected.replace(english, japanese)
        assert expected or not source.ability_jp, original
        translation = card_translation(variant)
        assert translation["ability_en"] == expected, variant
        assert catalog[variant]["abilityEn"] == expected, variant
        ci = CardInstance(card, owner, iid=session.engine.state.allocate_iid(), area=AreaType.HAND)
        detail = serialize_card(session.engine, ci, session.asset_index)
        assert detail["abilityEn"] == expected, variant
        assert detail["abilityJp"] == catalog[variant]["abilityJp"]
        assert detail["abilityZh"] == catalog[variant]["abilityZh"] == card_translations()[variant]["ability_zh"]
        assert detail["nameJp"] == catalog[variant]["nameJp"] == card.name_jp
        assert detail["nameEn"] == catalog[variant]["nameEn"] == ""
        assert detail["assetId"] == variant
        assert "ability_en" not in card_translations()[variant]
        for effect in card.effects:
            fields = session._effect_text_fields(ci, effect)
            if fields:
                assert fields["effectTextEn"], (variant, effect.timing)
                assert fields["effectTextEn"] in expected
        hidden = serialize_card(session.engine, ci, session.asset_index, face_down=True)
        assert "abilityEn" not in hidden


def test_sao_english_named_effects_use_sao_targets_and_originals_stay_original() -> None:
    assert card_translation("red_00_01_02c_01")["ability_en"].startswith("Boost: Cost 3 or Higher\n")
    targets = {
        "red_07_02_02c_02": '"「双剣」キリト"',
        "yellow_07_02_02c_00": '"「絶剣」ユウキ"',
        "green_08_02_02c_00": '"「整合騎士」ユージオ"',
        "yellow_03_03_02c_00": '"スピードホリック"',
        "colorless_08_02_02c_00": "ソードゴーレム",
    }
    for card_id, target in targets.items():
        assert target in card_translation(card_id)["ability_en"]
    catalog = {row["id"]: row for row in catalog_dto(AssetIndex(None))["cards"]}
    for original, _variant in explicit_card_equivalence_pairs():
        assert catalog[original]["abilityEn"].replace("\\n", "\n") == CARD_REGISTRY[original].ability_en
    assert '"Lightning Speed"' in CARD_REGISTRY["yellow_03_03_EX02_00"].ability_en
    assert "ability_en" not in card_translation("red_02_03_02r_01")


def test_sao_english_effect_reaches_a_real_magic_target_prompt() -> None:
    runner = ScenarioRunner(ROOT / "tests/semantic_scenarios/ex02c/yellow_03_03_02c_00-positive.json", ROOT)
    for call in runner.spec["setup"]:
        response = runner._apply_setup(call)
        runner._apply_captures(response, call)
    runner._run_action(runner.spec["actions"][0])
    prompt = runner.session.prompt
    assert prompt["kind"] == "effect_target"
    assert "[Main]" in prompt["effectTextEn"]
    assert '"スピードホリック"' in prompt["effectTextEn"]
    assert prompt["card"]["abilityEn"] == card_translation("yellow_03_03_02c_00")["ability_en"]


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
    playable_card_ids = {
        card_id
        for card_id in CARD_REGISTRY
        if is_user_deck_card_id(card_id)
    }
    with (ROOT / "data" / "official_cardlist.tsv").open(encoding="utf-8-sig", newline="") as handle:
        official_rows = list(csv.DictReader(handle, delimiter="\t"))
        official_pc02r_ids = {row["image_id"] for row in official_rows if row["pack_jp_official"] == "PC:02R DIVINE"}
        official_card_ids = {row["image_id"] for row in official_rows}
    expected_card_ids = playable_card_ids | official_pc02r_ids

    assert expected_card_ids <= set(cards) <= official_card_ids | playable_card_ids
    assert all(row.get("name_zh") and row.get("ability_zh") for row in cards.values())
    assert len(forces) == 10
    assert all(row.get("name_zh") and row.get("ability_zh") for row in forces.values())
    assert all(row.get("name_en") and row.get("ability_en") for row in forces.values())


def test_cyclops_uses_100_bp_in_code_translations_and_all_rulebooks() -> None:
    force = force_translations()["force_e"]
    assert "+100" in F_CYCLOPS.ability_jp
    assert "+200" not in F_CYCLOPS.ability_jp
    assert "+100" in force["ability_zh"]
    assert "+100" in force["ability_en"]
    assert "+200" not in force["ability_zh"]
    assert "+200" not in force["ability_en"]

    for filename in RULEBOOK_FILES.values():
        text = (RULES_ROOT / filename).read_text(encoding="utf-8")
        cyclops_line = next(
            line for line in text.splitlines()
            if "Cyclops" in line or "サイクロプス" in line
        )
        assert "+100" in cyclops_line
        assert "+200" not in cyclops_line


def test_selectable_characters_have_names_in_all_three_languages() -> None:
    manifest = json.loads((
        ROOT / "asserts" / "images" / "clean_graph" / "characters" / "characters.json"
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
