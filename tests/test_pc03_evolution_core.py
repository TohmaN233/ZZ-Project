import random

import pytest

import zz.decks
from zz.cards import CARD_REGISTRY
from zz.decks import is_user_deck_card_id
from zz.engine import Engine, IllegalActionError
from zz.enums import AreaType, Side, Step
from zz.model import CardInstance, Context, GameState, Player
from zz.web.debug_tools import setup_debug_lab, add_debug_card_to_zone
from zz.web.session import GameSession


def test_handcrafted_basic_and_pc01_cards_keep_official_race_metadata():
    from zz.basic import _basic_rows
    from zz.pc01 import DEFAULT_CARD_TSV, _clean_text, _pc01_rows

    rows = _basic_rows(DEFAULT_CARD_TSV) + _pc01_rows(DEFAULT_CARD_TSV)
    assert rows
    for row in rows:
        card_id = row['image_id'].strip()
        assert CARD_REGISTRY[card_id].race_jp == _clean_text(row.get('race_jp')), card_id


def test_evolution_targets_and_conjured_beasts_cannot_be_built_into_decks():
    from importlib import import_module
    from zz.pc03 import _MODULES

    restricted = set()
    for _, module_name in _MODULES:
        module = import_module(module_name)
        beast = getattr(module, 'SUMMON_BEAST_CARD_ID', None)
        if beast:
            restricted.add(beast)
        for attr in ('EVOLUTION_PAIRS', 'LAHRS_UPGRADES'):
            restricted.update(target for _, target in getattr(module, attr, ()))
    assert restricted
    assert all(not is_user_deck_card_id(card_id) for card_id in restricted)
    assert is_user_deck_card_id('blue_00_00_03_00')
    assert is_user_deck_card_id('colorless_00_00_03_00')


def game():
    p, q = Player('P1', Side.P1), Player('P2', Side.P2)
    return Engine(GameState([p, q], step=Step.MAIN), random.Random(3)), p, q


def put(e, p, cid, area):
    ci = CardInstance(CARD_REGISTRY[cid], p, iid=e.state.allocate_iid(), area=area)
    getattr(p, area.value).append(ci)
    return ci


def test_deck_base_placement_does_not_trigger_ordinary_hand_placement_effect():
    e, player, _ = game()
    summoner = put(e, player, 'green_00_00_03_00', AreaType.DECK)
    e.place_from_deck_to_base(player, summoner)
    e.triggers.resolve_all()
    assert summoner in player.base
    assert all(card.card.id != 'green_03_01_03_02' for card in player.hand)
    player.movement_right_count = 1
    with pytest.raises(IllegalActionError):
        e.move_card(summoner, 'base_to_field')

    hand_engine, hand_player, _ = game()
    hand_engine.state.step = Step.MANA
    summoner_from_hand = put(hand_engine, hand_player, 'green_00_00_03_00', AreaType.HAND)
    hand_engine.play_to_base(summoner_from_hand)
    assert summoner_from_hand in hand_player.base
    assert [card.card.id for card in hand_player.hand] == ['green_03_01_03_02']


def test_paired_evolution_every_zone_and_family_limits():
    e, p, q = game()
    regions = [AreaType.DECK, AreaType.HAND, AreaType.BASE, AreaType.FIELD,
               AreaType.TRASH, AreaType.REMOVED, AreaType.RESOLVING]
    copies = [put(e, p, 'blue_00_00_03_00', a) for a in regions]
    beast = put(e, p, 'blue_02_01_03_01', AreaType.FIELD)
    other = put(e, q, 'blue_00_00_03_00', AreaType.HAND)
    nested = CardInstance(CARD_REGISTRY['blue_00_00_03_00'], p, iid=e.state.allocate_iid(), area=AreaType.BLESSING)
    copies[3].blessings.append(nested)
    beast.rested = True
    beast.bp_mod = 100
    beast.permanent_bp_mod = 200
    original_id = beast.iid
    ctx = Context(controller=p, source=beast)
    pairs = (('blue_00_00_03_00', 'blue_00_00_03_01'), ('blue_02_01_03_01', 'blue_02_01_03_02'))
    assert e.apply_pc03_evolution(source=beast, context=ctx, upgrades=pairs, family_id='seadra')
    assert all(x.card.id == 'blue_00_00_03_01' for x in copies + [nested])
    assert other.card.id == 'blue_00_00_03_00'
    assert beast.card.id == 'blue_02_01_03_02'
    assert (beast.iid, beast.rested, beast.bp_mod, beast.permanent_bp_mod) == (original_id, True, 100, 200)
    assert not e.can_pc03_evolve(p, 'seadra') and e.can_pc03_evolve(p, 'juy')
    assert not e.apply_pc03_evolution(source=beast, context=ctx, upgrades=pairs, family_id='seadra')
    juy = put(e, p, 'blue_05_01_03_00', AreaType.FIELD)
    bruna = put(e, p, 'blue_00_00_03_03', AreaType.BASE)
    juy_pairs = (('blue_05_01_03_00', 'blue_05_01_03_01'), ('blue_00_00_03_03', 'blue_00_00_03_04'))
    assert e.apply_pc03_evolution(source=juy, context=ctx, upgrades=juy_pairs, family_id='juy')
    assert (juy.card.id, bruna.card.id) == ('blue_05_01_03_01', 'blue_00_00_03_04')
    clone = e.clone_for_simulation()
    assert not clone.can_pc03_evolve(clone.state.players[0], 'seadra')
    assert e.add_card_from_outside_to_hand(p, 'blue_02_01_03_01').card.id == 'blue_02_01_03_02'
    e.state.turn += 1
    assert e.can_pc03_evolve(p, 'seadra')
    e.state.active_idx = 1
    assert e.can_pc03_evolve(q, 'seadra') and not e.can_pc03_evolve(p, 'seadra')


