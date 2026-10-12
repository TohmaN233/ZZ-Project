from __future__ import annotations

import json
import random
from dataclasses import replace
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from zz.cards import CARD_REGISTRY
import zz.decks as decks
from zz.web.assets import AssetIndex
from zz.web.catalog import catalog_dto
from zz.web.deck_store import DeckStore


REPRINT_PAIRS = (
    ("colorless_04_02_01_03", "colorless_04_02_02r_03"),
    ("colorless_010_02_01_00", "colorless_010_02_02r_00"),
    ("colorless_09_02_ex01_00", "colorless_09_02_02r_00"),
    ("colorless_03_02_01r_02", "colorless_03_02_02r_03"),
)
FILLER = "red_00_01_00_00"
ROOT = Path(__file__).resolve().parents[1]


def recipe_for(pair, counts):
    return {FILLER: 40 - sum(counts), **dict(zip(pair, counts))}


@pytest.mark.parametrize("pair", REPRINT_PAIRS)
def test_reprint_and_original_share_three_copy_limit(pair):
    with pytest.raises(ValueError, match=r"at most 3 copies.*got 4"):
        decks.validate_user_deck_recipe(recipe_for(pair, (2, 2)))
    decks.validate_user_deck_recipe(recipe_for(pair, (2, 1)))


@pytest.mark.parametrize("pair", REPRINT_PAIRS)
def test_catalog_declares_same_copy_identity_as_backend(pair):
    cards = {card["id"]: card for card in catalog_dto(AssetIndex(None))["cards"]}
    first, second = pair
    assert cards[first]["copyIdentity"] == cards[second]["copyIdentity"]
    assert cards[first]["copyIdentity"] == decks.deck_card_copy_identity(first)
    assert cards[first]["maxCopies"] == cards[second]["maxCopies"] == 3


def test_save_and_load_reject_mixed_four_copies(tmp_path):
    store = DeckStore(tmp_path)
    payload = {"id": "mixed", "name": "mixed", "forces": decks.AGUMA_FORCES,
               "recipe": recipe_for(REPRINT_PAIRS[0], (2, 2))}
    with pytest.raises(ValueError, match="at most 3 copies"):
        store.save_deck(payload)
    (tmp_path / "mixed.json").write_text(json.dumps(payload), encoding="utf-8")
    assert store.list_decks() == []
    payload["recipe"] = recipe_for(REPRINT_PAIRS[0], (2, 1))
    store.save_deck(payload)
    assert store.list_decks()[0]["recipe"] == payload["recipe"]


def test_load_reports_invalid_file_and_keeps_valid_decks(tmp_path):
    from zz.web.server import dispatch_api

    store = DeckStore(tmp_path)
    good = store.save_deck({"id": "good", "name": "good", "forces": decks.AGUMA_FORCES,
                            "recipe": recipe_for(REPRINT_PAIRS[0], (2, 1))})
    bad = {**good, "id": "bad", "recipe": recipe_for(REPRINT_PAIRS[0], (2, 2))}
    raw_bad = json.dumps(bad)
    (tmp_path / "bad.json").write_text(raw_bad, encoding="utf-8")
    status, payload = dispatch_api(SimpleNamespace(deck_store=lambda: store), "GET", "/api/decks", None)
    assert status == 200 and payload["decks"] == [good]
    assert payload["warnings"][0]["file"] == "bad.json"
    assert "at most 3 copies combined (got 4)" in payload["warnings"][0]["message"]
    assert (tmp_path / "bad.json").read_text(encoding="utf-8") == raw_bad
    (tmp_path / "bad.json").write_text(json.dumps(good), encoding="utf-8")
    _, repaired = dispatch_api(SimpleNamespace(deck_store=lambda: store), "GET", "/api/decks", None)
    assert repaired["warnings"] == []


