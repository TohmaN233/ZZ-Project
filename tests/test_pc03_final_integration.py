import pytest
from zz.cards import CARD_REGISTRY
from zz.effects import EffectSpec, EffectTiming
from zz.enums import AreaType, CardType, Color, Keyword
from zz.model import Card, CardInstance, Context
from zz.web.session import GameSession


def setup():
    s = GameSession(seed=42, mode='god')
    e = s.engine
    e.defer_trigger_choice = None
    for p in e.state.players:
        p.field.clear(); p.base.clear(); p.hand.clear(); p.deck.clear()
    return e, *e.state.players


def add(e, owner, card, area=AreaType.FIELD):
    ci = CardInstance(card, owner, iid=e.state.allocate_iid(), area=area)
    getattr(owner, area.name.lower()).append(ci)
    return ci


def test_flame_ring_blocking_aura_uses_attacker_original_and_blocker_current_bp():
    e, owner, opp = setup()
    source = add(e, owner, CARD_REGISTRY['red_05_01_03_03'])
    attacker = add(e, owner, Card('red-attacker', '', '', CardType.F_MINION,
                                  bp=500, printed_color=Color.RED))
    attacker.bp_mod = 500
    weak = add(e, opp, Card('weak', '', '', CardType.F_MINION, bp=400))
    equal = add(e, opp, Card('equal', '', '', CardType.F_MINION, bp=500))
    boosted = add(e, opp, Card('boosted', '', '', CardType.F_MINION, bp=400))
    boosted.bp_mod = 100
    assert weak not in e.legal_blockers(attacker)
    assert equal in e.legal_blockers(attacker)
    assert boosted in e.legal_blockers(attacker)

    attacker.card.printed_color = Color.BLUE
    assert weak in e.legal_blockers(attacker)
    attacker.card.printed_color = Color.RED
    owner.field.remove(source)
    assert weak in e.legal_blockers(attacker)


def test_minion_action_restrictions_do_not_break_force_refresh():
    e, owner, _ = setup()
    add(e, owner, CARD_REGISTRY['colorless_09_02_02c_01'])
    force = owner.forces[0]
    force.rested = True
    assert e.refresh_target(force)
    assert not force.rested


def test_suppression_only_affects_summoned_non_yellow_and_ends_with_source():
    e, owner, opp = setup()
    lock = add(e, owner, CARD_REGISTRY['yellow_05_01_03_01'])
    calls = []
    for color, expected in [(Color.RED, 0), (Color.YELLOW, 1)]:
        c = Card(str(color), '', '', CardType.F_MINION, bp=500, printed_color=color)
        c.effects.append(EffectSpec(EffectTiming.ON_SUMMON, lambda *args: calls.append(1), condition=lambda source, state, ctx: source is ctx.source))
        ci = add(e, opp, c)
        e.triggers.emit(EffectTiming.ON_SUMMON, Context(controller=opp, source=ci))
        e.triggers.resolve_all()
        assert len(calls) == expected
    owner.field.remove(lock)
    ci = add(e, opp, c := Card('red', '', '', CardType.F_MINION, bp=500, printed_color=Color.RED))
    c.effects.append(EffectSpec(EffectTiming.ON_SUMMON, lambda *args: calls.append(1), condition=lambda source, state, ctx: source is ctx.source))
    e.triggers.emit(EffectTiming.ON_SUMMON, Context(controller=opp, source=ci)); e.triggers.resolve_all()
    assert len(calls) == 2


def test_replacement_follows_evolved_source_and_controller():
    e, owner, opp = setup()
    source = add(e, owner, CARD_REGISTRY['yellow_06_01_03_03'])
    actor = add(e, owner, Card('actor', '', '', CardType.F_MINION))
    victim = add(e, opp, Card('victim', '', '', CardType.F_MINION))
    existing = add(e, opp, Card('existing', '', '', CardType.F_MINION), AreaType.DECK)
    assert e.return_to_hand(victim, source=actor)
    assert victim in opp.deck and victim not in opp.hand
    assert opp.deck == [existing, victim]
    owner.field.remove(source)
    victim2 = add(e, opp, Card('victim2', '', '', CardType.F_MINION))
    assert e.return_to_hand(victim2, source=actor)
    assert victim2 in opp.hand


