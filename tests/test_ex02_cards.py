"""Both printed EX02 families use the same verified executable rules."""

from __future__ import annotations

from collections import Counter
import csv
from dataclasses import fields
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools.run_semantic_scenario import ScenarioRunner
from zz.cards import CARD_REGISTRY
from zz.decks import build_deck, is_user_deck_card_id, validate_user_deck_recipe
from zz.enums import Side
from zz.model import Card, Player
from zz.pc01 import _card_from_row
from zz.web.session import GameSession
from zz.web.localization import card_translation


ROOT = Path(__file__).resolve().parents[1]
with (ROOT / "data/ex02_ex02c_equivalences.tsv").open(encoding="utf-8-sig", newline="") as handle:
    PAIRS = tuple((row["canonical_card_id"], row["variant_card_id"]) for row in csv.DictReader(handle, delimiter="\t"))
with (ROOT / "data/cards_bilingual_v4.tsv").open(encoding="utf-8-sig", newline="") as handle:
    ROWS = {row["image_id"]: row for row in csv.DictReader(handle, delimiter="\t")}
ORIGINAL_BY_VARIANT = {variant: original for original, variant in PAIRS}
SCENARIOS = tuple(sorted((ROOT / "tests/semantic_scenarios/ex02c").glob("*.json")))


@pytest.mark.parametrize("original,variant", PAIRS)
def test_printed_faces_share_rules_and_keep_their_own_metadata(original, variant):
    card, counterpart = CARD_REGISTRY[original], CARD_REGISTRY[variant]
    printed = _card_from_row(ROWS[original], infer_effects=False)
    for name in ("id", "name_jp", "name_en", "ability_jp", "ability_en", "race_jp", "cost", "type", "bp", "dp"):
        assert getattr(card, name) == getattr(printed, name)
    assert card is not counterpart
    for field in fields(Card):
        value = getattr(counterpart, field.name)
        if callable(value):
            assert getattr(card, field.name) is value
        elif isinstance(value, (list, dict)):
            assert getattr(card, field.name) is not value
    assert len(card.effects) == len(counterpart.effects)
    for effect, shared in zip(card.effects, counterpart.effects):
        assert effect is not shared and effect.params is not shared.params
        assert effect.fn is shared.fn and effect.condition is shared.condition


@pytest.mark.parametrize("original,variant", PAIRS)
def test_mixed_printed_faces_really_share_the_copy_limit(original, variant):
    if not is_user_deck_card_id(original):
        assert not is_user_deck_card_id(variant)
        return
    filler = "red_00_01_00_00"
    recipe = {filler: 37, original: 1, variant: 2}
    validate_user_deck_recipe(recipe)
    deck = build_deck(recipe, Player("test", Side.P1))
    counts = Counter(card.card.id for card in deck)
    assert counts[original] == 1 and counts[variant] == 2
    with pytest.raises(ValueError, match="at most 3 copies"):
        validate_user_deck_recipe({filler: 36, original: 2, variant: 2})


@pytest.mark.parametrize("original,variant", PAIRS)
def test_original_effect_prompts_keep_complete_own_face_text(original, variant):
    session = GameSession.__new__(GameSession)
    original_ci = SimpleNamespace(card=CARD_REGISTRY[original])
    variant_ci = SimpleNamespace(card=CARD_REGISTRY[variant])
    for effect, shared in zip(original_ci.card.effects, variant_ci.card.effects):
        if session._effect_event_texts(variant_ci, shared):
            assert session._effect_event_texts(original_ci, effect), (original, effect.timing)
    if original == "green_08_02_EX02_00":
        texts = [session._effect_event_texts(original_ci, effect).get("jp", "") for effect in original_ci.card.effects]
        assert "召喚時" in texts[0] and "絶対零度" in texts[1]
        assert "ユージオ" not in "".join(texts)


