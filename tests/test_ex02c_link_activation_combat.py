"""Real choices for cooperation, timed activation denial, and BP/DP combat."""
from __future__ import annotations

import copy

import pytest

import zz.ex02c  # noqa: F401
from tests.test_public_base_rules import choose_kind, lab
from zz.cards import CARD_REGISTRY
from zz.effects import EffectSpec, EffectTiming, build_effect
from zz.enums import AreaType, CardType, Color, Step
from zz.forces import F_OUROBOROS, F_PHOENIX
from zz.model import Card, CardInstance, ForceInstance
from zz.web.debug_tools import add_debug_card_to_zone


def put(engine, owner, card, area=AreaType.FIELD, *, rested=False):
    ci = CardInstance(card, owner, iid=engine.state.allocate_iid(), area=area, rested=rested)
    getattr(owner, area.value).append(ci)
    return ci


def main_prompt(session):
    session._clear_prompt()
    session._prompt_main_action()


def block_attack(session, attacker, blocker):
    main_prompt(session)
    assert choose_kind(session, "attack", attacker_iid=attacker.iid)["error"] is None
    target = next(o for o in session.prompt["options"] if o.get("kind") == "player")
    assert session.choose(session.prompt["id"], target["id"])["error"] is None
    while session.prompt["kind"] == "flash_action":
        assert choose_kind(session, "flash_pass")["error"] is None
    assert session.prompt["kind"] == "blocker"
    option = next(o for o in session.prompt["options"] if o.get("cardIid") == blocker.iid)
    assert session.choose(session.prompt["id"], option["id"])["error"] is None


@pytest.mark.parametrize("item_id", ["green_00_01_02c_01", "green_00_01_EX02_01"])
def test_berkuli_draws_from_item_placed_by_real_mana_choice(item_id):
    session, owner = lab("green_05_02_02c_00", base_count=5)
    source = next(ci for ci in owner.hand if ci.card.id == "green_05_02_02c_00")
    item_iid = add_debug_card_to_zone(session, item_id, side="P1", zone="hand")["added"]["iid"]
    put(session.engine, owner, Card("cooperation-draw", "draw", "", CardType.B_MINION), AreaType.DECK)
    owner.flags.clear()
    session.engine.state.step = Step.MANA
    main_prompt(session)
    assert choose_kind(session, "play_to_base", iid=item_iid)["error"] is None
    drawn = owner.deck[0]
    hand_size = len(owner.hand)
    assert choose_kind(session, "play_card", iid=source.iid)["error"] is None
    assert drawn in owner.hand
    assert len(owner.hand) == hand_size  # Summon -1, cooperation +1.


@pytest.mark.parametrize("placement", ["non_item", "previous_turn", "item_attached"])
def test_berkuli_cooperation_uses_placement_history_not_current_base(placement):
    session, owner = lab("green_05_02_02c_00", base_count=5)
    engine = session.engine
    source = owner.hand[0]
    item = put(engine, owner, CARD_REGISTRY["green_00_01_02c_01"], AreaType.HAND)
    if placement == "non_item":
        item.card = Card("non-item-mana", "mana", "", CardType.B_MINION, race_jp="トライブ", mana_color=Color.GREEN)
    draws = [put(engine, owner, Card(f"history-draw-{i}", "draw", "", CardType.B_MINION), AreaType.DECK)
             for i in range(3)]
    owner.flags.clear()
    engine.state.step = Step.MANA
    main_prompt(session)
    assert choose_kind(session, "play_to_base", iid=item.iid)["error"] is None
    if placement == "previous_turn":
        put(engine, engine.state.opponent, Card("opponent-history-draw", "draw", "", CardType.B_MINION), AreaType.DECK)
        assert choose_kind(session, "end_turn")["error"] is None
        assert choose_kind(session, "place_colorless_mana")["error"] is None
        assert choose_kind(session, "end_turn")["error"] is None
        assert choose_kind(session, "place_colorless_mana")["error"] is None
    elif placement == "item_attached":
        host = put(engine, owner, Card("item-host", "host", "", CardType.F_MINION,
                                       cost={Color.COLORLESS: 4}, bp=100))
        owner.movement_right_count = 1
        main_prompt(session)
        assert choose_kind(session, "bless", mana_iid=item.iid, target_iid=host.iid)["error"] is None
        assert item not in owner.base
    drawn_before = sum(ci in owner.hand for ci in draws)
    assert choose_kind(session, "play_card", iid=source.iid)["error"] is None
    assert sum(ci in owner.hand for ci in draws) == drawn_before + int(placement == "item_attached")


