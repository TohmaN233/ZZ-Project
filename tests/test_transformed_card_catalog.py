import pytest

from zz.cards import CARD_REGISTRY
from zz.decks import (
    AGUMA_RED_RECIPE,
    build_deck,
    is_user_deck_card_id,
    validate_recipe,
    validate_user_deck_recipe,
)
from zz.enums import CardType, Side
from zz.model import Card, Player
from zz.web.assets import AssetIndex
from zz.web.catalog import catalog_dto


ANJU_BASE = "colorless_04_02_02r_01"
ANJU_FORMS = (
    "red_04_02_02r_01",
    "yellow_04_02_02r_01",
    "purple_04_02_02r_00",
    "green_04_02_02r_01",
    "blue_04_02_02r_02",
    "white_04_02_02r_00",
)
GIANT_FORMS = {
    "red_07_02_02r_00": "red_07_02_02r_01",
    "blue_07_02_02r_00": "blue_07_02_02r_01",
    "green_07_02_02r_00": "green_07_02_02r_01",
    "white_07_02_02r_00": "white_07_02_02r_01",
    "yellow_07_02_02r_00": "yellow_07_02_02r_01",
    "purple_07_02_02r_00": "purple_07_02_02r_01",
}
TRANSFORMED_IDS = (*ANJU_FORMS, *GIANT_FORMS.values())


@pytest.fixture(scope="module")
def catalog_cards():
    return {card["id"]: card for card in catalog_dto(AssetIndex(None))["cards"]}


@pytest.mark.parametrize("card_id", TRANSFORMED_IDS)
def test_transformed_cards_cannot_be_selected_or_enter_any_deck(card_id):
    assert not is_user_deck_card_id(card_id)
    recipe = dict(AGUMA_RED_RECIPE)
    recipe["red_00_01_00_00"] -= 1
    recipe[card_id] = 1
    for validator in (validate_recipe, validate_user_deck_recipe):
        with pytest.raises(ValueError, match="not deck-buildable"):
            validator(recipe)
    with pytest.raises(ValueError, match="not deck-buildable"):
        build_deck(recipe, Player("test", Side.P1))


@pytest.mark.parametrize("card_id", TRANSFORMED_IDS)
def test_transformed_details_remain_in_catalog_but_are_not_searchable(catalog_cards, card_id):
    details = catalog_cards[card_id]
    assert details["deckBuildable"] is False
    assert card_id not in {card["id"] for card in catalog_cards.values() if card["deckBuildable"]}
    assert details["nameJp"]
    assert details["abilityJp"]
    assert details["bp"] == CARD_REGISTRY[card_id].bp
    assert details["dp"] == CARD_REGISTRY[card_id].dp
    assert details["effectSpecs"]
    assert "assetUrl" in details and "assetUrlEn" in details


def test_anju_and_giant_transformation_links_are_registered(catalog_cards):
    assert set(catalog_cards[ANJU_BASE]["transformationIds"]) == set(ANJU_FORMS)
    for form in ANJU_FORMS:
        assert set(catalog_cards[form]["transformationIds"]) == set(ANJU_FORMS) - {form}
    for base, transformed in GIANT_FORMS.items():
        assert catalog_cards[base]["transformationIds"] == [transformed]
        assert catalog_cards[transformed]["transformationIds"] == []
    for card in catalog_cards.values():
        assert isinstance(card["deckBuildable"], bool)
        assert isinstance(card["transformationIds"], list)
        assert set(card["transformationIds"]) <= catalog_cards.keys()


@pytest.mark.parametrize("card_id", (ANJU_BASE, *GIANT_FORMS))
def test_base_forms_remain_legal_for_deck_building(catalog_cards, card_id):
    assert is_user_deck_card_id(card_id)
    assert catalog_cards[card_id]["deckBuildable"] is True
    recipe = dict(AGUMA_RED_RECIPE)
    recipe["red_00_01_00_00"] -= 1
    recipe[card_id] = 1
    validate_user_deck_recipe(recipe)
    assert len(build_deck(recipe, Player("test", Side.P1))) == 40


