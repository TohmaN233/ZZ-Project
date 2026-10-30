from zz.effects import EffectSpec, EffectTiming
from zz.enums import AreaType, CardType
from zz.model import Card, CardInstance
from zz.model import Action
from zz.web.debug_tools import add_debug_card_to_zone
from tests.test_public_base_rules import lab
import pytest


def test_destroyed_source_prompts_once_and_other_destroy_listener_still_fires():
    session, owner = lab('purple_02_02_02r_00', zone='field')
    source = next(c for c in owner.field if c.card.id == 'purple_02_02_02r_00')
    opponent = session.engine.state.players[1]
    for force in opponent.forces:
        force.destroyed = True
    # The lab has no Forces; two DP-zero bodies are eligible at X=0.
    enemies = []
    for _ in range(2):
        card = Card('zero-dp', 'zero', 'zero', CardType.F_MINION, bp=300, dp=0)
        instance = CardInstance(card, opponent, iid=session.engine.state.allocate_iid(), area=AreaType.FIELD)
        opponent.field.append(instance)
        enemies.append(instance)
    observed = []
    listener = CardInstance(Card('listener', 'listener', 'listener', CardType.F_MINION,
        effects=[EffectSpec(EffectTiming.ON_DESTROY, lambda c,s,x: observed.append(x.target.iid),
                            condition=lambda c,s,x: x.target is source)]), owner,
        iid=session.engine.state.allocate_iid(), area=AreaType.FIELD)
    owner.field.append(listener)
    session._clear_prompt()
    session.engine.destroy_target(source, enemies[0])
    option = next(o for o in session.prompt['options'] if o.get('cardIid') == enemies[0].iid)
    result = session.choose(session.prompt['id'], option['id'])
    assert result['error'] is None
    assert session.prompt['kind'] != 'effect_target'
    assert enemies[1] in opponent.field
    assert observed == [source.iid]


def test_magic_source_explicit_trash_effect_is_resolved_once():
    session, owner = lab('blue_01_03_02r_00')
    calls = []
    magic = CardInstance(Card('test-magic', 'magic', 'magic', CardType.MAGIC,
        effects=[EffectSpec(EffectTiming.ON_CAST_MAGIC, lambda c,s,x: calls.append(c.iid),
                            condition=lambda c,s,x: x.source is c, active_areas=(AreaType.TRASH,))]),
        owner, iid=session.engine.state.allocate_iid(), area=AreaType.HAND)
    owner.hand.append(magic)
    session._clear_prompt()
    session.engine.play_card(magic)
    assert calls == [magic.iid]


@pytest.mark.parametrize('flash', [False, True])
def test_magic_is_in_resolving_area_until_its_effect_completes(flash):
    session, owner = lab('blue_01_03_02r_00')
    observed = []
    magic = CardInstance(Card('flash-magic', 'flash', 'flash', CardType.MAGIC, flash_timing_ok=True,
        effects=[EffectSpec(EffectTiming.ON_CAST_MAGIC,
                            lambda c,s,x: observed.append((c.area, c in c.owner.resolving,
                                                           c in c.owner.hand, c in c.owner.trash)))]),
        owner, iid=session.engine.state.allocate_iid(), area=AreaType.HAND)
    owner.hand.append(magic)
    session._clear_prompt()
    if flash:
        session.engine.apply_flash_action(owner, Action('play_card', {'iid': magic.iid}))
    else:
        session.engine.play_card(magic)
    assert observed == [(AreaType.RESOLVING, True, False, False)]
    assert magic.area is AreaType.TRASH and owner.trash.count(magic) == 1
    assert magic not in owner.resolving


def test_generated_mana_disappears_without_entering_trash_or_banished_card_count():
    session, owner = lab('green_07_02_02r_00')
    source = owner.base[-1]
    token = session.engine.place_generated_colorless_mana(owner, replace_base_iid=source.iid)
    trash_count, removed_count = len(owner.trash), len(owner.removed)
    session.engine._eject_base_card(owner, token, reason='replacement')
    assert token not in owner.base and token not in owner.trash
    assert token not in owner.removed
    assert len(owner.trash) == trash_count and len(owner.removed) == removed_count


def test_discard_records_departure_before_subsequent_draw():
    session, owner = lab('colorless_03_02_02r_03')
    selected = owner.hand[0]
    add_debug_card_to_zone(session, 'red_02_02_02r_00', side='P1', zone='deck')
    session.engine.visual_events.clear()
    session.engine.discard_from_hand(owner, selected)
    session.engine.draw(owner, 1)
    moves = [e for e in session.engine.visual_events if e['type'] == 'zone_move']
    assert [(e['from'], e['to']) for e in moves] == [
        (AreaType.HAND, AreaType.TRASH), (AreaType.DECK, AreaType.HAND)]


@pytest.mark.parametrize('operation', ['return_to_hand', 'return_to_deck', 'banish_target'])
def test_generated_minion_leaving_field_disappears(operation):
    session, owner = lab('green_07_02_02r_00')
    token = session.engine.create_token(owner, Card('generated-body', 'token', 'token', CardType.F_MINION, is_token=True))
    assert getattr(session.engine, operation)(token)
    assert all(token not in zone for zone in (owner.hand, owner.deck, owner.field, owner.base, owner.trash, owner.removed))