def test_item_placed_by_card_effect_enables_berkuli_cooperation():
    session, owner = lab("green_05_02_02c_00", base_count=8)
    engine = session.engine
    put(engine, owner, Card("additional-green", "mana", "", CardType.B_MINION, mana_color=Color.GREEN), AreaType.BASE)
    source = owner.hand[0]
    item = put(engine, owner, CARD_REGISTRY["green_00_01_02c_01"], AreaType.HAND)
    leafa = put(engine, owner, CARD_REGISTRY["green_03_02_02c_00"], AreaType.HAND)
    drawn = put(engine, owner, Card("effect-placement-draw", "draw", "", CardType.B_MINION), AreaType.DECK)
    owner.flags.clear()
    main_prompt(session)
    assert choose_kind(session, "play_card", iid=leafa.iid)["error"] is None
    assert session.prompt["kind"] == "effect_target"
    option = next(o for o in session.prompt["options"] if o.get("cardIid") == item.iid)
    assert session.choose(session.prompt["id"], option["id"])["error"] is None
    assert item in owner.base and item.rested
    assert choose_kind(session, "play_card", iid=source.iid)["error"] is None
    assert drawn in owner.hand


def test_new_turn_clears_both_players_placement_history_only():
    session, owner = lab("green_05_02_02c_00", base_count=5)
    engine = session.engine
    opponent = engine.state.opponent
    owner.flags.update({"turn:placed_mana:GREEN", "turn:placed_mana_race:アイテム", "retained-rule"})
    opponent.flags.add("turn:placed_mana_race:アイテム")
    put(engine, opponent, Card("turn-draw", "draw", "", CardType.B_MINION), AreaType.DECK)
    session._clear_prompt()
    engine.state.active_idx = 1
    engine.begin_turn()
    assert "retained-rule" in owner.flags
    assert not any(flag.startswith(("turn:placed_mana:", "turn:placed_mana_race:"))
                   for player in engine.state.players for flag in player.flags)


@pytest.mark.parametrize("color", [Color.COLORLESS, Color.GREEN])
def test_generated_mana_records_color_placement_without_item_race(color):
    session, owner = lab("green_05_02_02c_00", base_count=5)
    owner.flags.clear()
    mana = session.engine.place_generated_colorless_mana(owner, mana_color=color)
    assert mana in owner.base
    assert f"turn:placed_mana:{color.name}" in owner.flags
    assert not any(flag.startswith("turn:placed_mana_race:") for flag in owner.flags)


@pytest.mark.parametrize("zone", [AreaType.TRASH, AreaType.DECK])
def test_berkuli_put_from_trash_or_deck_does_not_trigger_cooperation(zone):
    session, owner = lab("green_05_02_02c_00", base_count=5)
    engine = session.engine
    source = owner.hand.pop(0)
    source.area = zone
    getattr(owner, zone.value).append(source)
    item = put(engine, owner, CARD_REGISTRY["green_00_01_02c_01"], AreaType.HAND)
    drawn = put(engine, owner, Card("no-resurrection-draw", "draw", "", CardType.B_MINION), AreaType.DECK)
    engine.state.step = Step.MANA
    main_prompt(session)
    assert choose_kind(session, "play_to_base", iid=item.iid)["error"] is None
    session._clear_prompt()
    getattr(engine, f"summon_from_{zone.value}")(owner, source)
    assert source in owner.field
    assert drawn in owner.deck and drawn not in owner.hand


