"""ZZ-03/11/13: granted abilities use the host Minion's selection rules."""
from copy import copy

import pytest

from tests.test_public_base_rules import choose_kind, lab
from zz.cards import CARD_REGISTRY
from zz.effects import EffectTiming, build_effect
from zz.engine import IllegalActionError
from zz.enums import AreaType, CardType, Color
from zz.model import Card, CardInstance, Context
from zz.web.debug_tools import add_debug_card_to_zone, replace_debug_forces, setup_debug_fixed_board


def put(session, owner, card, area=AreaType.FIELD):
    instance = CardInstance(card, owner, iid=session.engine.state.allocate_iid(), area=area)
    getattr(owner, area.value).append(instance)
    return instance


def sword_board(*, ex02=False, other_target=True):
    host_id = "green_04_02_EX02_00" if ex02 else "green_04_02_02c_00"
    sword_id = "green_00_01_EX02_02" if ex02 else "green_00_01_02c_02"
    asuna_id = "yellow_05_02_EX02_00" if ex02 else "yellow_05_02_02c_00"
    session, attacker_owner = lab(host_id, zone="field", base_count=4)
    attacker = attacker_owner.field[0]
    defender = session.engine.state.players[1]
    replace_debug_forces(session, "P2", ["force_sei", "force_chi"])
    asuna = put(session, defender, CARD_REGISTRY[asuna_id])
    legal = put(session, defender, Card("colored-six", "有色6", "Colored Six", CardType.F_MINION,
                                      cost={Color.GREEN: 1, Color.COLORLESS: 5}, bp=700)) if other_target else None
    sword_iid = add_debug_card_to_zone(session, sword_id, side="P1", zone="base")["added"]["iid"]
    setup_debug_fixed_board(session, active_side="P1", control_both=True, preserve_board=True)
    assert choose_kind(session, "bless", mana_iid=sword_iid, target_iid=attacker.iid)["error"] is None
    return session, attacker, asuna, legal


def sword_battle(**kwargs):
    session, attacker, asuna, legal = sword_board(**kwargs)
    assert choose_kind(session, "attack", attacker_iid=attacker.iid)["error"] is None
    attack_target = next(option for option in session.prompt["options"] if option.get("kind") == "force")
    after = session.choose(session.prompt["id"], attack_target["id"])
    assert after["error"] is None
    return session, attacker, asuna, legal


@pytest.mark.parametrize("ex02", [False, True])
def test_blue_rose_granted_rest_cannot_offer_sphinx_protected_asuna(ex02):
    session, attacker, asuna, legal = sword_battle(ex02=ex02)
    prompt = session.prompt
    assert prompt["kind"] == "effect_target"
    assert {option.get("cardIid") for option in prompt["options"]} == {legal.iid}
    assert "相手の有色のミニオン1体をレストする。" in prompt["effectTextJp"]
    invalid = session.choose(prompt["id"], prompt["options"][0]["id"],
                             {"selectedOptionIds": [f"card:{asuna.iid}"]})
    assert invalid["error"]["code"] == "illegal_choice"
    assert not asuna.rested and not legal.rested
    assert session.prompt["id"] == prompt["id"]
    after = session.choose(prompt["id"], prompt["options"][0]["id"])
    assert after["error"] is None
    assert legal.rested and not asuna.rested
    assert attacker.rested
    assert session.prompt["kind"] == "flash_action"


@pytest.mark.parametrize("source_kind", ["granted", "minion", "base_in_field", "magic", "base", "native_attached_base"])
@pytest.mark.parametrize("cost,own_turn,destroyed", [(5, False, False), (6, False, False),
                                                    (5, True, False), (5, False, True)])
