from pathlib import Path

import pytest

from tools.run_semantic_scenario import ScenarioRunner
from zz.cards import CARD_REGISTRY
from zz.effects import EffectSpec, EffectTiming
from zz.enums import AreaType
from zz.forces import F_CHIRON, F_OUROBOROS
from zz.model import ForceInstance
from zz.multiplayer.views import build_player_view
from zz.web.debug_tools import add_debug_card_to_zone, setup_debug_fixed_board, setup_debug_lab
from zz.web.session import GameSession
from tests.test_public_base_rules import choose_kind, lab


ROOT = Path(__file__).resolve().parents[1]


def setup(card_id):
    runner = ScenarioRunner(ROOT / f"tests/semantic_scenarios/ex02c/{card_id}-positive.json", ROOT)
    for call in runner.spec["setup"]:
        response = runner._apply_setup(call)
        runner._apply_captures(response, call)
    return runner


def source_events(response, card_id):
    return [event for event in response["animationEvents"]
            if event["type"] == "effect" and event.get("card", {}).get("cardId") == card_id]


def test_siune_switch_announces_before_top_two_window_and_never_repeats_on_selection():
    card_id = "yellow_02_02_02c_00"
    runner = setup(card_id)
    opened = runner._run_action(runner.spec["actions"][0])["state"]
    assert opened["prompt"]["kind"] == "effect_target"
    assert len(opened["prompt"]["revealedCards"]) == 2
    assert len(source_events(opened, card_id)) == 1
    opponent_view = build_player_view(runner.session, player_id="player_2", revision=1, state_hash="test")
    assert opponent_view["prompt"] is None
    selected = runner._run_action(runner.spec["actions"][1])["state"]
    assert not source_events(selected, card_id)
    assert len(selected["publicReveals"]) == 1


def test_rosario_really_enters_trash_only_after_both_clauses_resolve():
    card_id = "yellow_011_03_02c_00"
    runner = setup(card_id)
    for action in runner.spec["actions"][:2]:
        runner._run_action(action)
    cast = runner._run_action(runner.spec["actions"][2])["state"]
    source = runner.session._pending_effect["source"]
    owner = source.owner
    assert cast["prompt"]["kind"] == "effect_target" and source not in owner.trash
    first = runner._run_action(runner.spec["actions"][3])["state"]
    assert first["prompt"]["kind"] == "effect_target"
    assert source.area is AreaType.RESOLVING
    assert source in owner.resolving and source not in owner.hand and source not in owner.trash
    assert [card["iid"] for card in first["players"]["human"]["resolving"]] == [source.iid]
    opponent_view = build_player_view(runner.session, player_id="player_2", revision=1, state_hash="test",
                                      animation_events=first["animationEvents"])
    assert [card["cardId"] for card in opponent_view["players"]["opponent"]["resolving"]] == [card_id]
    assert all(card.get("faceDown") for card in opponent_view["players"]["opponent"]["hand"])
    assert any(event.get("card", {}).get("cardId") == card_id and event.get("toArea") == "resolving"
               for event in opponent_view["animationEvents"])
    assert [(event.get("fromArea"), event.get("toArea")) for event in first["animationEvents"]
            if event["type"] == "zone_move" and event.get("card", {}).get("iid") == source.iid] == [
                ("hand", "resolving")]
    final = runner._run_action(runner.spec["actions"][4])["state"]
    events = final["animationEvents"]
    moves = [i for i, event in enumerate(events) if event["type"] == "zone_move"
             and event.get("card", {}).get("cardId") == card_id and event.get("toArea") == "trash"]
    returned = [i for i, event in enumerate(events) if event["type"] == "zone_move"
                and event.get("fromArea") == "field" and event.get("toArea") == "hand"]
    assert len(moves) == 1 and returned and moves[0] > returned[-1]
    assert events[moves[0]]["fromArea"] == "resolving"
    assert source.area is AreaType.TRASH
    assert source not in owner.resolving and owner.trash.count(source) == 1
    assert final["players"]["human"]["resolving"] == []