@pytest.mark.parametrize("mana_kind", ["item", "other"])
def test_berkuli_bless_effect_is_independent_of_cooperation(mana_kind):
    session, owner = lab("green_05_02_02c_00", zone="field", base_count=1)
    engine = session.engine
    source = next(ci for ci in owner.field if ci.card.id == "green_05_02_02c_00")
    mana = put(engine, owner, Card(
        "berkuli-bless", "bless", "", CardType.B_MINION,
        race_jp="アイテム" if mana_kind == "item" else "トライブ",
        keywords=list(CARD_REGISTRY["green_00_01_02c_01"].keywords),
        bless_condition=lambda _mana, _target, _state: True,
    ), AreaType.BASE)
    enemy = put(engine, engine.state.opponent, Card("berkuli-enemy", "enemy", "", CardType.F_MINION, bp=800))
    owner.movement_right_count = 1
    main_prompt(session)
    assert choose_kind(session, "bless", mana_iid=mana.iid, target_iid=source.iid)["error"] is None
    session._clear_prompt()
    engine.rest_target(enemy)
    engine.triggers.resolve_all()
    assert engine.effective_bp(enemy) == 500


def eugeo_switch_board():
    session, owner = lab("green_08_02_02c_00", zone="field", base_count=5)
    engine = session.engine
    source = next(ci for ci in owner.field if ci.card.id == "green_08_02_02c_00")
    session._clear_prompt()
    engine.transform_card(source, copy.deepcopy(CARD_REGISTRY["green_08_02_02c_01"]))
    opponent = engine.state.opponent
    enemy = put(engine, opponent, Card("locked-enemy", "enemy", "", CardType.F_MINION, bp=800), rested=True)
    summon_iid = add_debug_card_to_zone(session, "green_04_02_02c_00", side="P1", zone="hand")["added"]["iid"]
    main_prompt(session)
    assert choose_kind(session, "play_card", iid=summon_iid)["error"] is None
    assert session.prompt["kind"] == "main_action"
    return session, owner, source, enemy


def test_eugeo_denies_effect_activation_and_expires_after_standby():
    session, owner, source, enemy = eugeo_switch_board()
    engine = session.engine
    opponent = enemy.owner
    assert not engine.refresh_target(enemy)
    assert enemy.rested
    assert any(effect["kind"] == "cannot_activate" for effect in engine.card_active_effects(enemy))
    assert source in owner.field
    late = put(engine, opponent, Card("late-enemy", "late", "", CardType.F_MINION), rested=True)
    mana = put(engine, opponent, Card("base-minion", "base", "", CardType.B_MINION), AreaType.BASE, rested=True)
    token = put(engine, opponent, Card("base-token", "token", "", CardType.MANA_TOKEN), AreaType.BASE, rested=True)
    assert engine.refresh_target(late)
    assert engine.refresh_target(mana)
    assert engine.refresh_target(token)
    observations = []
    put(engine, opponent, Card("standby-draw", "draw", "", CardType.B_MINION), AreaType.DECK)
    source.card.effects.append(EffectSpec(
        EffectTiming.TURN_START,
        lambda _source, _state, _ctx: observations.append(engine.refresh_target(enemy)),
        active_areas=(AreaType.FIELD,),
    ))
    assert choose_kind(session, "end_turn")["error"] is None
    assert observations == [False]
    assert enemy.rested  # Natural refresh was also denied.
    assert all(effect["kind"] != "cannot_activate" for effect in engine.card_active_effects(enemy))
    assert engine.refresh_target(enemy)  # Standby ended; MAIN effects may activate it.


def test_eugeo_denies_ouroboros_before_deadline_but_not_base_phoenix():
    session, _owner, _source, enemy = eugeo_switch_board()
    engine = session.engine
    opponent = enemy.owner
    mana = put(engine, opponent, Card("phoenix-mana", "mana", "", CardType.B_MINION), AreaType.BASE, rested=True)
    rin = ForceInstance(force=F_OUROBOROS, owner=opponent, life=2)
    phoenix = ForceInstance(force=F_PHOENIX, owner=opponent, life=2)
    F_OUROBOROS.passive(rin, engine)
    F_PHOENIX.passive(phoenix, engine)
    engine.state.active_idx = 1
    engine._fire_turn_end_hooks()  # Opponent's END while the next Standby is still ahead.
    assert enemy.rested
    assert not mana.rested


