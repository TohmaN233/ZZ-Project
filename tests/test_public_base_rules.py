import pytest
from pathlib import Path
from tools.run_semantic_scenario import ScenarioRunner

from zz.cards import CARD_REGISTRY
from zz.engine import BASE_CAP
from zz.forces import F_CHIRON
from zz.enums import AreaType, CardType, Color, Step
from zz.effects import EffectTiming
from zz.model import Card, CardInstance, ForceInstance, Context
from zz.web.debug_tools import add_debug_card_to_zone, setup_debug_fixed_board, setup_debug_lab
from zz.web.serialize import serialize_card
from zz.web.session import GameSession


def lab(card_id, *, zone="hand", base_count=10):
    session = GameSession(seed=901, mode="god")
    setup_debug_lab(session, card_id, zone=zone, compact_board=True, non_minion_mana_only=False)
    owner = session.engine.state.players[0]
    while len(owner.base) < base_count:
        add_debug_card_to_zone(session, "mana_token", side="P1", zone="base")
    setup_debug_fixed_board(session, active_side="P1", control_both=True, preserve_board=True, step="main")
    return session, owner


def choose_kind(session, kind, **payload):
    option_id = next(key for key, action in session._options.items()
                     if getattr(action, "kind", None) == kind
                     and all(action.payload.get(key) == value for key, value in payload.items()))
    return session.choose(session.prompt["id"], option_id)


@pytest.mark.parametrize("card_id", ["green_07_02_02r_00", "blue_01_03_02r_00"])
def test_mandatory_generated_mana_at_full_base_prompts_and_keeps_magic_in_trash(card_id):
    session, owner = lab(card_id)
    source = next(card for card in owner.hand if card.card.id == card_id)
    dto = choose_kind(session, "play_card", iid=source.iid)
    assert dto["error"] is None
    assert session.prompt["kind"] == "effect_target"
    assert session.prompt["choiceKind"] == "ally_base"
    assert session.prompt["playerSide"] == owner.side.name
    assert len(owner.base) == BASE_CAP
    replacement = owner.base[-1]
    option = next(option for option in session.prompt["options"] if option["cardIid"] == replacement.iid)
    dto = session.choose(session.prompt["id"], option["id"])
    assert dto["error"] is None
    assert len(owner.base) == BASE_CAP and replacement not in owner.base
    generated = owner.base[-1]
    assert session.engine._mana_color_of(generated) is (Color.GREEN if card_id.startswith("green") else Color.COLORLESS)
    if card_id.startswith("blue"):
        assert generated.rested
        assert source in owner.trash and source not in owner.hand
        assert owner.movement_right_count == 0
    events = dto["animationEvents"]
    assert any(event.get("type") == "zone_move" and event.get("toArea") == "base" and event.get("card", {}).get("iid") == generated.iid for event in events)


@pytest.mark.parametrize("target_kind", ["player", "force"])
def test_penny_heals_once_after_blessed_host_damages_any_player_or_force(target_kind):
    session, owner = lab("white_00_01_02r_00", zone="base", base_count=2)
    mana = next(card for card in owner.base if card.card.id == "white_00_01_02r_00")
    host = CardInstance(Card("white-body", "white", "white", CardType.F_MINION, printed_color=Color.WHITE), owner,
                        iid=session.engine.state.allocate_iid(), area=AreaType.FIELD)
    owner.field.append(host)
    for player in session.engine.state.players:
        player.forces = [ForceInstance(force=F_CHIRON, owner=player, life=4)]
    session._clear_prompt()
    session.engine.bless(mana, host)
    force = owner.forces[0]
    force.life = 1
    opponent = session.engine.state.players[1]
    if target_kind == "player":
        session.engine._damage_player(opponent, 1, source=host)
    else:
        session.engine._damage_force(opponent.forces[0], 1, source=host)
    assert session.prompt is not None and session.prompt["choiceKind"] == "ally_force"
    option = next(option for option in session.prompt["options"] if option["forceId"] == force.force.id)
    result = session.choose(session.prompt["id"], option["id"])
    assert result["error"] is None
    assert force.life == 2
    assert session.prompt["kind"] != "effect_target"


def test_ivy_dragon_debuff_is_visible_in_public_details():
    session, owner = lab("green_06_02_02r_01", base_count=6)
    source = next(card for card in owner.hand if card.card.id == "green_06_02_02r_01")
    enemy_iid = add_debug_card_to_zone(session, "red_02_02_02r_00", side="P2", zone="field")["added"]["iid"]
    choose_kind(session, "play_card", iid=source.iid)
    option = next(option for option in session.prompt["options"] if option["cardIid"] == enemy_iid)
    session.choose(session.prompt["id"], option["id"])
    enemy = next(card for card in session.engine.state.players[1].field if card.iid == enemy_iid)
    dto = serialize_card(session.engine, enemy, session.asset_index)
    assert any(effect["kind"] == "cannot_attack_player" for effect in dto["activeEffects"])