def test_sphinx_source_cost_turn_and_lifetime_contract(source_kind, cost, own_turn, destroyed):
    session, host, target, _ = sword_board(other_target=False)
    engine = session.engine
    owner, defender = engine.state.players
    target.card = copy(target.card)
    target.card.cost = {Color.YELLOW: 1, Color.COLORLESS: cost - 1}
    sword = host.blessings[0]
    effect = build_effect("rest_targets", EffectTiming.ON_ATTACK, target_kind="enemy_minion")
    if source_kind == "granted":
        source = sword
        effect = sword.card.effects[0]
    elif source_kind == "minion":
        source = host
    elif source_kind == "native_attached_base":
        source = sword
        effect = build_effect("rest_targets", EffectTiming.ON_BLESS, target_kind="enemy_minion",
                              active_areas=(AreaType.BLESSING,))
    else:
        card_type = CardType.MAGIC if source_kind == "magic" else CardType.B_MINION
        area = {"magic": AreaType.HAND, "base": AreaType.BASE, "base_in_field": AreaType.FIELD}[source_kind]
        source = put(session, owner, Card("effect-carrier", "effect", "effect", card_type), area)
    session._clear_prompt()
    engine.state.active_idx = 1 if own_turn else 0
    if destroyed:
        engine._destroy_force(defender.forces[0], host)
    observed_sources = []
    target.card.effect_targetable = lambda target, source, state: observed_sources.append(source) or True
    protected = cost <= 5 and not own_turn and not destroyed and source_kind in {"granted", "minion", "base_in_field"}
    expected = [] if protected else [target]
    assert engine._can_effect_select(source, target, effect=effect) is not protected
    assert session._eligible_targets(owner, "enemy_minion", None, effect, source_ci=source) == expected
    offered = []

    class CapturePolicy:
        def choose_target(self, engine, kind, minimum, maximum, eligible):
            offered.extend(eligible)
            return eligible[:maximum]

    engine.set_policies(CapturePolicy(), CapturePolicy())
    engine._run_effect_callback(effect.fn, source, engine.state, Context(controller=owner, source=host), effect=effect)
    assert offered == expected
    assert target.rested is not protected
    expected_source = host if source_kind == "granted" else source
    assert observed_sources and all(observed is expected_source for observed in observed_sources)


@pytest.mark.parametrize("operation", ["detach", "host_leaves"])
def test_granted_selection_source_does_not_survive_detach_or_host_departure(operation):
    session, host, target, legal = sword_board()
    engine = session.engine
    sword = host.blessings[0]
    effect = sword.card.effects[0]
    assert engine.effect_selection_source(sword, effect=effect) is host
    session._clear_prompt()
    if operation == "detach":
        engine._finish_blessing_return(host, sword)
    else:
        assert engine.return_to_hand(host)
    assert engine.effect_selection_source(sword, effect=effect) is None
    assert not engine._can_effect_select(sword, legal, effect=effect)
    assert session._eligible_targets(host.owner, "enemy_minion", None, effect, source_ci=sword) == []
    next_host = put(session, host.owner, host.card)
    engine.refresh_target(sword)
    host.owner.movement_right_count = 1
    setup_debug_fixed_board(session, active_side="P1", control_both=True, preserve_board=True)
    assert choose_kind(session, "bless", mana_iid=sword.iid, target_iid=next_host.iid)["error"] is None
    assert engine.effect_selection_source(sword, effect=effect) is next_host
    assert not engine._can_effect_select(sword, target, effect=effect)
    assert engine._can_effect_select(sword, legal, effect=effect)


def test_sphinx_does_not_cancel_nonselecting_all_minion_effect():
    session, host, target, legal = sword_board()
    session._clear_prompt()
    host.card = copy(host.card)
    host.card.effects = [build_effect("rest_targets", EffectTiming.ON_ATTACK, target_kind="enemy_minion",
                                      all_targets=True, condition=lambda ci, state, ctx: ctx.source is ci)]
    # Remove the single-target sword ability for this all-target contract.
    session.engine._finish_blessing_return(host, host.blessings[0])
    session._prompt_main_action()
    assert choose_kind(session, "attack", attacker_iid=host.iid)["error"] is None
    target_option = next(option for option in session.prompt["options"] if option.get("kind") == "force")
    after = session.choose(session.prompt["id"], target_option["id"])
    assert after["error"] is None
    assert session.prompt["kind"] == "flash_action"
    assert target.rested and legal.rested


def test_blue_rose_no_legal_target_continues_the_attack():
    session, attacker, asuna, _ = sword_battle(other_target=False)
    assert session.prompt["kind"] == "flash_action"
    assert attacker.rested and not asuna.rested
    assert not session.engine.triggers.has_pending()