def test_eugeo_standby_lock_covers_interactive_turn_start_effect():
    session, _owner, _source, enemy = eugeo_switch_board()
    engine = session.engine
    put(engine, enemy.owner, Card("standby-deck", "draw", "", CardType.B_MINION), AreaType.DECK)
    enemy.card = copy.deepcopy(enemy.card)
    enemy.card.effects.append(build_effect(
        "refresh_targets", EffectTiming.TURN_START, target_kind="ally_minion",
        min_targets=1, max_targets=1,
        condition=lambda source, _state, ctx: ctx.controller is source.owner,
        active_areas=(AreaType.FIELD,),
    ))
    assert choose_kind(session, "end_turn")["error"] is None
    assert session.prompt["kind"] == "effect_target"
    option = next(o for o in session.prompt["options"] if o.get("cardIid") == enemy.iid)
    assert session.choose(session.prompt["id"], option["id"])["error"] is None
    assert enemy.rested
    assert engine.refresh_target(enemy)  # The queued Standby effect has now finished.


@pytest.mark.parametrize("attacker_bp,attacker_dp,blocker_bp,blocker_dp,attacker_alive,blocker_alive", [
    (500, 1, 400, 9, True, False),
    (400, 9, 500, 1, False, True),
    (500, 1, 500, 9, False, False),
])
def test_actual_blocking_battle_uses_bp_not_dp(attacker_bp, attacker_dp, blocker_bp, blocker_dp,
                                            attacker_alive, blocker_alive):
    session, owner = lab("green_05_02_02c_00", zone="field", base_count=1)
    engine = session.engine
    attacker = owner.field[0]
    attacker.card = Card("battle-attacker", "attacker", "", CardType.F_MINION, bp=attacker_bp, dp=attacker_dp)
    attacker.summoning_sickness = False
    engine.state.present_at_turn_start.add(attacker.iid)
    blocker = put(engine, engine.state.opponent, Card("battle-blocker", "blocker", "", CardType.F_MINION,
                                                   bp=blocker_bp, dp=blocker_dp))
    block_attack(session, attacker, blocker)
    assert (attacker.area is AreaType.FIELD) is attacker_alive
    assert (blocker.area is AreaType.FIELD) is blocker_alive


@pytest.mark.parametrize("berkuli_debuff", [False, True])
def test_real_eugeo_blocked_by_higher_bp_with_and_without_berkuli(berkuli_debuff):
    session, owner = lab("green_08_02_02c_00", zone="field", base_count=1)
    engine = session.engine
    eugeo = owner.field[0]
    sword_iid = add_debug_card_to_zone(session, "green_00_01_02c_01", side="P1", zone="base")["added"]["iid"]
    owner.movement_right_count = 2
    main_prompt(session)
    assert choose_kind(session, "bless", mana_iid=sword_iid, target_iid=eugeo.iid)["error"] is None
    assert eugeo.card.id == "green_08_02_02c_01"
    assert engine.effective_bp(eugeo) == 1000
    if berkuli_debuff:
        berkuli = put(engine, owner, CARD_REGISTRY["green_05_02_02c_00"])
        mana_iid = add_debug_card_to_zone(session, "green_00_01_02c_01", side="P1", zone="base")["added"]["iid"]
        main_prompt(session)
        assert choose_kind(session, "bless", mana_iid=mana_iid, target_iid=berkuli.iid)["error"] is None
    opponent = engine.state.opponent
    blocker = put(engine, opponent, CARD_REGISTRY["colorless_010_02_01_00"])
    extra = put(engine, opponent, Card("unrested-observer", "observer", "", CardType.F_MINION, bp=800))
    battle_bp = []
    extra.card.effects.append(EffectSpec(
        EffectTiming.ON_BLOCK,
        lambda _source, _state, _ctx: battle_bp.append(engine.effective_bp(blocker)),
        active_areas=(AreaType.FIELD,),
    ))
    assert engine.effective_bp(blocker) == 1200
    eugeo.summoning_sickness = False
    engine.state.present_at_turn_start.add(eugeo.iid)
    block_attack(session, eugeo, blocker)
    assert battle_bp == [900 if berkuli_debuff else 1200]
    if berkuli_debuff:
        assert eugeo.area is AreaType.FIELD
        assert blocker.area is AreaType.TRASH
        assert extra.bp_mod == 0
        assert not extra.flags  # Eugeo was not destroyed, so its lock did not fire.
    else:
        assert eugeo.area is AreaType.TRASH
        assert blocker.area is AreaType.FIELD
        assert blocker.rested
        assert not extra.rested  # The destruction effect does not rest active Minions.
        assert not engine.refresh_target(blocker)
        engine.rest_target(extra)
        assert not engine.refresh_target(extra)