def test_lahrs_no_allowance_outside_capacity_and_deck():
    e, p, _ = game()
    source = put(e, p, 'colorless_00_00_03_00', AreaType.BASE)
    e.apply_pc03_evolution(source=source, context=Context(controller=p, source=source),
        upgrades=(('colorless_00_00_03_00', 'colorless_00_00_03_01'),), family_id=None)
    assert not p.pc03_evolution_turns
    assert source.card.id == 'colorless_00_00_03_01'
    assert not is_user_deck_card_id('colorless_04_01_03_02')
    for _ in range(10):
        put(e, p, 'blue_00_00_03_00', AreaType.HAND)
    generated = e.add_card_from_outside_to_hand(p, 'colorless_04_01_03_02')
    assert generated in p.trash and generated.area is AreaType.TRASH
    assert e.zone_move_events[-1]['from'] is AreaType.OUTSIDE
    p.movement_right_count = 1
    with pytest.raises(IllegalActionError):
        e.move_card(source, 'base_to_field')


def test_real_session_summon_only_one_family_use():
    s = GameSession(seed=1, mode='debug-card-lab')
    setup_debug_lab(s, 'blue_02_02_01r_00', zone='hand', compact_board=True, player_forces=[], opponent_forces=[])
    add_debug_card_to_zone(s, 'blue_02_01_03_01', side='P1', zone='field')
    add_debug_card_to_zone(s, 'blue_02_01_03_01', side='P1', zone='field')
    add_debug_card_to_zone(s, 'blue_00_00_03_00', side='P1', zone='base')
    s._prompt_main_action()
    opt = next(x for x in s.prompt['options'] if x.get('cardId') == 'blue_02_02_01r_00' or x.get('iid') == s.engine.state.players[0].hand[0].iid)
    payload = {'paymentBaseIids': opt['paymentDefaultIids']} if opt.get('paymentDefaultIids') is not None else None
    result = s.choose(s.prompt['id'], opt['id'], payload)
    assert result['error'] is None
    p = s.engine.state.players[0]
    assert sum(ci.card.id == 'blue_02_01_03_02' for ci in p.field) == 2
    assert any(ci.card.id == 'blue_00_00_03_01' for ci in p.base)
    assert p.pc03_evolution_turns == {'seadra': s.engine.state.turn}
from zz.effects import EffectTiming


def test_evolution_queue_filters_wrong_race_source_and_controller_then_rechecks():
    e, p, q = game()
    beast1 = put(e, p, 'blue_02_01_03_01', AreaType.FIELD)
    beast2 = put(e, p, 'blue_02_01_03_01', AreaType.FIELD)
    wrong = put(e, p, 'red_02_02_00_00', AreaType.HAND)
    e.summon_from_hand(p, wrong, resolve_triggers=False)
    assert not any(getattr(x.trigger, 'params', {}).get('pc03_evolution_family') == 'seadra' for x in e.triggers._queue)
    enemy = put(e, q, 'blue_02_02_01r_00', AreaType.HAND)
    e.summon_from_hand(q, enemy, resolve_triggers=False)
    assert not any(getattr(x.trigger, 'params', {}).get('pc03_evolution_family') == 'seadra' for x in e.triggers._queue)
    ally = put(e, p, 'blue_02_02_01r_00', AreaType.HAND)
    e.summon_from_hand(p, ally, resolve_triggers=False)
    assert sum(getattr(x.trigger, 'params', {}).get('pc03_evolution_family') == 'seadra' for x in e.triggers._queue) == 2
    seen = []
    def inspect(pending):
        if getattr(pending.trigger, 'params', {}).get('pc03_evolution_family') == 'seadra':
            seen.append(pending.instance.iid)
        return False
    e.defer_trigger_choice = inspect
    e.triggers.resolve_all()
    assert len(seen) == 1
    assert beast1.card.id == beast2.card.id == 'blue_02_01_03_02'
    assert p.pc03_evolution_turns == {'seadra': 1}


def test_evolution_excludes_non_hand_summon_and_foreign_context():
    e, p, q = game()
    put(e, p, 'blue_02_01_03_01', AreaType.FIELD)
    summon = put(e, p, 'blue_02_02_01r_00', AreaType.FIELD)
    e._record_zone_move(summon, AreaType.DECK, AreaType.FIELD)
    e.triggers.emit(EffectTiming.ON_SUMMON, Context(controller=p, source=summon))
    assert not e.triggers._queue
    e._record_zone_move(summon, AreaType.HAND, AreaType.FIELD)
    e.triggers.emit(EffectTiming.ON_SUMMON, Context(controller=q, source=summon))
    assert not e.triggers._queue