@pytest.mark.parametrize("original,prefix", [
    ("red_00_01_EX02_02", "加护：「剑」＋费用4以上"),
    ("green_00_01_EX02_01", "加护：费用4以上"),
    ("green_00_01_EX02_02", "加护：「剑」＋费用4以上"),
    ("colorless_00_01_EX02_00", "加护：「黑衣剑士」"),
    ("green_05_02_EX02_00", "连携：「道具」"),
    ("red_07_02_EX02_00", "袭击"),
    ("yellow_04_02_EX02_00", "飞来"),
    ("colorless_08_02_EX02_01", "飞来"),
])
def test_translated_keyword_lines_match_the_verified_faces(original, prefix):
    variant = dict(PAIRS)[original]
    for card_id in (original, variant):
        text = card_translation(card_id)["ability_zh"]
        assert text.startswith(prefix), card_id
        assert "EPIC" not in text


def _original_spec(value):
    if isinstance(value, dict):
        return {key: _original_spec(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_original_spec(item) for item in value]
    if isinstance(value, str):
        return ORIGINAL_BY_VARIANT.get(value, value)
    return value


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda path: path.stem)
def test_original_face_through_the_real_semantic_actions(scenario, tmp_path):
    spec = _original_spec(json.loads(scenario.read_text(encoding="utf-8")))
    spec["scenario_id"] = "ex02_original_" + scenario.stem
    spec["official_rule"] = CARD_REGISTRY[spec["card_id"]].ability_jp
    if not spec["official_rule"]:
        card = CARD_REGISTRY[spec["card_id"]]
        assert not card.effects and not card.triggers
        spec["official_rule"] = f"効果欄なし：{card.name_jp}、BP{card.bp}/DP{card.dp}"
    target = tmp_path / "original.json"
    target.write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
    assert ScenarioRunner(target, ROOT).run()["result"] == "passed"


@pytest.mark.parametrize("original_source", [True, False])
def test_named_magic_can_recover_the_other_printed_face(tmp_path, original_source):
    spec = json.loads((ROOT / "tests/semantic_scenarios/ex02c/yellow_03_03_02c_00-positive.json").read_text(encoding="utf-8"))
    variant = "yellow_03_03_02c_00"
    original = ORIGINAL_BY_VARIANT[variant]
    if original_source:
        spec = _original_spec(spec)
    source, recovered = (original, variant) if original_source else (variant, original)
    spec["setup"].append({"path": "/api/debug/add-card", "payload": {"cardId": recovered, "side": "P1", "zone": "trash"}})
    spec["actions"][-1]["select"]["cardId"] = recovered
    spec["assertions"] = [
        {"name": "The counterpart returns to Hand", "path": "state.players.human.hand", "op": "count_where", "value": 1, "where": {"cardId": recovered}},
        {"name": "The cast source remains in Trash", "path": "state.players.human.trash", "op": "count_where", "value": 1, "where": {"cardId": source}},
    ]
    target = tmp_path / "mixed.json"
    target.write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
    assert ScenarioRunner(target, ROOT).run()["result"] == "passed"


@pytest.mark.parametrize("original_source", [True, False])
def test_named_minion_can_recover_the_other_printed_face(tmp_path, original_source):
    spec = json.loads((ROOT / "tests/semantic_scenarios/ex02c/colorless_08_02_02c_00-positive.json").read_text(encoding="utf-8"))
    variant = "colorless_08_02_02c_00"
    original = ORIGINAL_BY_VARIANT[variant]
    if original_source:
        spec = _original_spec(spec)
    source, recovered = (original, variant) if original_source else (variant, original)
    step = next(step for step in spec["setup"] if step.get("payload", {}).get("zone") == "trash")
    step["payload"]["cardId"] = recovered
    spec["assertions"][0]["where"]["cardId"] = recovered
    spec["assertions"][1]["where"]["cardId"] = source
    target = tmp_path / "mixed-minion.json"
    target.write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
    assert ScenarioRunner(target, ROOT).run()["result"] == "passed"


@pytest.mark.parametrize("scenario", [
    path for path in SCENARIOS
    if path.name.startswith(("green_08_02_02c_00-", "yellow_07_02_02c_00-", "red_07_02_02c_02-", "yellow_03_03_02c_00-"))
], ids=lambda path: path.stem)
def test_shared_rule_changes_preserve_the_variant_scenarios(scenario):
    assert ScenarioRunner(scenario, ROOT).run()["result"] == "passed"