def test_copy_identity_normalizes_layout_and_equivalent_timing_but_not_effects(monkeypatch):
    original = CARD_REGISTRY[REPRINT_PAIRS[0][0]]
    for card_id, ability in (
        ("red_test_copy_a", "【自分のターン】【召喚時】\\n相手のミニオン1体を破壊する。"),
        ("red_test_copy_b", "【自分のターン：召喚時】\n 相手のミニオン１体を破壊する。"),
        ("red_test_copy_c", "【自分のターン：召喚時】相手のミニオン2体を破壊する。"),
    ):
        monkeypatch.setitem(CARD_REGISTRY, card_id, replace(original, id=card_id, name_jp="同名", ability_jp=ability))
    assert decks.deck_card_copy_identity("red_test_copy_a") == decks.deck_card_copy_identity("red_test_copy_b")
    assert decks.deck_card_copy_identity("red_test_copy_a") != decks.deck_card_copy_identity("red_test_copy_c")
    decks.validate_user_deck_recipe({FILLER: 34, "red_test_copy_a": 3, "red_test_copy_c": 3})
    with pytest.raises(ValueError, match="at most 3 copies"):
        decks.validate_user_deck_recipe({FILLER: 36, "red_test_copy_a": 2, "red_test_copy_b": 2})


def test_copy_identity_uses_authoritative_japanese_text(monkeypatch):
    first, second = REPRINT_PAIRS[0]
    monkeypatch.setitem(CARD_REGISTRY, second, replace(CARD_REGISTRY[second], name_jp="stale name", ability_jp="stale text"))
    assert decks.deck_card_copy_identity(first) == decks.deck_card_copy_identity(second)


def test_unlimited_copies_remain_legal():
    decks.validate_user_deck_recipe({FILLER: 40})
    assert decks.deck_card_max_copies(FILLER) == 40


def test_unlimited_reprints_share_identity_without_three_copy_limit(monkeypatch):
    basic = CARD_REGISTRY[FILLER]
    for card_id in ("red_test_unlimited_a", "red_test_unlimited_b"):
        monkeypatch.setitem(CARD_REGISTRY, card_id, replace(basic, id=card_id))
    decks.validate_user_deck_recipe({"red_test_unlimited_a": 20, "red_test_unlimited_b": 20})
    assert decks.deck_card_copy_count({"red_test_unlimited_a": 20, "red_test_unlimited_b": 20},
                                     "red_test_unlimited_a") == 40


def test_ai_builders_stop_at_the_combined_copy_limit(monkeypatch):
    import zz.deck_ai as deck_ai
    import zz.ai_deck_analysis as analysis
    from zz.enums import Color

    first, second = REPRINT_PAIRS[0]
    saturated = {first: 2, second: 1}
    assert not deck_ai._can_add(saturated, CARD_REGISTRY[first])
    assert not deck_ai._can_add(saturated, CARD_REGISTRY[second])
    with pytest.raises(ValueError, match="not enough legal cards"):
        analysis._choose_card_for_slot([CARD_REGISTRY[first], CARD_REGISTRY[second]], random.Random(1),
                                      saturated, CARD_REGISTRY[first].type, 4)
    candidates = [CARD_REGISTRY[first], CARD_REGISTRY[second], CARD_REGISTRY[FILLER]]
    monkeypatch.setattr(deck_ai, "legal_candidate_cards", lambda constraints: candidates)
    constraints = deck_ai.DeckBuildConstraints.from_inputs(["red"], decks.AGUMA_FORCES)
    with pytest.raises(ValueError, match="at most 3 copies"):
        deck_ai.generate_completion_recipe({first: 2, second: 2, FILLER: 20}, constraints, seed=1)
    with pytest.raises(ValueError, match="unknown card id: missing"):
        deck_ai.generate_completion_recipe({first: 1, "missing": 1}, constraints, seed=1)
    completed = deck_ai.generate_completion_recipe({first: 2, second: 1, FILLER: 20}, constraints, seed=1)
    assert completed[first] == 2 and completed[second] == 1
    decks.validate_user_deck_recipe(completed)
    monkeypatch.setattr(analysis, "_candidate_pool", lambda color: candidates)
    source = analysis.DeckSpec("source", "source", recipe_for((first, second), (2, 1)), decks.AGUMA_FORCES)
    generated = analysis.generate_random_recipe([source], rng=random.Random(3), color=Color.RED)
    decks.validate_user_deck_recipe(generated)