def test_later_source_clause_waits_for_the_previous_target_choice(monkeypatch):
    card_id = "yellow_011_03_02c_00"
    card = CARD_REGISTRY[card_id]
    def third_clause(source, _state, _ctx):
        source.owner.flags.add("test:third_clause_resolved")
    third = EffectSpec(timing=EffectTiming.ON_CAST_MAGIC, fn=third_clause,
                       official_timing="フラッシュ", official_effect="third clause")
    monkeypatch.setattr(card, "effects", [*card.effects, third])
    runner = setup(card_id)
    for action in runner.spec["actions"][:3]:
        runner._run_action(action)
    first = runner._run_action(runner.spec["actions"][3])["state"]
    assert first["prompt"]["kind"] == "effect_target"
    assert "test:third_clause_resolved" not in runner.session.engine.state.players[0].flags
    final = runner._run_action(runner.spec["actions"][4])["state"]
    assert "test:third_clause_resolved" in runner.session.engine.state.players[0].flags
    source_moves = [event for event in final["animationEvents"] if event["type"] == "zone_move"
                    and event.get("card", {}).get("cardId") == card_id]
    assert len(source_moves) == 1


def test_discarded_magic_is_not_mistaken_for_a_cast_before_a_following_draw():
    runner = setup("yellow_06_02_02c_00")
    session = runner.session
    owner = session.engine.state.players[0]
    add_debug_card_to_zone(session, "yellow_03_03_02c_00", side="P1", zone="hand")
    add_debug_card_to_zone(session, "red_02_02_02c_00", side="P1", zone="deck")
    magic = next(card for card in owner.hand if card.card.id == "yellow_03_03_02c_00")
    before = session._visual_state_snapshot()
    session.engine.discard_from_hand(owner, magic)
    session.engine.draw(owner, 1)
    session._record_visual_changes(before)
    response = session.state_dto()
    events = response["animationEvents"]
    discard = next(i for i, event in enumerate(events) if event["type"] == "zone_move"
                   and event.get("card", {}).get("iid") == magic.iid)
    draw = next(i for i, event in enumerate(events) if event["type"] == "draw")
    assert discard < draw


def test_draw_then_discard_resolves_before_magic_enters_trash():
    session, owner = lab("white_02_03_00_01")
    source = next(card for card in owner.hand if card.card.id == "white_02_03_00_01")
    add_debug_card_to_zone(session, "red_02_02_02c_00", side="P1", zone="deck")
    add_debug_card_to_zone(session, "yellow_05_02_02c_00", side="P1", zone="deck")
    copy = add_debug_card_to_zone(session, "white_02_03_00_01", side="P1", zone="trash")
    hand_before = len(owner.hand)
    deck_before = len(owner.deck)
    result = choose_kind(session, "play_card", iid=source.iid)
    assert result["error"] is None
    assert result["prompt"]["kind"] == "effect_target"
    assert result["prompt"]["choiceKind"] == "hand_card"
    assert len(owner.deck) == deck_before - 2 and len(owner.hand) == hand_before + 1
    assert source.area is AreaType.RESOLVING and source not in owner.trash
    assert source.iid not in {option.get("cardIid") for option in result["prompt"]["options"]}
    for candidates in (session.engine._eligible_targets(owner, "trash_magic_cost_at_most_4"),
                       session._eligible_targets(owner, "trash_magic_cost_at_most_4")):
        candidate_iids = {card.iid for card in candidates}
        assert copy["added"]["iid"] in candidate_iids and source.iid not in candidate_iids
    chosen = next(option for option in result["prompt"]["options"] if option.get("cardIid"))
    result = session.choose(result["prompt"]["id"], chosen["id"])
    assert result["error"] is None
    assert len(owner.hand) == hand_before
    assert source.area is AreaType.TRASH and owner.trash.count(source) == 1
    assert source in session.engine._eligible_targets(owner, "trash_magic_cost_at_most_4")
    assert source in session._eligible_targets(owner, "trash_magic_cost_at_most_4")
    events = result["animationEvents"]
    discarded = next(i for i, event in enumerate(events) if event["type"] == "zone_move"
                     and event.get("card", {}).get("iid") == chosen["cardIid"])
    finished = next(i for i, event in enumerate(events) if event["type"] == "zone_move"
                    and event.get("card", {}).get("iid") == source.iid)
    assert discarded < finished