def test_mana_value_and_battle_requirement():
    e, owner, opp = setup()
    mana = add(e, owner, CARD_REGISTRY['green_02_01_03_00'], AreaType.BASE)
    arcana = CardInstance(Card('a', '', '', CardType.F_MINION, race_jp='アルカナ'), owner, 99, AreaType.HAND)
    other = CardInstance(Card('b', '', '', CardType.F_MINION, race_jp='Other'), owner, 100, AreaType.HAND)
    assert e._mana_value(mana, arcana) == 2
    assert e._mana_value(mana, other) == 1
    attacker = add(e, owner, Card('attacker', '', '', CardType.F_MINION))
    blocker = add(e, opp, Card('blocker', '', '', CardType.F_MINION))
    attacker.flags.add('battle:must_be_blocked')
    assert not e.can_decline_block(attacker, [blocker])
    attacker.flags.clear()
    assert e.can_decline_block(attacker, [blocker])


def test_attack_grant_queues_only_matching_allies_and_is_cloned():
    e, owner, opp = setup()
    actor = add(e, owner, Card('caster', '', '', CardType.MAGIC), AreaType.HAND)
    blue = add(e, owner, Card('blue', '', '', CardType.F_MINION, bp=500, printed_color=Color.BLUE))
    red = add(e, owner, Card('red', '', '', CardType.F_MINION, bp=500, printed_color=Color.RED))
    calls = []
    effect = EffectSpec(EffectTiming.ON_ATTACK, lambda source, state, ctx: calls.append(source.iid))
    e.apply_pc03_temporary_attack_grant(source=actor, context=Context(controller=owner, source=actor), target_color=Color.BLUE, target_types=(CardType.F_MINION, CardType.B_MINION), effect=effect, duration='turn')
    assert len(e.clone_for_simulation()._pc03_attack_grants) == 1
    for attacker in (blue, red):
        e.triggers.emit(EffectTiming.ON_ATTACK, Context(controller=owner, source=attacker))
        e.triggers.resolve_all()
    assert calls == [blue.iid]
    e._pc03_attack_grants.clear()
    e.triggers.emit(EffectTiming.ON_ATTACK, Context(controller=owner, source=blue)); e.triggers.resolve_all()
    assert calls == [blue.iid]


def test_nitrog_modifies_only_controller_negative_effects():
    e, owner, opp = setup()
    nitrog = add(e, owner, CARD_REGISTRY['red_03_01_03_01'])
    target = add(e, opp, Card('target', '', '', CardType.F_MINION, bp=1000))
    source = add(e, owner, Card('source', '', '', CardType.F_MINION, bp=1000))
    effect = EffectSpec(EffectTiming.ON_ATTACK, lambda s, state, ctx: state.engine.modify_stat(target, bp_delta=-100))
    e._run_effect_callback(effect.fn, source, e.state, Context(controller=owner, source=source), effect=effect)
    assert target.bp_mod == -200
    owner.field.remove(nitrog)
    e._run_effect_callback(effect.fn, source, e.state, Context(controller=owner, source=source), effect=effect)
    assert target.bp_mod == -300


def test_force_reduction_does_not_stack_and_ends_when_sources_leave():
    e, owner, opp = setup()
    e.state.active_idx = 1
    one = add(e, owner, CARD_REGISTRY['white_01_01_03_00'])
    two = add(e, owner, CARD_REGISTRY['white_01_01_03_00'])
    mana = add(e, owner, Card('evoker', '', '', CardType.B_MINION, printed_color=Color.WHITE, race_jp='エヴォーカー'), AreaType.BASE)
    attacker = add(e, opp, Card('attacker', '', '', CardType.F_MINION, bp=500, cost={Color.RED: 5}))
    force = owner.forces[0]
    force.life = 5
    before = force.life
    e._damage_force(force, 2, attacker, damage_kind='battle')
    assert force.life == before - 1
    owner.field.remove(one); owner.field.remove(two)
    before = force.life
    e._damage_force(force, 2, attacker, damage_kind='battle')
    assert force.life == before - 2


def test_swamp_dragon_only_restricts_its_own_blockers():
    e, owner, opp = setup()
    from zz.enums import Step
    e.state.active_idx = 0
    e.state.step = Step.MAIN
    dragon = add(e, owner, CARD_REGISTRY['colorless_04_01_03_01'])
    other = add(e, owner, Card('other', '', '', CardType.F_MINION, bp=500))
    human = add(e, opp, Card('human', '', '', CardType.F_MINION, bp=500, race_jp='ヒューマン'))
    enemy_dragon = add(e, opp, Card('dragon', '', '', CardType.F_MINION, bp=500, race_jp='ドラゴン'))
    assert human not in e.legal_blockers(dragon)
    assert enemy_dragon in e.legal_blockers(dragon)
    assert human in e.legal_blockers(other)
    assert not any(effect.timing is EffectTiming.ON_SUMMON for effect in dragon.card.effects)