def test_frontend_aggregates_reprints_for_add_count_and_save():
    source = (ROOT / "zz/web/static/app.js").read_text(encoding="utf-8")
    names = ("deckTotal", "deckIsValid", "deckCanAiComplete", "deckRecipeContainsUnbuildableCard",
             "deckCardMaxCopies", "deckCardCopyIdentity", "deckCardCopyCount", "deckRecipeWithinCopyLimits",
             "canAddDeckCard", "cardById", "addDeckCard", "removeDeckCard", "renderCatalogCard", "saveCurrentDeck",
             "loadSavedDecks", "renderDeckLoadWarnings")
    assert "${renderDeckLoadWarnings()}" in source[source.index("function renderDeckBuilder("):]
    functions = []
    for name in names:
        start = source.index(f"function {name}(")
        if source[start - 6:start] == "async ":
            start -= 6
        end = source.find("\nfunction ", start + 1)
        async_end = source.find("\nasync function ", start + 1)
        ends = [pos for pos in (end, async_end) if pos >= 0]
        functions.append(source[start:min(ends)] if ends else source[start:])
    harness = r"""
const assert = require('node:assert/strict');
const catalog = {cards: [
  {id:'old',copyIdentity:'shared',maxCopies:3},
  {id:'art',copyIdentity:'shared',maxCopies:3},
  {id:'other',copyIdentity:'different',maxCopies:3},
  {id:'basic',copyIdentity:'basic',maxCopies:40},
]};
let deckEditor = {recipe:{old:2,art:1,basic:37},selectedForceIds:['a','b']};
let savedDecks = [], savedDeckWarnings = [];
let apiCalls = 0;
const ZZApi = {request:async()=>{apiCalls++;return {ok:true,decks:[{id:'good'}],warnings:[{file:'bad.json',message:'at most 3 copies combined (got 4)'}]};}};
function renderPreservingDeckBuilderScroll() {}
function render() {}
const esc = String;
const t = (key,values={})=>key==='deckCopyTotal' ? `Total ${values.count} / ${values.max}` : key;
const localizedName = (card,id)=>id;
const localizedCardAssetUrl = ()=>'';
const localizedCardType = ()=>'', localizedCardAttribute = ()=>'', localizedCardSeries = ()=>'';
eval(process.argv[1]);
(async () => {
assert.equal(deckCardCopyCount('art'),3);
assert.equal(canAddDeckCard('old'),false);
assert.equal(canAddDeckCard('art'),false);
assert.equal(deckIsValid(),true);
deckEditor.recipe = {old:2,art:1};
assert.equal(canAddDeckCard('other'),true);
assert.ok(renderCatalogCard(catalog.cards[1]).includes('3 / 3'));
addDeckCard('art');
assert.equal(deckEditor.recipe.art,1);
removeDeckCard('old');
assert.equal(canAddDeckCard('art'),true);
addDeckCard('art');
assert.equal(deckEditor.recipe.art,2);
deckEditor.recipe = {old:2,art:2,basic:36};
assert.equal(deckIsValid(),false);
await saveCurrentDeck();
assert.equal(apiCalls,0);
await loadSavedDecks();
assert.equal(savedDecks[0].id,'good');
assert.equal(savedDeckWarnings[0].file,'bad.json');
assert.ok(renderDeckLoadWarnings().includes('bad.json'));
assert.ok(renderDeckLoadWarnings().includes('at most 3 copies combined (got 4)'));
deckEditor.recipe = {old:2,art:2,basic:20};
assert.equal(deckCanAiComplete(),false);
deckEditor.recipe = {old:3,other:3,basic:34};
assert.equal(deckIsValid(),true);
deckEditor.recipe = {basic:40};
assert.equal(deckIsValid(),true);
deckEditor.recipe = {basic:39};
assert.equal(canAddDeckCard('basic'),true);
})().catch(error=>{console.error(error);process.exitCode=1;});
"""
    result = subprocess.run(["node", "-e", harness, "\n".join(functions)], cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