def test_resolving_magic_cannot_be_selected_as_a_trash_target(monkeypatch):
    card_id = "yellow_011_03_02c_00"
    card = CARD_REGISTRY[card_id]

    def recover_magic(source, state, _ctx):
        targets = state.engine.select_target(source.owner, "trash_magic_cost_at_most_4", 1, 1, source=source)
        for target in targets:
            state.engine.add_to_hand(source.owner, target, from_area=AreaType.TRASH)

    recover = EffectSpec(timing=EffectTiming.ON_CAST_MAGIC, fn=recover_magic,
                         target_kind="trash_magic_cost_at_most_4")
    monkeypatch.setattr(card, "effects", [*card.effects, recover])
    runner = setup(card_id)
    existing = add_debug_card_to_zone(runner.session, "yellow_03_03_02c_00", side="P1", zone="trash")
    for action in runner.spec["actions"][:5]:
        runner._run_action(action)
    session = runner.session
    source = session._pending_effect["source"]
    prompt = session.prompt
    assert prompt["kind"] == "effect_target" and prompt["choiceKind"] == "trash_magic_cost_at_most_4"
    offered = {option.get("cardIid") for option in prompt["options"] if option.get("cardIid")}
    assert existing["added"]["iid"] in offered and source.iid not in offered
    assert source.area is AreaType.RESOLVING and source not in source.owner.trash
    option = next(option for option in prompt["options"] if option.get("cardIid") == existing["added"]["iid"])
    result = session.choose(prompt["id"], option["id"])
    assert result["error"] is None and source.area is AreaType.TRASH
    assert any(card.iid == existing["added"]["iid"] for card in source.owner.hand)


def test_draw_three_and_discard_two_finishes_before_spell_enters_trash():
    path = ROOT / "tests/semantic_scenarios/pc02r/white_05_03_02r_00-positive.json"
    runner = ScenarioRunner(path, ROOT)
    for call in runner.spec["setup"]:
        response = runner._apply_setup(call)
        runner._apply_captures(response, call)
    first = runner._run_action(runner.spec["actions"][0])["state"]
    source = runner.session._pending_effect["source"]
    assert source.area is AreaType.RESOLVING and source not in source.owner.trash
    assert first["prompt"]["requiredTargetCount"] == 2
    final = runner._run_action(runner.spec["actions"][1])["state"]
    moves = [event for event in final["animationEvents"] if event["type"] == "zone_move"]
    assert [(event["fromArea"], event["toArea"]) for event in moves] == [
        ("hand", "trash"), ("hand", "trash"), ("resolving", "trash")]
    assert source.area is AreaType.TRASH and source.owner.trash.count(source) == 1


def test_listener_moved_out_of_field_by_magic_is_not_collected_early():
    session = GameSession(seed=17, mode="debug-card-lab")
    setup_debug_lab(session, "blue_04_03_02r_00", compact_board=True)
    owner, opponent = session.engine.state.players
    small_iid = add_debug_card_to_zone(session, "colorless_01_02_02c_01", side="P2", zone="field")["added"]["iid"]
    puma_iid = add_debug_card_to_zone(session, "colorless_05_02_01r_01", side="P2", zone="field")["added"]["iid"]
    puma = next(card for card in opponent.field if card.iid == puma_iid)
    source = next(card for card in owner.hand if card.card.id == "blue_04_03_02r_00")
    play = next(option for option in session.prompt["options"] if option.get("iid") == source.iid)
    result = session.choose(session.prompt["id"], play["id"], {"paymentBaseIids": play["paymentDefaultIids"]})
    assert result["error"] is None
    assert session.prompt["kind"] == "effect_target"
    assert {option.get("cardIid") for option in session.prompt["options"]} == {small_iid, puma_iid}
    small = next(option for option in session.prompt["options"] if option.get("cardIid") == small_iid)
    result = session.choose(session.prompt["id"], small["id"])
    assert result["error"] is None and source.area is AreaType.RESOLVING
    assert session.prompt["kind"] == "effect_target"
    assert [option.get("cardIid") for option in session.prompt["options"]] == [puma_iid]
    result = session.choose(session.prompt["id"], session.prompt["options"][0]["id"])
    assert result["error"] is None
    assert puma.area is AreaType.BASE and puma in opponent.base
    assert (puma.permanent_bp_mod, puma.permanent_dp_mod) == (0, 0)
    assert source.area is AreaType.TRASH and not owner.resolving and not session.engine._magic_cast_frames


