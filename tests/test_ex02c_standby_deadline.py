"""User-confirmed deadline: a Standby that has begun is not the next Standby."""
from __future__ import annotations

import copy

import pytest

from tests.test_ex02c_link_activation_combat import main_prompt, put
from tests.test_public_base_rules import choose_kind, lab
from zz.cards import CARD_REGISTRY
from zz.effects import EffectSpec, EffectTiming, build_effect
from zz.enums import AreaType, CardType, Step
from zz.model import Card


@pytest.mark.parametrize("target_idx", [0, 1])
@pytest.mark.parametrize("already_locked", [False, True])
def test_eugeo_destroyed_during_standby_locks_through_next_owner_standby(target_idx, already_locked):
    session, first_player = lab("green_08_02_02c_00", zone="field", base_count=1)
    engine = session.engine
    target_owner = engine.state.players[target_idx]
    source_owner = engine.state.players[1 - target_idx]
    eugeo = first_player.field[0]
    if eugeo.owner is not source_owner:
        eugeo.owner.field.remove(eugeo)
        eugeo.owner = source_owner
        source_owner.field.append(eugeo)
    session._clear_prompt()
    engine.transform_card(eugeo, copy.deepcopy(CARD_REGISTRY["green_08_02_02c_01"]))
    for player in engine.state.players:
        for index in range(4):
            put(engine, player, Card(f"deadline-draw-{player.side.name}-{index}", "draw", "", CardType.B_MINION), AreaType.DECK)
    target = put(engine, target_owner, Card("deadline-target", "target", "", CardType.F_MINION, bp=500), rested=True)
    target.card.effects.append(EffectSpec(
        EffectTiming.TURN_START,
        lambda source, state, _ctx: state.engine._destroy(eugeo, source=source),
        condition=lambda source, _state, ctx: ctx.controller is source.owner and eugeo.area is AreaType.FIELD,
        active_areas=(AreaType.FIELD,),
    ))
    engine.state.active_idx = 1 - target_idx
    if already_locked:
        engine.prevent_activation_until_next_standby_end(target)
    main_prompt(session)
    assert choose_kind(session, "end_turn")["error"] is None
    assert eugeo.area is AreaType.TRASH
    assert engine.state.active is target_owner and engine.state.step is Step.MANA
    assert target.rested
    assert not engine.refresh_target(target)  # This Standby had already begun when the lock was applied.
    assert any(effect["kind"] == "cannot_activate" for effect in engine.card_active_effects(target))

    # An actual MAIN refresh magic also cannot bypass this still-live lock.
    magic = put(engine, target_owner, Card("deadline-refresh", "refresh", "", CardType.MAGIC,
        effects=[build_effect("refresh_targets", EffectTiming.ON_CAST_MAGIC,
                             target_kind="ally_minion", min_targets=1, max_targets=1)]), AreaType.HAND)
    assert choose_kind(session, "place_colorless_mana")["error"] is None
    assert choose_kind(session, "play_card", iid=magic.iid)["error"] is None
    option = next(option for option in session.prompt["options"] if option.get("cardIid") == target.iid)
    assert session.choose(session.prompt["id"], option["id"])["error"] is None
    assert target.rested

    # Hold the next owner Standby open with a real effect-target choice.
    target.card.effects.append(build_effect(
        "refresh_targets", EffectTiming.TURN_START, target_kind="ally_minion", min_targets=1, max_targets=1,
        condition=lambda source, _state, ctx: ctx.controller is source.owner,
        active_areas=(AreaType.FIELD,),
    ))
    assert choose_kind(session, "end_turn")["error"] is None
    assert choose_kind(session, "place_colorless_mana")["error"] is None
    assert choose_kind(session, "end_turn")["error"] is None
    assert engine.state.active is target_owner and engine.state.step is Step.START
    assert not engine.refresh_target(target)
    option = next(option for option in session.prompt["options"] if option.get("cardIid") == target.iid)
    assert session.choose(session.prompt["id"], option["id"])["error"] is None
    assert engine.state.step is Step.MANA
    assert target.rested  # Both the START effect and natural Refresh were denied.
    assert engine.refresh_target(target)
    assert all(effect["kind"] != "cannot_activate" for effect in engine.card_active_effects(target))


def test_activation_deadline_is_removed_on_leaving_field():
    session, owner = lab("green_05_02_02c_00", zone="field", base_count=1)
    engine = session.engine
    target = owner.field[0]
    engine.prevent_activation_until_next_standby_end(target)
    assert engine.return_to_hand(target)
    assert not any("cannot_activate_until_standby_end" in flag for flag in target.flags)
    session._clear_prompt()
    engine.summon_from_hand(owner, target)
    target.rested = True
    assert engine.refresh_target(target)


def test_researcher_player_activation_lock_covers_field_not_minion_mana():
    session, owner = lab("colorless_03_02_02c_00", zone="field", base_count=1)
    engine = session.engine
    opponent = engine.state.opponent
    field = [put(engine, opponent, Card(f"field-{kind.value}", "field", "", kind, bp=500), rested=True)
             for kind in (CardType.F_MINION, CardType.B_MINION)]
    base = [put(engine, opponent, Card(f"mana-{kind.value}", "mana", "", kind), AreaType.BASE, rested=True)
            for kind in (CardType.F_MINION, CardType.B_MINION, CardType.MANA_TOKEN)]
    session._clear_prompt()
    engine._destroy(owner.field[0], source=field[0])
    assert all(not engine.refresh_target(target) for target in field)
    assert all(engine.refresh_target(target) for target in base)