@pytest.mark.parametrize("base_count", [8, 9, 10])
def test_retreat_returns_host_and_bless_mana_through_owner_capacity_choices(base_count):
    session, owner = lab("blue_02_02_02r_00", zone="field", base_count=base_count)
    host = owner.field[0]
    mana_iid = add_debug_card_to_zone(session, "blue_00_01_02r_00", side="P1", zone="base")["added"]["iid"]
    mana = next(card for card in owner.base if card.iid == mana_iid)
    session._clear_prompt()
    session.engine.bless(mana, host)
    owner.movement_right_count = 1
    setup_debug_fixed_board(session, active_side="P1", control_both=True, preserve_board=True, step="main")
    dto = choose_kind(session, "move_card", iid=host.iid, direction="field_to_base")
    assert dto["error"] is None
    while session.prompt["kind"] in {"blessing_base_replacement", "effect_target"}:
        assert session.prompt["playerSide"] == owner.side.name
        count = session.prompt.get("requiredTargetCount", 1)
        option_ids = [option["id"] for option in session.prompt["options"][:count]]
        dto = session.choose(session.prompt["id"], option_ids[0], {"selectedOptionIds": option_ids})
        assert dto["error"] is None
    assert host in owner.base and mana in owner.base
    assert not host.blessings and mana.rested
    assert len(owner.base) <= BASE_CAP


def test_mulligan_visual_events_remove_selected_hand_before_drawing():
    session = GameSession(seed=902, mode="god")
    owner = session.engine.state.players[0]
    selected = owner.hand[:3]
    dto = session.choose(session.prompt["id"], "redraw_selected", {"selectedCardIids": [card.iid for card in selected]})
    assert dto["error"] is None
    events = [event for event in dto["animationEvents"] if event["type"] in {"zone_move", "draw"}]
    departures = [index for index, event in enumerate(events) if event["type"] == "zone_move" and event["fromArea"] == "hand" and event["toArea"] == "deck"]
    draws = [index for index, event in enumerate(events) if event["type"] == "draw"]
    assert len(departures) == len(selected) and draws
    assert max(departures) < min(draws)


def test_blue_bounce_full_base_lets_opponent_choose_all_replacements_including_bless():
    root = Path(__file__).resolve().parents[1]
    runner = ScenarioRunner(root / "tests/semantic_scenarios/pc02r/blue_04_03_02r_00-positive.json", root)
    for call in runner.spec["setup"]:
        response = runner._apply_setup(call)
        runner._apply_captures(response, call)
    session = runner.session
    owner, opponent = session.engine.state.players
    victim = next(card for card in opponent.field if card.card.id == "blue_06_02_02r_00")
    mana_iid = add_debug_card_to_zone(session, "blue_00_01_02r_00", side="P2", zone="base")["added"]["iid"]
    mana = next(card for card in opponent.base if card.iid == mana_iid)
    session._clear_prompt()
    session.engine.state.active_idx = 1
    session.engine.bless(mana, victim)
    while len(opponent.base) < BASE_CAP:
        add_debug_card_to_zone(session, "mana_token", side="P2", zone="base")
    setup_debug_fixed_board(session, active_side="P1", control_both=True, preserve_board=True, step="main")
    runner.state = session.state_dto()
    for action in runner.spec["actions"]:
        runner._run_action(action)
    assert session.prompt["kind"] == "effect_target"
    assert session.prompt["choiceKind"] == "ally_base"
    assert session.prompt["playerSide"] == opponent.side.name
    assert session.prompt["requiredTargetCount"] == 3
    assert victim in opponent.field and mana in victim.blessings
    replacement_iids = {card.iid for card in opponent.base[-3:]}
    option_ids = [option["id"] for option in session.prompt["options"] if option["cardIid"] in replacement_iids]
    result = session.choose(session.prompt["id"], option_ids[0], {"selectedOptionIds": option_ids})
    assert result["error"] is None
    assert victim in opponent.base and mana in opponent.base
    assert len(opponent.base) == BASE_CAP
    assert replacement_iids.isdisjoint(card.iid for card in opponent.base)
    assert any(card.card.id == "blue_04_03_02r_00" for card in owner.trash)


def test_draflare_attack_debuff_matches_verified_japanese_face():
    session, owner = lab("red_08_02_02r_00", zone="field", base_count=8)
    opponent = session.engine.state.players[1]
    iid = add_debug_card_to_zone(session, "yellow_03_02_02r_00", side="P2", zone="field")["added"]["iid"]
    enemy = next(card for card in opponent.field if card.iid == iid)
    session._clear_prompt()
    session.engine.triggers.emit(EffectTiming.ON_ATTACK, Context(controller=owner, source=owner.field[0]))
    session.engine.triggers.resolve_all()
    assert enemy.permanent_bp_mod == -100
    assert session.engine.card_active_effects(enemy)[0]["bpDelta"] == -100


def test_token_pushed_to_full_base_disappears_without_replacing_any_mana():
    session, owner = lab("blue_02_02_02r_00", zone="field")
    token = CardInstance(Card("base-rule-token", "token", "token", CardType.F_MINION, is_token=True), owner,
                         iid=session.engine.state.allocate_iid(), area=AreaType.FIELD)
    owner.field.append(token)
    existing = {card.iid for card in owner.base}
    session._clear_prompt()
    assert session.engine.move_target_to_base_asking_owner(token)
    assert token not in owner.removed and token not in owner.field
    assert {card.iid for card in owner.base} == existing