def test_force_attack_restriction_leaves_player_attack_open():
    from zz.enums import AttackTargetKind, Step
    e, owner, opp = setup()
    e.state.active_idx = 1
    e.state.step = Step.MAIN
    add(e, owner, CARD_REGISTRY['white_06_01_03_00'])
    attacker = add(e, opp, Card('rusher', '', '', CardType.F_MINION, bp=500, keywords=[Keyword.RUSH]))
    attacker.summoning_sickness = False
    targets = e.legal_attack_targets(attacker)
    assert any(t.kind is AttackTargetKind.PLAYER for t in targets)
    assert all(t.kind is not AttackTargetKind.FORCE for t in targets)
    owner.field.clear()
    assert any(t.kind is AttackTargetKind.FORCE for t in e.legal_attack_targets(attacker))


def session_setup(active_idx=0):
    session = GameSession(seed=42, mode='god')
    e = session.engine
    session._clear_prompt()
    for p in e.state.players:
        p.field.clear(); p.base.clear(); p.hand.clear()
    e.state.active_idx = active_idx
    from zz.enums import Step
    e.state.step = Step.MAIN
    return session, e, *e.state.players


def choose_card(session, card):
    prompt = session.prompt
    option = next(x for x in prompt['options'] if x.get('cardIid') == card.iid)
    result = session.choose(prompt['id'], option['id'])
    assert result['error'] is None


def test_session_white_attack_grant_filters_and_applies_block():
    from zz.pc03_cards.white_03_02_03_01 import ATTACK_EFFECT
    session, e, owner, opp = session_setup()
    source = add(e, owner, Card('magic', '', '', CardType.MAGIC), AreaType.HAND)
    attacker = add(e, owner, Card('attacker', '', '', CardType.F_MINION, bp=500))
    ready = add(e, opp, Card('ready', '', '', CardType.F_MINION, bp=500))
    rested = add(e, opp, Card('rested', '', '', CardType.F_MINION, bp=500)); rested.rested = True
    e.apply_pc03_temporary_attack_grant(source=source, context=Context(controller=owner, source=source), target_color=None, target_types=(CardType.F_MINION, CardType.B_MINION), effect=ATTACK_EFFECT, duration='turn')
    e.triggers.emit(EffectTiming.ON_ATTACK, Context(controller=owner, source=attacker)); e.triggers.resolve_all()
    assert session.prompt['choiceKind'] == 'enemy_minion'
    assert {x.get('cardIid') for x in session.prompt['options']} == {ready.iid}
    choose_card(session, ready)
    assert 'turn:must_block' in ready.flags
    assert 'turn:must_block' not in rested.flags
    assert not e.can_decline_block(attacker, [ready])


def test_session_nitrog_target_choice_and_opponent_boundary():
    from zz.effects import build_effect
    session, e, owner, opp = session_setup()
    add(e, owner, CARD_REGISTRY['red_03_01_03_01'])
    attacker = add(e, owner, Card('effect', '', '', CardType.F_MINION, bp=500))
    victim = add(e, opp, Card('victim', '', '', CardType.F_MINION, bp=1000))
    eff = build_effect('stat_modifier', EffectTiming.ON_ATTACK, target_kind='enemy_minion', bp_delta=-100, duration='turn')
    attacker.card.effects.append(eff)
    e.triggers.emit(EffectTiming.ON_ATTACK, Context(controller=owner, source=attacker)); e.triggers.resolve_all()
    choose_card(session, victim)
    assert victim.bp_mod == -200
    # The opponent's own effect does not benefit from this owner's Nitrog.
    effect2 = EffectSpec(EffectTiming.ON_ATTACK, lambda source, state, ctx: state.engine.modify_stat(source, bp_delta=-100))
    e._run_effect_callback(effect2.fn, victim, e.state, Context(controller=opp, source=victim), effect=effect2)
    assert victim.bp_mod == -300
    future = EffectSpec(EffectTiming.ON_ATTACK, lambda source, state, ctx: state.engine.add_turn_stat_modifier(owner, target_kind="enemy_minion", bp_delta=-100, source=source))
    e._run_effect_callback(future.fn, attacker, e.state, Context(controller=owner, source=attacker), effect=future)
    assert e._turn_stat_modifiers[-1]["bp_delta"] == -200


