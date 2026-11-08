import copy
from tests.test_public_base_rules import lab, choose_kind
from zz.effects import EffectTiming
from zz.enums import AreaType, Step
from zz.model import Context
from zz.multiplayer.hashing import canonical_authoritative_state, hash_authoritative_state
from zz.web.debug_tools import setup_debug_lab, add_debug_card_to_zone
from zz.web.session import GameSession


def digest(session):
    return hash_authoritative_state(session, revision=0, initial_match={})


def canonical(session):
    return canonical_authoritative_state(session, revision=0, initial_match={})


def cloned_session(session):
    clone = copy.copy(session)
    clone.engine = session.engine.clone_for_simulation()
    return clone


def test_evolution_ledgers_hash_clone_and_turn_allowance():
    session = GameSession(seed=1, mode='god')
    engine = session.engine
    player = engine.state.players[0]
    assert engine.can_pc03_evolve(player, 'seadra')
    before = digest(session)
    player.pc03_evolution_turns['seadra'] = engine.state.turn
    assert not engine.can_pc03_evolve(player, 'seadra')
    assert digest(session) != before
    after_quota = digest(session)
    player.pc03_upgrades['blue_02_01_03_01'] = 'blue_02_01_03_02'
    assert digest(session) != after_quota
    clone = cloned_session(session)
    assert digest(clone) == digest(session)
    assert not clone.engine.can_pc03_evolve(clone.engine.state.players[0], 'seadra')
    engine.state.turn += 1
    assert engine.can_pc03_evolve(player, 'seadra')
    assert digest(clone) != digest(session)


def test_force_activation_lock_and_release_are_hashed():
    session = GameSession(seed=2, mode='god')
    engine = session.engine
    owner = engine.state.players[0]
    force = owner.forces[0]
    engine.rest_target(force)
    before = digest(session)
    engine.prevent_activation_until_next_standby_end(force)
    locked = digest(session)
    assert locked != before and not engine.refresh_target(force)
    assert digest(cloned_session(session)) == digest(session)
    engine.state.turn += 1
    session._clear_prompt()
    engine._pending_standby_player = owner
    engine._pending_standby_step = Step.MANA
    assert engine.continue_standby()
    released = digest(session)
    assert released != locked and engine.refresh_target(force)
    assert not force.flags


def test_real_spell_attack_grant_hash_and_clone():
    session, owner = lab('white_03_02_03_01', base_count=4)
    attacker_iid = add_debug_card_to_zone(session, 'red_04_01_03_00', side='P1', zone='field')['added']['iid']
    source = next(ci for ci in owner.hand if ci.card.id == 'white_03_02_03_01')
    assert choose_kind(session, 'play_card', iid=source.iid)['error'] is None
    engine = session.engine
    assert len(engine._pc03_attack_grants) == 1
    assert any(card.card.id == 'white_03_02_03_01' for card in engine.state.players[0].trash)
    before = digest(session)
    clone = cloned_session(session)
    assert digest(clone) == digest(session)
    attacker = next(ci for ci in clone.engine.state.players[0].field if ci.iid == attacker_iid)
    clone.engine.triggers.emit(EffectTiming.ON_ATTACK, Context(controller=attacker.owner, source=attacker))
    assert clone.engine.triggers.has_pending()
    engine._pc03_attack_grants.clear()
    assert digest(session) != before
    attacker = next(ci for ci in engine.state.players[0].field if ci.iid == attacker_iid)
    engine.triggers.emit(EffectTiming.ON_ATTACK, Context(controller=attacker.owner, source=attacker))
    assert not engine.triggers.has_pending()


def test_queued_summon_source_area_is_hashed():
    session = GameSession(seed=1, mode='debug-card-lab')
    setup_debug_lab(session, 'blue_02_02_01r_00', zone='hand', compact_board=True, player_forces=[], opponent_forces=[])
    add_debug_card_to_zone(session, 'blue_02_01_03_01', side='P1', zone='field')
    engine = session.engine
    player = engine.state.players[0]
    summoned = player.hand[0]
    engine.summon_from_hand(player, summoned, resolve_triggers=False)
    pending = next(item for item in engine.triggers._queue if getattr(item.trigger, 'params', {}).get('pc03_evolution_family') == 'seadra')
    assert pending.context.summon_source_area is AreaType.HAND
    assert engine.pc03_evolution_trigger_eligible(pending.instance, pending.trigger, pending.context)
    before = digest(session)
    assert digest(cloned_session(session)) == digest(session)
    pending.context.summon_source_area = AreaType.DECK
    assert not engine.pc03_evolution_trigger_eligible(pending.instance, pending.trigger, pending.context)
    assert digest(session) != before



def test_force_passives_are_bound_to_simulated_engine():
    session = GameSession(seed=1, mode='debug-card-lab')
    setup_debug_lab(session, 'red_04_01_03_00', zone='field', compact_board=True,
                    player_forces=['force_e', 'force_so2'], opponent_forces=['force_sho', 'force_chi'])
    engine = session.engine
    owner = engine.state.players[0]
    card = next(ci for ci in owner.field if ci.card.id == 'red_04_01_03_00')
    mana_iid = add_debug_card_to_zone(session, 'white_00_01_02_00', side='P1', zone='base')['added']['iid']
    mana = next(ci for ci in owner.base if ci.iid == mana_iid)
    mana.rested = True
    clone = engine.clone_for_simulation()
    cloned_owner = clone.state.players[0]
    cloned_card = next(ci for ci in cloned_owner.field if ci.iid == card.iid)
    cloned_mana = next(ci for ci in cloned_owner.base if ci.iid == mana.iid)
    assert engine.effective_bp(card) == clone.effective_bp(cloned_card) == 500
    next(fn for kind, fn in clone._passive_modifiers if kind == 'turn_end_hook')()
    assert not cloned_mana.rested and mana.rested
    clone.state.players[0].forces[0].rested = True
    assert clone.effective_bp(cloned_card) == 400 and engine.effective_bp(card) == 500
    assert canonical(cloned_session(session))['engineRuntime']['passiveModifiers'] == canonical(session)['engineRuntime']['passiveModifiers']


def test_granted_force_passive_rebinds_on_both_clone_paths():
    session = GameSession(seed=5, mode='debug-card-lab')
    setup_debug_lab(session, 'red_04_01_03_00', zone='field', compact_board=True,
                    player_forces=['force_sho', 'force_chi'], opponent_forces=['force_sho', 'force_chi'])
    engine = session.engine
    source = next(ci for ci in engine.state.players[0].field if ci.card.id == 'red_04_01_03_00')
    engine.grant_force_ability(source, 'force_e')
    assert engine.effective_bp(source) == 500
    for clone in (engine.clone_for_simulation(), copy.deepcopy(engine)):
        cloned_source = next(ci for ci in clone.state.players[0].field if ci.iid == source.iid)
        assert clone.effective_bp(cloned_source) == 500
        clone.state.players[0].field.remove(cloned_source)
        assert clone.effective_bp(cloned_source) == 400
        assert engine.effective_bp(source) == 500
