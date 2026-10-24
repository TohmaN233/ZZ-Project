from pathlib import Path

import pytest

from tools.run_semantic_scenario import ScenarioRunner
from zz.cards import CARD_REGISTRY
from zz.effects import EffectTiming
from zz.enums import AreaType, CardType, Step
from zz.model import Card, CardInstance, Context
from zz.web.debug_tools import add_debug_card_to_zone, setup_debug_lab
from zz.web.serialize import serialize_card
from zz.web.session import GameSession


ROOT = Path(__file__).resolve().parents[1]


def scenario(card_id):
    runner = ScenarioRunner(ROOT / f"tests/semantic_scenarios/pc02r/{card_id}-positive.json", ROOT)
    for call in runner.spec["setup"]:
        response = runner._apply_setup(call)
        runner._apply_captures(response, call)
    return runner


def test_build_up_recovery_prompt_only_offers_build_up_and_returns_chosen_copy():
    runner = scenario("yellow_01_03_02r_00")
    add_debug_card_to_zone(runner.session, "red_02_03_02r_01", side="P1", zone="trash")
    for action in runner.spec["actions"][:-1]:
        runner._run_action(action)
    prompt = runner.session.prompt
    assert prompt["kind"] == "effect_target"
    offered = [option["cardId"] for option in prompt["options"]]
    assert offered == ["yellow_01_03_02r_00", "yellow_01_03_02r_00"]
    runner._run_action(runner.spec["actions"][-1])
    owner = runner.session.engine.state.players[0]
    assert any(card.iid == runner.captures["recovery_copy"] for card in owner.hand)
    assert any(card.card.id == "red_02_03_02r_01" for card in owner.trash)
    assert runner.session.state_dto()["error"] is None


@pytest.mark.parametrize("skip", [False, True])
def test_hardin_hand_choice_filters_printed_cost_and_type_and_allows_declining(skip):
    runner = scenario("yellow_07_02_02r_00")
    session = runner.session
    for card_id in ("red_02_03_02r_01", "yellow_00_01_02r_00", "red_07_02_02r_00"):
        add_debug_card_to_zone(session, card_id, side="P1", zone="hand")
    runner._run_action(runner.spec["actions"][0])
    prompt = session.prompt
    assert prompt["kind"] == "effect_target"
    offered = [option["cardIid"] for option in prompt["options"] if option["id"] != "none"]
    assert offered == [runner.captures["recruited"]]
    assert any(option["id"] == "none" for option in prompt["options"])
    if skip:
        before = [card.iid for card in session.engine.state.players[0].hand]
        dto = session.choose(prompt["id"], "none")
        assert dto["error"] is None
        assert [card.iid for card in session.engine.state.players[0].hand] == before
        assert session.prompt["kind"] == "main_action"
    else:
        runner._run_action(runner.spec["actions"][1])
        runner._run_action(runner.spec["actions"][2])
        assert any(card.iid == runner.captures["recruited"] for card in session.engine.state.players[0].field)


def test_hardin_empty_target_list_requires_explicit_decline_option():
    runner = scenario("yellow_07_02_02r_00")
    session = runner.session
    runner._run_action(runner.spec["actions"][0])
    prompt = session.prompt
    target = next(option for option in prompt["options"] if option.get("cardIid"))
    owner = session.engine.state.players[0]
    before = tuple(card.iid for card in owner.hand)

    rejected = session.choose(prompt["id"], target["id"], {"selectedOptionIds": []})
    assert rejected["error"]["code"] == "illegal_choice"
    assert tuple(card.iid for card in owner.hand) == before
    assert session.prompt["id"] == prompt["id"]

    accepted_decline = session.choose(prompt["id"], "none", {"selectedOptionIds": []})
    assert accepted_decline["error"] is None
    assert tuple(card.iid for card in owner.hand) == before


def test_ascended_hardin_attack_prompt_uses_attack_text_in_each_language():
    runner = scenario("yellow_07_02_02r_01")
    for action in runner.spec["actions"][:3]:
        runner._run_action(action)
    prompt = runner.session.prompt
    assert prompt["kind"] == "effect_target"
    assert "【アタック時】" in prompt["effectTextJp"]
    assert "【攻击时】" in prompt["effectTextZh"]
    assert "When Attacking" in prompt["effectTextEn"]
    assert "变形时" not in prompt["effectTextZh"]
    assert "When Transformed" not in prompt["effectTextEn"]