@pytest.mark.parametrize("active_idx", [0, 1])
def test_session_godbird_replaces_only_its_controllers_bounce(active_idx):
    from zz.effects import build_effect
    session, e, p1, p2 = session_setup(active_idx)
    owner, opp = (p1, p2) if active_idx == 0 else (p2, p1)
    bird = add(e, owner, CARD_REGISTRY['yellow_06_01_03_03'])
    source = add(e, owner, Card('effect', '', '', CardType.F_MINION, bp=500))
    victim = add(e, opp, Card('victim', '', '', CardType.F_MINION, bp=500))
    source.card.effects.append(build_effect('return_to_hand', EffectTiming.ON_ATTACK, target_kind='enemy_minion'))
    e.triggers.emit(EffectTiming.ON_ATTACK, Context(controller=owner, source=source)); e.triggers.resolve_all()
    choose_card(session, victim)
    assert victim in opp.deck and victim not in opp.hand
    # The opposing player's effect is not replaced by the owner's Bird.
    target = add(e, owner, Card('target', '', '', CardType.F_MINION, bp=500))
    oppsource = add(e, opp, Card('enemy', '', '', CardType.F_MINION, bp=500))
    assert e.return_to_hand(target, source=oppsource)
    assert target in owner.hand


@pytest.mark.parametrize("owner_idx", [0, 1])
def test_outside_generation_animation_is_private_to_owner(owner_idx):
    from zz.multiplayer.views import build_player_view
    session, e, p1, p2 = session_setup(owner_idx)
    owner = (p1, p2)[owner_idx]
    session.state_dto()
    created = e.add_card_from_outside_to_hand(owner, 'blue_02_01_03_01')
    packet = session.state_dto()
    moves = [event for event in packet['animationEvents'] if event.get('fromArea') == 'outside']
    assert len(moves) == 1 and moves[0]['toArea'] == 'hand'
    assert moves[0]['card']['cardId'] == created.card.id
    own_id = f'player_{owner_idx + 1}'
    other_id = f'player_{2 - owner_idx}'
    own_view = build_player_view(session, player_id=own_id, revision=1, state_hash='test', animation_events=moves)
    other_view = build_player_view(session, player_id=other_id, revision=1, state_hash='test', animation_events=moves)
    assert own_view['animationEvents'][0]['card']['cardId'] == created.card.id
    hidden = other_view['animationEvents'][0]['card']
    assert hidden['faceDown'] and 'cardId' not in hidden and 'iid' not in hidden
    assert all(card['faceDown'] for card in other_view['players']['opponent']['hand'])
    assert other_view['publicReveals'] == []


def test_outside_generation_full_hand_goes_public_trash():
    from zz.multiplayer.views import build_player_view
    session, e, owner, opp = session_setup()
    for i in range(10): add(e, owner, Card(str(i), '', '', CardType.MAGIC), AreaType.HAND)
    session.state_dto()
    created = e.add_card_from_outside_to_hand(owner, 'blue_02_01_03_01')
    packet = session.state_dto()
    moves = [event for event in packet['animationEvents'] if event.get('fromArea') == 'outside']
    assert len(owner.hand) == 10 and created in owner.trash and moves[0]['toArea'] == 'trash'
    view = build_player_view(session, player_id='player_2', revision=1, state_hash='test', animation_events=moves)
    assert view['animationEvents'][0]['card']['cardId'] == created.card.id


def test_outside_hidden_animation_updates_opponent_hand_without_identity():
    from tests.test_frontend_atomic_zone_transitions import _run
    _run(r"""
const hidden = {faceDown:true, area:'hand', ownerSide:'P2'};
state = dto(player('P1'), [], null, player('P2'));
const next = dto(player('P1'), [], null, player('P2', [hidden]));
next.animationEvents = [move(hidden, 'outside', 'hand', 'P2')];
stageDuelState(next); drain(); check();
assert.equal(state.players.opponent.handCount, 1);
assert.equal(state.players.opponent.hand[0].faceDown, true);
assert.equal(state.players.opponent.hand[0].iid, undefined);
""")


def test_trash_to_hand_triggers_return_without_a_summon():
    session, e, owner, opp = session_setup()
    card = add(e, owner, CARD_REGISTRY['purple_05_01_03_01'], AreaType.TRASH)
    e.add_to_hand(owner, card, from_area=AreaType.TRASH)
    assert card in owner.field and card not in owner.hand and card not in owner.trash
    assert [(x['from'], x['to']) for x in e.zone_move_events if x['card'] is card] == [
        (AreaType.TRASH, AreaType.HAND), (AreaType.HAND, AreaType.FIELD)]
    assert card not in e.state.summoned_this_turn


def test_trash_return_waits_for_field_owner_replacement():
    session, e, owner, opp = session_setup()
    card = add(e, owner, CARD_REGISTRY['purple_05_01_03_01'], AreaType.TRASH)
    blockers = [add(e, owner, Card(str(i), '', '', CardType.F_MINION, bp=500)) for i in range(5)]
    e.add_to_hand(owner, card, from_area=AreaType.TRASH)
    assert card in owner.hand and session.prompt['choiceKind'] == 'ally_minion'
    choose_card(session, blockers[0])
    assert card in owner.field and blockers[0] in owner.trash and len(owner.field) == 5