@pytest.mark.parametrize("validator", (validate_recipe, validate_user_deck_recipe, build_deck))
def test_preset_and_user_validation_reject_transformed_form(validator):
    recipe = dict(AGUMA_RED_RECIPE)
    recipe["red_00_01_00_00"] -= 1
    recipe[ANJU_FORMS[0]] = 1
    with pytest.raises(ValueError, match="not deck-buildable"):
        if validator is build_deck:
            validator(recipe, Player("test", Side.P1))
        else:
            validator(recipe)


@pytest.mark.parametrize("token_type", (CardType.F_MINION, CardType.MANA_TOKEN))
def test_official_prefixed_tokens_cannot_enter_decks_or_catalog(monkeypatch, token_type):
    card_id = "red_test_token"
    monkeypatch.setitem(CARD_REGISTRY, card_id, Card(
        id=card_id, name_jp="token", name_en="token", type=token_type,
        is_token=token_type is CardType.F_MINION,
    ))
    assert not is_user_deck_card_id(card_id)
    with pytest.raises(ValueError, match="not deck-buildable"):
        validate_recipe({card_id: 40})
    assert card_id not in {card["id"] for card in catalog_dto(AssetIndex(None))["cards"]}


def test_explicit_deck_metadata_controls_all_validation_paths(monkeypatch):
    card_id = "red_test_unbuildable"
    monkeypatch.setitem(CARD_REGISTRY, card_id, Card(
        id=card_id, name_jp="test", name_en="test", type=CardType.F_MINION,
        deck_buildable=False,
    ))
    assert not is_user_deck_card_id(card_id)
    with pytest.raises(ValueError, match="not deck-buildable"):
        validate_recipe({card_id: 40})
    with pytest.raises(ValueError, match="not deck-buildable"):
        build_deck({card_id: 40}, Player("test", Side.P1))
    details = next(card for card in catalog_dto(AssetIndex(None))["cards"] if card["id"] == card_id)
    assert details["deckBuildable"] is False
    assert details["transformationIds"] == []


def test_transformation_registration_fails_when_a_target_is_missing(monkeypatch):
    from zz.pc02r import _register_transformation_metadata

    monkeypatch.delitem(CARD_REGISTRY, ANJU_FORMS[0])
    with pytest.raises(RuntimeError, match=f"transformation card is not registered:.*{ANJU_FORMS[0]}"):
        _register_transformation_metadata()


@pytest.mark.parametrize("card_id", TRANSFORMED_IDS)
@pytest.mark.parametrize("zone", ("hand", "field", "base", "deck", "trash", "removed"))
def test_debug_cannot_create_transformed_faces_in_any_zone(card_id, zone):
    from zz.web.debug_tools import add_debug_card_to_zone, setup_debug_lab
    from zz.web.session import GameSession

    session = GameSession(seed=908, mode="god")
    setup_debug_lab(session, ANJU_BASE, zone="field", compact_board=True)
    before = session.state_dto()
    for create in (
        lambda: setup_debug_lab(session, card_id, zone=zone),
        lambda: add_debug_card_to_zone(session, card_id, side="P1", zone=zone),
    ):
        with pytest.raises(ValueError, match="transformation-only card cannot be created directly"):
            create()
        assert session.state_dto() == before


def test_debug_can_move_a_face_created_by_actual_bless_back_to_hand():
    from zz.enums import AreaType
    from zz.web.debug_tools import add_debug_card_to_zone, move_debug_card, setup_debug_lab
    from zz.web.session import GameSession

    session = GameSession(seed=908, mode="god")
    setup_debug_lab(session, ANJU_BASE, zone="field", compact_board=True, non_minion_mana_only=True)
    owner = session.engine.state.players[0]
    host = owner.field[0]
    mana_id = add_debug_card_to_zone(session, "red_00_01_02_00", side="P1", zone="base")["added"]["iid"]
    mana = next(card for card in owner.base if card.iid == mana_id)
    action_id = next(option_id for option_id, action in session._options.items()
                     if action.kind == "bless" and action.payload["iid"] == mana.iid
                     and action.payload["target_iid"] == host.iid)
    session.choose(session.prompt["id"], action_id)
    assert host.card.id == ANJU_FORMS[0]
    assert mana.area is AreaType.BASE and mana.rested
    moved = move_debug_card(session, host.iid, zone="hand")
    assert moved["moved"]["cardId"] == ANJU_FORMS[0]
    assert host in owner.hand and host.card.id == ANJU_FORMS[0]
    assert not is_user_deck_card_id(host.card.id)


