import json

import pytest

from tests.test_frontend_atomic_zone_transitions import _run
from zz.enums import AreaType, CardType, Color
from zz.model import Card, CardInstance
from zz.web.debug_tools import add_debug_card_to_zone, setup_debug_lab
from zz.web.session import GameSession


def prepare_placement(card_id):
    session = GameSession(seed=17, mode="debug-card-lab")
    setup_debug_lab(session, card_id, zone="hand", compact_board=True,
                    player_forces=[], opponent_forces=[])
    owner = session.engine.state.players[0]
    owner.base.clear()
    card = next(ci for ci in owner.hand if ci.card.id == card_id)
    session._prompt_main_action()
    return session, owner, card


def place_card(session, card):
    option = next(option for option in session.prompt["options"]
                  if option.get("kind") == "play_to_base" and option.get("iid") == card.iid)
    result = session.choose(session.prompt["id"], option["id"])
    assert result["error"] is None
    return result


@pytest.mark.parametrize("card_id,expected_id,beast_id", [
    ("colorless_00_00_03_00", "colorless_00_00_03_01", "colorless_04_01_03_02"),
    ("colorless_00_00_03_01", "colorless_00_00_03_02", "colorless_07_01_03_02"),
    ("colorless_00_00_03_02", "colorless_00_00_03_02", "colorless_10_01_03_01"),
])
def test_lahrs_is_active_after_placement_and_can_pay_generic_mana(card_id, expected_id, beast_id):
    session, owner, placed = prepare_placement(card_id)
    cost_one = Card("one-free-mana", "one-free-mana", "one-free-mana", CardType.F_MINION,
                    cost={Color.COLORLESS: 1}, bp=300)
    payee = CardInstance(cost_one, owner, iid=session.engine.state.allocate_iid(), area=AreaType.HAND)
    owner.hand.append(payee)
    result = place_card(session, placed)
    assert placed.card.id == expected_id and not placed.rested
    assert any(card.card.id == beast_id for card in owner.hand)
    actual = next(card for card in result["players"]["human"]["base"] if card["iid"] == placed.iid)
    assert actual["cardId"] == expected_id and actual["rested"] is False
    play = next(option for option in session.prompt["options"]
                if option.get("kind") == "play_card" and option.get("iid") == payee.iid)
    assert placed.iid in play["paymentDefaultIids"]
    paid = session.choose(session.prompt["id"], play["id"], {"paymentBaseIids": [placed.iid]})
    assert paid["error"] is None and payee in owner.field and placed.rested


@pytest.mark.parametrize("card_id", [
    "blue_00_00_03_00", "green_00_00_03_00", "purple_00_00_03_00",
    "red_00_00_03_00", "white_00_00_03_00", "yellow_00_00_03_00",
])
def test_other_summoners_are_active_when_normally_placed(card_id):
    session, owner, placed = prepare_placement(card_id)
    result = place_card(session, placed)
    assert placed in owner.base and not placed.rested
    assert next(card for card in result["players"]["human"]["base"]
                if card["iid"] == placed.iid)["rested"] is False


@pytest.mark.parametrize("knight_side", ["P1", "P2"])
@pytest.mark.parametrize("card_id", ["colorless_00_00_03_00", "blue_00_00_03_00"])
def test_knight_does_not_rest_newly_placed_base_minions(knight_side, card_id):
    session, owner, placed = prepare_placement(card_id)
    add_debug_card_to_zone(session, "colorless_03_01_03_03", side=knight_side, zone="field")
    minion = Card("one-free-mana", "one-free-mana", "one-free-mana", CardType.F_MINION,
                  cost={Color.COLORLESS: 1}, bp=300)
    payee = CardInstance(minion, owner, iid=session.engine.state.allocate_iid(), area=AreaType.HAND)
    owner.hand.append(payee)
    session._prompt_main_action()
    result = place_card(session, placed)
    assert placed in owner.base and not placed.rested
    assert next(card for card in result["players"]["human"]["base"]
                if card["iid"] == placed.iid)["rested"] is False
    play = next(option for option in session.prompt["options"]
                if option.get("kind") == "play_card" and option.get("iid") == payee.iid)
    assert placed.iid in play["paymentDefaultIids"]
    result = session.choose(session.prompt["id"], play["id"], {"paymentBaseIids": [placed.iid]})
    assert result["error"] is None and payee in owner.field and placed.rested
    assert not session.engine.refresh_target(placed) and placed.rested


@pytest.mark.parametrize("knight_side", ["P1", "P2"])
def test_knight_does_not_rest_newly_placed_colorless_mana(knight_side):
    session, owner, _ = prepare_placement("colorless_00_00_03_00")
    add_debug_card_to_zone(session, "colorless_03_01_03_03", side=knight_side, zone="field")
    session._prompt_main_action()
    option = next(option for option in session.prompt["options"]
                  if option.get("kind") == "place_colorless_mana")
    result = session.choose(session.prompt["id"], option["id"])
    assert result["error"] is None
    token = next(card for card in owner.base if card.card.id == "mana_token")
    assert not token.rested
    assert next(card for card in result["players"]["human"]["base"]
                if card["iid"] == token.iid)["rested"] is False