def test_nested_opponent_choice_finishes_before_magic_continues():
    session = GameSession(seed=17, mode="debug-card-lab")
    setup_debug_lab(session, "blue_04_03_02r_00", compact_board=True)
    owner, opponent = session.engine.state.players
    small = add_debug_card_to_zone(session, "colorless_01_02_02c_02", side="P2", zone="field")["added"]["iid"]
    red = add_debug_card_to_zone(session, "red_02_02_02c_00", side="P2", zone="field")["added"]["iid"]
    item = add_debug_card_to_zone(session, "green_00_01_02c_01", side="P2", zone="deck")["added"]["iid"]
    setup_debug_fixed_board(session, control_both=True, preserve_board=True)
    source = next(card for card in owner.hand if card.card.id == "blue_04_03_02r_00")
    play = next(option for option in session.prompt["options"] if option.get("iid") == source.iid)
    result = session.choose(session.prompt["id"], play["id"], {"paymentBaseIids": play["paymentDefaultIids"]})
    assert result["error"] is None and [option.get("cardIid") for option in session.prompt["options"]] == [small]
    result = session.choose(session.prompt["id"], session.prompt["options"][0]["id"])
    assert result["error"] is None and source.area is AreaType.RESOLVING
    assert session.prompt["choiceKind"] == "deck_base_minion" and session.prompt["playerSide"] == "P2"
    assert any(option.get("cardIid") == item for option in session.prompt["options"])
    option = next(option for option in session.prompt["options"] if option.get("cardIid") == item)
    result = session.choose(session.prompt["id"], option["id"])
    assert result["error"] is None and session.prompt["kind"] == "effect_target"
    assert session.prompt["playerSide"] == "P1"
    assert [option.get("cardIid") for option in session.prompt["options"]] == [red]
    result = session.choose(session.prompt["id"], session.prompt["options"][0]["id"])
    assert result["error"] is None and source.area is AreaType.TRASH
    assert any(card.iid == red for card in opponent.base)


@pytest.mark.parametrize("card_id", ["yellow_01_03_02r_00", "white_02_03_02r_00"])
def test_flash_magic_can_be_used_when_it_has_no_legal_minion_target(card_id):
    session = GameSession(seed=19, mode="debug-card-lab")
    setup_debug_lab(session, card_id, compact_board=True)
    owner, opponent = session.engine.state.players
    assert not owner.field
    attacker_iid = add_debug_card_to_zone(session, "red_02_02_02c_00", side="P2", zone="field")["added"]["iid"]
    setup_debug_fixed_board(session, active_side="P2", control_both=True, preserve_board=True)
    assert any(card.iid == attacker_iid for card in opponent.field)
    attack = next(option for option in session.prompt["options"] if option.get("kind") == "attack")
    result = session.choose(session.prompt["id"], attack["id"])
    assert result["error"] is None
    target = next(option for option in session.prompt["options"] if option.get("kind") == "player")
    result = session.choose(session.prompt["id"], target["id"])
    assert result["error"] is None and session.prompt["kind"] == "flash_action"
    source = next(card for card in owner.hand if card.card.id == card_id)
    spell = next(option for option in session.prompt["options"] if option.get("iid") == source.iid)
    result = session.choose(session.prompt["id"], spell["id"], {"paymentBaseIids": spell["paymentDefaultIids"]})
    assert result["error"] is None and source.area is AreaType.TRASH
    assert source not in owner.hand and not owner.resolving and not session.engine._magic_cast_frames