def test_debug_still_rejects_tokens(monkeypatch):
    from zz.web.debug_tools import add_debug_card_to_zone, setup_debug_lab
    from zz.web.session import GameSession

    session = GameSession(seed=908, mode="god")
    token_id = "red_debug_token"
    monkeypatch.setitem(CARD_REGISTRY, token_id, Card(
        id=token_id, name_jp="token", name_en="token", type=CardType.F_MINION, is_token=True,
    ))
    with pytest.raises(ValueError, match="unknown debug card id"):
        setup_debug_lab(session, token_id, zone="field")
    with pytest.raises(ValueError, match="unknown debug card id"):
        add_debug_card_to_zone(session, token_id, side="P1", zone="field")


def test_semantic_fixture_validates_the_edge_and_resolves_the_transform_event():
    from pathlib import Path
    from tools.run_semantic_scenario import ScenarioError, ScenarioRunner
    from zz.enums import AreaType, Keyword

    root = Path(__file__).resolve().parents[1]
    runner = ScenarioRunner(root / "tests/semantic_scenarios/pc02r/white_07_02_02r_01-boundary.json", root)
    runner._apply_setup(runner.spec["setup"][0])
    host = runner.session.engine.state.players[0].field[0]
    before = runner.session.state_dto()
    with pytest.raises(ScenarioError, match="unverified fixture transformation"):
        runner._transform_fixture({"iid": host.iid, "sourceId": host.card.id, "targetId": ANJU_FORMS[0]})
    with pytest.raises(ScenarioError, match="source does not match"):
        runner._transform_fixture({"iid": host.iid, "sourceId": ANJU_BASE, "targetId": ANJU_FORMS[0]})
    assert runner.session.state_dto() == before

    runner._transform_fixture({"iid": host.iid, "sourceId": host.card.id, "targetId": GIANT_FORMS[host.card.id]})
    assert host.card.id == GIANT_FORMS["white_07_02_02r_00"]
    assert host.permanent_bp_mod == 100
    assert Keyword.REAWAKEN in host.extra_keywords
    runner._return_fixture_to_hand({"iid": host.iid})
    assert host.area is AreaType.HAND
    assert host.card.id == GIANT_FORMS["white_07_02_02r_00"]
    assert host.permanent_bp_mod == 0
    assert Keyword.REAWAKEN not in host.extra_keywords


def test_all_named_japanese_transformation_clauses_and_faces_are_covered():
    import csv
    import re
    from pathlib import Path
    from zz.transformations import transformation_graph
    root = Path(__file__).resolve().parents[1]
    with (root / "data/cards_bilingual_v4.tsv").open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    graph = transformation_graph()
    products = {target for targets in graph.values() for target in targets}
    assert len(products) == 24
    for row in rows:
        text = row["ability_jp"].replace("\\n", "").replace("\n", "")
        if "に変形する" in text or "大変身" in text:
            assert row["image_id"] in graph, row["image_id"]
        # A rule destroying cards that have this timing is not a transformed face.
        if re.match(r"^(?:襲撃)?【変形時】", text):
            assert row["image_id"] in products, row["image_id"]


def test_registering_future_pack_forms_uses_shared_transformation_metadata(monkeypatch):
    from zz.cards import register
    source_id, target_id = "blue_03_01_03_00", "blue_03_01_03_01"
    monkeypatch.setitem(CARD_REGISTRY, source_id, None)
    monkeypatch.setitem(CARD_REGISTRY, target_id, None)
    source = register(Card(source_id, "source", "source", CardType.F_MINION))
    target = register(Card(target_id, "target", "target", CardType.F_MINION))
    assert source.transformation_ids == (target_id,)
    assert not target.deck_buildable
    assert not is_user_deck_card_id(target_id)