def test_engine_rejects_policy_submitting_a_protected_granted_effect_target():
    session, attacker, asuna, legal = sword_battle()
    pending = session._pending_effect

    class IllegalTargetPolicy:
        def choose_target(self, engine, kind, minimum, maximum, eligible):
            return [asuna]

    session.engine.set_policies(IllegalTargetPolicy(), IllegalTargetPolicy())
    with pytest.raises(IllegalActionError, match="illegal effect target"):
        session.engine._run_effect_callback(pending["effect"].fn, pending["source"],
                                            session.engine.state, pending["context"], effect=pending["effect"])
    assert not asuna.rested and not legal.rested
    assert session.engine._effect_target_contract is None


def choose_only_unprotected_target(session, protected, legal):
    assert session.prompt["kind"] == "effect_target"
    assert {option.get("cardIid") for option in session.prompt["options"]} == {legal.iid}
    after = session.choose(session.prompt["id"], session.prompt["options"][0]["id"])
    assert after["error"] is None
    assert not protected.rested and legal.rested
    return after


def test_already_queued_granted_attack_keeps_host_source_after_host_leaves():
    session, host, protected, legal = sword_board()
    sword = host.blessings[0]
    host.card = copy(host.card)
    host.card.effects = [build_effect("return_self_to_hand", EffectTiming.ON_ATTACK,
                                      condition=lambda source, state, ctx: ctx.source is source)]
    session._clear_prompt()
    session._prompt_main_action()
    assert choose_kind(session, "attack", attacker_iid=host.iid)["error"] is None
    option = next(option for option in session.prompt["options"] if option.get("kind") == "force")
    assert session.choose(session.prompt["id"], option["id"])["error"] is None
    assert host.area is AreaType.HAND and sword.area is AreaType.BASE
    choose_only_unprotected_target(session, protected, legal)
    assert session.engine.effect_selection_source(sword, effect=sword.card.effects[0]) is None


@pytest.mark.parametrize("granted", [False, True])
def test_destroy_effect_keeps_minion_origin_after_zone_cleanup_and_resolves_once(granted):
    session, host, protected, legal = sword_board()
    sword = host.blessings[0]
    source = sword if granted else host
    source.card = copy(source.card)
    effect = build_effect("rest_targets", EffectTiming.ON_DESTROY, target_kind="enemy_minion",
                          granted_by_blessing=granted,
                          condition=lambda source, state, ctx: ctx.target is host,
                          active_areas=(AreaType.BLESSING,) if granted else (AreaType.FIELD,),
                          official_effect="相手のミニオン1体をレストする。")
    calls = []
    resolve = effect.fn

    def counted(source, state, ctx):
        calls.append(source.iid)
        resolve(source, state, ctx)

    effect.fn = counted
    source.card.effects = [effect]
    session._clear_prompt()
    session.state_dto()
    session.engine._destroy(host, source=protected)
    assert host.area is AreaType.TRASH and sword.area is AreaType.BASE
    from zz.multiplayer.hashing import hash_authoritative_state
    assert len(hash_authoritative_state(session, revision=0, initial_match={})) == 64
    session.state_dto()
    choose_only_unprotected_target(session, protected, legal)
    assert calls == [source.iid]
    assert not session.engine.triggers.has_pending()


@pytest.mark.parametrize("operation", ["detach_then_destroy", "return_to_hand", "condition_false", "once_per_turn_used"])
def test_granted_destroy_does_not_fire_for_detach_nondestruction_or_failed_condition(operation):
    session, host, protected, legal = sword_board()
    sword = host.blessings[0]
    calls = []
    sword.card = copy(sword.card)
    sword.card.effects = [build_effect("rest_targets", EffectTiming.ON_DESTROY, target_kind="enemy_minion",
                                       granted_by_blessing=True, active_areas=(AreaType.BLESSING,),
                                       condition=lambda source, state, ctx: operation != "condition_false")]
    if operation == "once_per_turn_used":
        sword.card.effects[0].params["once_per_turn_flag"] = "test:already-used"
        sword.flags.add("test:already-used")
    original = sword.card.effects[0].fn

    def counted(source, state, ctx):
        calls.append(source.iid)
        original(source, state, ctx)

    sword.card.effects[0].fn = counted
    session._clear_prompt()
    if operation == "detach_then_destroy":
        session.engine._finish_blessing_return(host, sword)
        session.engine._destroy(host, source=protected)
    elif operation == "return_to_hand":
        assert session.engine.return_to_hand(host)
    else:
        session.engine._destroy(host, source=protected)
    assert calls == []
    assert session.prompt is None
    assert not protected.rested and not legal.rested
    assert not session.engine.triggers.has_pending()