@pytest.mark.parametrize("card_id", ["purple_03_03_02r_00", "purple_04_03_02r_00"])
def test_main_magic_resolves_available_effects_without_a_legal_target(card_id):
    session, owner = lab(card_id)
    opponent = session.engine.state.players[1]
    owner.field.clear()
    opponent.forces.clear()
    owner.life = 4
    enemy = add_debug_card_to_zone(session, "red_02_02_02c_00", side="P2", zone="field")["added"]["iid"]
    source = next(card for card in owner.hand if card.card.id == card_id)
    result = choose_kind(session, "play_card", iid=source.iid)
    assert result["error"] is None and source.area is AreaType.TRASH
    assert any(card.iid == enemy for card in opponent.field)
    assert owner.life == (5 if card_id == "purple_03_03_02r_00" else 4)


def test_auto_draw_discard_uses_available_hand_count_when_deck_is_short():
    session, owner = lab("white_05_03_02r_00")
    source = next(card for card in owner.hand if card.card.id == "white_05_03_02r_00")
    owner.hand = [source]
    owner.deck.clear()
    drawn = add_debug_card_to_zone(session, "red_02_02_02c_00", side="P1", zone="deck")["added"]["iid"]
    owner.forces = [ForceInstance(force=force, owner=owner, life=0, destroyed=True)
                    for force in (F_CHIRON, F_OUROBOROS)]

    class FirstTarget:
        def choose_target(self, _engine, _kind, _minimum, maximum, eligible):
            return eligible[:maximum]

    session._clear_prompt()
    session.engine.set_policies(FirstTarget(), FirstTarget())
    session.engine.defer_source_effect_choice = None
    session.engine.defer_trigger_choice = None
    session.engine.play_card(source)
    assert not owner.hand and source.area is AreaType.TRASH
    assert any(card.iid == drawn for card in owner.trash)
    assert owner.trash.count(source) == 1 and not owner.resolving


@pytest.mark.parametrize("hand_size", [9, 10])
def test_sakuya_orders_independent_choices_and_bounce_overflow_counts(hand_size):
    runner = setup("yellow_06_02_02c_00")
    session = runner.session
    session.engine.ignore_hand_cap = False
    owner, opponent = session.engine.state.players
    watcher = add_debug_card_to_zone(session, "colorless_04_02_02c_00", side="P1", zone="field")
    watcher = next(card for card in owner.field if card.iid == watcher["added"]["iid"])
    assert (session.engine.effective_bp(watcher), session.engine.effective_dp(watcher)) == (500, 1)
    while len(opponent.hand) < hand_size:
        add_debug_card_to_zone(session, "green_02_02_02c_03", side="P2", zone="hand")
    add_debug_card_to_zone(session, "green_02_02_02c_03", side="P2", zone="field")
    opponent.field[-1].permanent_dp_mod = -opponent.field[-1].card.dp
    add_debug_card_to_zone(session, "red_02_02_02c_00", side="P2", zone="field")
    before = {card.iid: session.engine.effective_dp(card) for card in opponent.field}
    session._prompt_main_action()
    for action in runner.spec["actions"][:2]:
        runner._run_action(action)
    for dp in (0, 1):
        prompt = session.prompt
        assert prompt["kind"] == "effect_target"
        offered = {option["cardIid"] for option in prompt["options"] if option.get("cardIid")}
        expected = {card.iid for card in opponent.field if before[card.iid] == dp}
        assert offered == expected and len(offered) == 2
        chosen_iid = max(offered)
        chosen = next(card for card in opponent.field if card.iid == chosen_iid)
        option = next(option for option in prompt["options"] if option.get("cardIid") == chosen_iid)
        response = session.choose(prompt["id"], option["id"])
        assert response["error"] is None and chosen not in opponent.field
        assert chosen.area is (AreaType.HAND if hand_size == 9 and dp == 0 else AreaType.TRASH)
        assert "turn:ex02c_opponent_minion_returned_to_hand" in owner.flags
    assert len(opponent.hand) == 10
    assert (session.engine.effective_bp(watcher), session.engine.effective_dp(watcher)) == (900, 3)