def omitsu_session():
    session = GameSession(seed=710, mode="god")
    setup_debug_lab(session, "yellow_00_01_02r_00", zone="base", compact_board=True, non_minion_mana_only=True)
    session._clear_prompt()
    session.engine.state.step = Step.MAIN
    session.engine.effect_events.clear()
    owner = session.engine.state.players[0]
    mana = next(card for card in owner.base if card.card.id == "yellow_00_01_02r_00")
    return session, owner, mana


def start_turn_event(session, owner):
    session.engine.state.active_idx = session.engine.state.players.index(owner)
    session.engine.triggers.emit(EffectTiming.TURN_START, Context(controller=owner))
    session.engine.triggers.resolve_all()


def test_omitsu_in_base_has_neither_turn_start_effect_nor_effect_popup():
    session, owner, mana = omitsu_session()
    start_turn_event(session, owner)
    assert (mana.bp_mod, mana.dp_mod) == (0, 0)
    assert not session.engine.effect_events


def test_blessed_omitsu_buffs_host_once_and_reports_its_own_granted_text():
    session, owner, mana = omitsu_session()
    host = CardInstance(CARD_REGISTRY["yellow_02_02_02r_00"], owner, iid=session.engine.state.allocate_iid(), area=AreaType.FIELD)
    owner.field.append(host)
    session.engine.bless(mana, host)
    session.engine.effect_events.clear()
    start_turn_event(session, owner)
    assert (host.bp_mod, host.dp_mod) == (100, 1)
    assert len(session.engine.effect_events) == 1
    source, effect, context = session.engine.effect_events[0]
    assert source is mana
    fields = session._effect_text_fields(source, effect, context)
    assert "回合开始时" in fields["effectTextZh"]
    assert "BP+100" in fields["effectTextZh"]
    session.engine.effect_events.clear()
    start_turn_event(session, session.engine.state.players[1])
    assert not session.engine.effect_events


def test_details_explain_battle_blessing_and_all_stat_aura_deltas():
    session = GameSession(seed=711, mode="god")
    setup_debug_lab(session, "red_02_02_02r_00", zone="field", compact_board=True, non_minion_mana_only=True)
    owner = session.engine.state.players[0]
    host = owner.field[0]
    mana_iid = add_debug_card_to_zone(session, "red_00_01_02r_00", side="P1", zone="base")["added"]["iid"]
    mana = next(card for card in owner.base if card.iid == mana_iid)
    session._clear_prompt()
    session.engine.bless(mana, host)
    session.engine.modify_stat(host, bp_delta=200, dp_delta=1, duration="battle")
    dto = serialize_card(session.engine, host, session.asset_index)
    assert any(effect["kind"] == "battle_stat_modifier" and effect["bpDelta"] == 200 for effect in dto["activeEffects"])
    assert any(effect["kind"] == "blessing_stats" and effect["sourceCardIid"] == mana.iid for effect in dto["activeEffects"])
    token_card = Card("feedback-token", "token", "token", CardType.F_MINION, bp=100, is_token=True)
    token = CardInstance(token_card, owner, iid=session.engine.state.allocate_iid(), area=AreaType.FIELD)
    owner.field.append(token)
    aura_card = Card("feedback-base-aura", "base aura", "base aura", CardType.B_MINION, stat_aura=lambda source, target, state: (50, 1) if target is token else (0, 0))
    base_aura = CardInstance(aura_card, owner, iid=session.engine.state.allocate_iid(), area=AreaType.BASE)
    owner.base.append(base_aura)
    dto = serialize_card(session.engine, token, session.asset_index)
    stat_effects = [effect for effect in dto["activeEffects"] if "bpDelta" in effect]
    assert sum(effect["bpDelta"] for effect in stat_effects) == dto["bpModifier"] == 250
    assert sum(effect["dpDelta"] for effect in stat_effects) == dto["dpModifier"] == 1
    assert {effect["sourceCardId"] for effect in stat_effects} == {mana.card.id, aura_card.id}
    session.engine.state.active_idx = 1
    dto = serialize_card(session.engine, token, session.asset_index)
    assert dto["bpModifier"] == 50
    assert {effect["sourceCardId"] for effect in dto["activeEffects"] if "bpDelta" in effect} == {aura_card.id}