@pytest.mark.parametrize("origin", ["hand", "deck", "generated"])
@pytest.mark.parametrize("rested", [False, True])
def test_effect_placements_respect_their_declared_initial_state_with_knight(origin, rested):
    session, owner, placed = prepare_placement("blue_00_00_03_00")
    add_debug_card_to_zone(session, "colorless_03_01_03_03", side="P2", zone="field")
    if origin == "hand":
        session.engine.put_base_minion_from_hand(owner, placed, rested=rested)
    elif origin == "deck":
        added = add_debug_card_to_zone(session, "green_00_00_03_00", side="P1", zone="deck")["added"]
        placed = next(ci for ci in owner.deck if ci.iid == added["iid"])
        session.engine.place_from_deck_to_base(owner, placed, rested=rested)
    else:
        placed = session.engine.place_generated_colorless_mana(owner, rested=rested)
    assert placed in owner.base and placed.rested is rested


def test_knight_blocks_refreshing_existing_mana_for_both_players():
    session, owner, _ = prepare_placement("colorless_00_00_03_00")
    opponent = session.engine.state.players[1]
    knight = add_debug_card_to_zone(session, "colorless_03_01_03_03", side="P2",
                                    zone="field")["added"]
    mana = []
    for side, player in (("P1", owner), ("P2", opponent)):
        added = add_debug_card_to_zone(session, "blue_00_00_03_00", side=side,
                                       zone="base", rested=True)["added"]
        mana.append(next(ci for ci in player.base if ci.iid == added["iid"]))
    assert all(not session.engine.refresh_target(ci) and ci.rested for ci in mana)

    knight = next(ci for ci in opponent.field if ci.iid == knight["iid"])
    opponent.field.remove(knight)
    knight.area = AreaType.TRASH
    opponent.trash.append(knight)
    assert all(session.engine.refresh_target(ci) and not ci.rested for ci in mana)


def test_lahrs_evolution_preserves_each_copys_existing_rest_state():
    session, owner, placed = prepare_placement("colorless_00_00_03_00")
    previous = add_debug_card_to_zone(session, "colorless_00_00_03_00", side="P1",
                                      zone="base", rested=True)["added"]
    previous = next(ci for ci in owner.base if ci.iid == previous["iid"])
    session._prompt_main_action()
    result = place_card(session, placed)
    assert previous.rested and not placed.rested
    event = next(event for event in result["animationEvents"] if event["type"] == "evolution")
    changes = {item["after"]["iid"]: item for item in event["cards"]}
    for ci in (placed, previous):
        assert changes[ci.iid]["before"]["rested"] is ci.rested
        assert changes[ci.iid]["after"]["rested"] is ci.rested


@pytest.mark.parametrize("knight_side", [None, "P1", "P2"])
def test_lahrs_placement_animation_keeps_the_actual_active_state(knight_side):
    session, _, placed = prepare_placement("colorless_00_00_03_00")
    if knight_side is not None:
        add_debug_card_to_zone(session, "colorless_03_01_03_03", side=knight_side, zone="field")
        session._prompt_main_action()
    before = session.state_dto()
    after = place_card(session, placed)
    assert any(event["type"] == "evolution" for event in after["animationEvents"])
    _run(f"""
state = {json.dumps(before)};
const next = {json.dumps(after)};
const iid = {placed.iid};
stageDuelState(next);
let seen = 0;
while (timers.size) {{
  tick();
  const mana = state.players.human.base.find(card => card.iid === iid);
  if (mana) {{
    seen += 1;
    assert.equal(mana.rested, false, 'placement or evolution showed the card as rested');
  }}
}}
assert.ok(seen > 0);
assert.equal(state.players.human.base.find(card => card.iid === iid).rested, false);
""")


def test_lahrs_placement_animation_precedes_later_mana_payment():
    session, owner, placed = prepare_placement("colorless_00_00_03_00")
    minion = Card("one-free-mana", "one-free-mana", "one-free-mana", CardType.F_MINION,
                  cost={Color.COLORLESS: 1}, bp=300)
    payee = CardInstance(minion, owner, iid=session.engine.state.allocate_iid(), area=AreaType.HAND)
    owner.hand.append(payee)
    before = session.state_dto()
    placed_state = place_card(session, placed)
    play = next(option for option in session.prompt["options"]
                if option.get("kind") == "play_card" and option.get("iid") == payee.iid)
    paid_state = session.choose(session.prompt["id"], play["id"], {"paymentBaseIids": [placed.iid]})
    assert paid_state["error"] is None and placed.rested
    _run(f"""
state = {json.dumps(before)};
const placedState = {json.dumps(placed_state)};
const paidState = {json.dumps(paid_state)};
const iid = {placed.iid};
stageDuelState(placedState);
stageDuelState(paidState);
let seen = 0;
while (timers.size) {{
  tick();
  if (stagedDuelStateQueue.length) {{
    const mana = state.players.human.base.find(card => card.iid === iid);
    if (mana) {{
      seen += 1;
      assert.equal(mana.rested, false, 'payment state appeared during placement animations');
    }}
  }}
}}
assert.ok(seen > 0);
assert.equal(state.players.human.base.find(card => card.iid === iid).rested, true);
""")
