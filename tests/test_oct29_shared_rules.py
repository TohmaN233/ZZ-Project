"""Regression tests for cooperation timing and shared activation restrictions."""

import pytest

from tests.test_effect_resolution_order_oct29 import setup
from tests.test_public_base_rules import choose_kind, lab
from zz.enums import AreaType, Step
from zz.multiplayer.hashing import hash_authoritative_state
from zz.web.debug_tools import add_debug_card_to_zone


@pytest.mark.parametrize("card_id", ["red_03_02_02c_00", "red_03_02_EX02_00"])
def test_cooperation_does_not_count_an_item_already_in_base(card_id):
    session, owner = lab(card_id, base_count=3)
    add_debug_card_to_zone(session, "red_00_01_02c_02", side="P1", zone="base")
    deck_iid = add_debug_card_to_zone(session, "colorless_03_02_02c_01", side="P1", zone="deck")["added"]["iid"]
    deck_card = next(ci for ci in owner.deck if ci.iid == deck_iid)
    source = next(ci for ci in owner.hand if ci.card.id == card_id)
    owner.flags = {flag for flag in owner.flags if not flag.startswith("turn:placed_mana")}
    assert choose_kind(session, "play_card", iid=source.iid)["error"] is None
    assert deck_card.area is AreaType.DECK
    assert deck_card not in owner.hand


@pytest.mark.parametrize("mana_id, should_draw", [
    ("red_00_01_02c_00", True),
    ("yellow_00_01_02_00", False),
])
def test_existing_color_cooperation_counts_real_mana_placement_once(mana_id, should_draw):
    session, owner = lab("red_03_02_01_00", base_count=4)
    mana_iid = add_debug_card_to_zone(session, mana_id, side="P1", zone="hand")["added"]["iid"]
    draw_iid = add_debug_card_to_zone(session, "colorless_03_02_02c_01", side="P1", zone="deck")["added"]["iid"]
    draw_card = next(ci for ci in owner.deck if ci.iid == draw_iid)
    source = next(ci for ci in owner.hand if ci.card.id == "red_03_02_01_00")
    owner.flags = {flag for flag in owner.flags if not flag.startswith("turn:placed_mana")}
    session.engine.state.step = Step.MANA
    session._clear_prompt()
    session._prompt_main_action()
    assert choose_kind(session, "play_to_base", iid=mana_iid)["error"] is None
    hand_size = len(owner.hand)
    assert choose_kind(session, "play_card", iid=source.iid)["error"] is None
    assert (draw_card in owner.hand) is should_draw
    assert len(owner.hand) == hand_size - 1 + int(should_draw)


@pytest.mark.parametrize("locked", [False, True])
def test_magic_activation_obeys_the_shared_minion_lock(locked):
    runner = setup("yellow_03_03_02c_00")
    engine = runner.session.engine
    owner = engine.state.players[0]
    target = next(ci for ci in owner.field if ci.card.id == "colorless_01_02_02c_01")
    if locked:
        owner.flags.add(engine._minion_activation_lock_flag(owner))
    for action in runner.spec["actions"][:2]:
        runner._run_action(action)
    assert target.rested is locked


def test_multiplayer_hash_includes_pending_standby_continuation():
    session, owner = lab("red_03_02_02c_00", base_count=3)
    before = hash_authoritative_state(session, revision=0, initial_match={})
    session.engine._pending_standby_player = owner
    session.engine._pending_standby_step = Step.REFRESH
    assert hash_authoritative_state(session, revision=0, initial_match={}) != before
