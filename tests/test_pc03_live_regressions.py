import pytest

from zz.cards import CARD_REGISTRY
from zz.effects import EffectSpec, EffectTiming, build_effect
from zz.engine import IllegalActionError
from zz.enums import AreaType, CardType, Color, Keyword, Step
from zz.model import Action, Card, CardInstance, Context
from zz.multiplayer.views import _project_animation_events
from zz.web.session import GameSession


def setup_game():
    session = GameSession(seed=19, mode="god")
    session._clear_prompt()
    engine = session.engine
    engine.state.step = Step.MAIN
    for player in engine.state.players:
        player.field.clear()
        player.base.clear()
        player.hand.clear()
        player.trash.clear()
        player.deck.clear()
    return session, engine, *engine.state.players


def add(engine, owner, card, area=AreaType.FIELD):
    instance = CardInstance(card, owner, iid=engine.state.allocate_iid(), area=area)
    getattr(owner, area.value).append(instance)
    return instance


def test_rainbow_fairy_only_offers_movable_minion_mana():
    session, engine, owner, _ = setup_game()
    source = add(engine, owner, CARD_REGISTRY["blue_03_01_03_03"])
    summoner = add(engine, owner, CARD_REGISTRY["blue_00_00_03_00"], AreaType.BASE)
    bless = add(engine, owner, CARD_REGISTRY["blue_00_01_02_00"], AreaType.BASE)
    blocked = add(engine, owner, Card("blocked", "blocked", "blocked", CardType.B_MINION,
                                      bp=300, mana_color=Color.BLUE), AreaType.BASE)
    blocked.flags.add("cannot_move")
    token = add(engine, owner, Card("token", "token", "token", CardType.B_MINION,
                                    bp=300, is_token=True), AreaType.BASE)
    legal = add(engine, owner, CARD_REGISTRY["blue_00_01_00_00"], AreaType.BASE)
    legal.rested = True
    other_color = add(engine, owner, Card("red", "red", "red", CardType.F_MINION,
                                         bp=300, mana_color=Color.RED), AreaType.BASE)
    engine.destroy_target(source, None)
    assert session.prompt['kind'] == 'effect_target'
    options = {option.get('cardIid'): option['id'] for option in session.prompt['options']
               if option.get('cardIid') is not None}
    assert set(options) == {legal.iid, other_color.iid}
    assert {summoner.iid, bless.iid, blocked.iid, token.iid}.isdisjoint(options)
    assert {ci.iid for ci in engine._eligible_targets(owner, 'ally_minion_base')} == {legal.iid, other_color.iid}
    result = session.choose(session.prompt['id'], options[legal.iid])
    assert result['error'] is None
    assert legal in owner.field and not legal.rested and legal not in owner.base
    assert owner.movement_right_count == 0


@pytest.mark.parametrize('replace_source', [False, True])
def test_espiral_full_field_filters_targets_and_uses_selected_replacement(replace_source):
    session, engine, owner, _ = setup_game()
    engine._passive_modifiers.clear()
    engine.state.turn = 2
    source = add(engine, owner, CARD_REGISTRY['blue_06_01_03_02'])
    source.summoning_sickness = False
    fillers = [add(engine, owner, Card(f'filler-{i}', 'filler', 'filler', CardType.F_MINION,
                                       bp=300, cannot_move=i == 0)) for i in range(4)]
    summoner = add(engine, owner, CARD_REGISTRY['blue_00_00_03_00'], AreaType.BASE)
    bless = add(engine, owner, CARD_REGISTRY['blue_00_01_02_00'], AreaType.BASE)
    legal = add(engine, owner, CARD_REGISTRY['blue_00_01_00_00'], AreaType.BASE)
    legal.rested = True
    override_blue = add(engine, owner, Card('green-blue-mana', 'green', 'green', CardType.B_MINION,
                                             bp=300, printed_color=Color.GREEN, mana_color=Color.GREEN), AreaType.BASE)
    override_blue.mana_color_override = Color.BLUE
    override_red = add(engine, owner, Card('blue-red-mana', 'blue', 'blue', CardType.B_MINION,
                                            bp=300, printed_color=Color.BLUE, mana_color=Color.BLUE), AreaType.BASE)
    override_red.mana_color_override = Color.RED
    flagged = add(engine, owner, Card('flagged', 'flagged', 'flagged', CardType.B_MINION,
                                       bp=300, printed_color=Color.BLUE, mana_color=Color.BLUE), AreaType.BASE)
    flagged.flags.add('cannot_move')
    session._refresh_visual_snapshot()
    session._declare_attack(source, engine.legal_attack_targets(source)[0])
    assert session.prompt['kind'] == 'effect_target'
    options = {option.get('cardIid'): option['id'] for option in session.prompt['options']
               if option.get('cardIid') is not None}
    assert set(options) == {legal.iid, override_blue.iid}
    assert {summoner.iid, bless.iid, override_red.iid, flagged.iid}.isdisjoint(options)
    result = session.choose(session.prompt['id'], options[override_blue.iid])
    assert result['error'] is None
    assert session.prompt['kind'] == 'effect_target'
    assert session.prompt['choiceKind'] == 'ally_minion'
    replacement_options = {option.get('cardIid'): option['id'] for option in session.prompt['options']}
    assert {source.iid, *(filler.iid for filler in fillers)} <= set(replacement_options)
    chosen = source if replace_source else fillers[0]
    result = session.choose(session.prompt['id'], replacement_options[chosen.iid])
    assert result['error'] is None
    assert chosen in owner.trash and override_blue in owner.field and not override_blue.rested
    assert len(owner.field) == 5 and owner.movement_right_count == 0
    assert session._pending_effect is None
    if replace_source:
        assert session._attack is None
    else:
        assert engine.effective_bp(source) == 700 and engine.effective_dp(source) == 2


def test_move_effect_rejects_immovable_mana_before_ejecting_replacement():
    _, engine, owner, _ = setup_game()
    locked = add(engine, owner, CARD_REGISTRY['blue_00_00_03_00'], AreaType.BASE)
    fillers = [add(engine, owner, Card(f'field-{i}', 'field', 'field', CardType.F_MINION, bp=300))
               for i in range(5)]
    with pytest.raises(IllegalActionError, match='cannot move'):
        engine.move_base_minion_to_field(owner, locked, replace_field_iid=fillers[0].iid)
    assert locked in owner.base and owner.field == fillers and not owner.trash


def test_rainbow_fairy_with_no_movable_mana_does_not_leave_a_choice_open():
    session, engine, owner, _ = setup_game()
    source = add(engine, owner, CARD_REGISTRY['blue_03_01_03_03'])
    summoner = add(engine, owner, CARD_REGISTRY['blue_00_00_03_00'], AreaType.BASE)
    engine.destroy_target(source, None)
    assert source in owner.trash and summoner in owner.base
    assert not session.prompt or session.prompt['kind'] != 'effect_target'


def test_rainbow_fairy_handles_a_full_field_before_its_target_is_chosen():
    session, engine, owner, _ = setup_game()
    source = add(engine, owner, CARD_REGISTRY['blue_03_01_03_03'])
    fillers = [add(engine, owner, Card(f'field-{i}', 'field', 'field', CardType.F_MINION, bp=300))
               for i in range(4)]
    legal = add(engine, owner, CARD_REGISTRY['blue_00_01_00_00'], AreaType.BASE)
    engine.destroy_target(source, None)
    assert session.prompt['choiceKind'] == 'ally_minion_base'
    # Another entry can fill the freed slot before the pending move resolves.
    add(engine, owner, Card('fifth', 'fifth', 'fifth', CardType.F_MINION, bp=300))
    target = next(option for option in session.prompt['options'] if option.get('cardIid') == legal.iid)
    result = session.choose(session.prompt['id'], target['id'])
    assert result['error'] is None and session.prompt['choiceKind'] == 'ally_minion'
    replacement = next(option for option in session.prompt['options'] if option.get('cardIid') == fillers[0].iid)
    result = session.choose(session.prompt['id'], replacement['id'])
    assert result['error'] is None
    assert legal in owner.field and fillers[0] in owner.trash and len(owner.field) == 5


@pytest.mark.parametrize('source_id,timing', [
    ('blue_08_02_01_00', EffectTiming.ON_SUMMON),
    ('blue_06_02_02r_00', EffectTiming.ON_DAMAGE_PLAYER),
])
def test_other_minion_mana_move_effects_share_legality_and_field_replacement(source_id, timing):
    session, engine, owner, opponent = setup_game()
    source = add(engine, owner, CARD_REGISTRY[source_id])
    fillers = [add(engine, owner, Card(f'field-{i}', 'field', 'field', CardType.F_MINION, bp=300))
               for i in range(4)]
    locked = add(engine, owner, CARD_REGISTRY['blue_00_00_03_00'], AreaType.BASE)
    legal = add(engine, owner, CARD_REGISTRY['blue_00_01_00_00'], AreaType.BASE)
    ctx = Context(controller=owner, source=source, target=opponent)
    engine._resolve_source_effects(source, timing, ctx)
    assert session.prompt['kind'] == 'effect_target' and session.prompt['choiceKind'] == 'ally_minion_base'
    options = {option.get('cardIid'): option['id'] for option in session.prompt['options']
               if option.get('cardIid') is not None}
    assert legal.iid in options and locked.iid not in options
    result = session.choose(session.prompt['id'], options[legal.iid])
    assert result['error'] is None and session.prompt['choiceKind'] == 'ally_minion'
    replacement = next(option for option in session.prompt['options'] if option.get('cardIid') == fillers[0].iid)
    result = session.choose(session.prompt['id'], replacement['id'])
    assert result['error'] is None
    assert legal in owner.field and locked in owner.base and fillers[0] in owner.trash
    assert len(owner.field) == 5 and session._pending_effect is None


def test_automatic_policy_selects_a_movable_mana_and_field_replacement():
    from zz.ai import PassOnlyPolicy

    _, engine, owner, _ = setup_game()
    engine._passive_modifiers.clear()
    engine.defer_trigger_choice = None
    engine.defer_source_effect_choice = None
    engine.set_policies(PassOnlyPolicy(), PassOnlyPolicy())
    fillers = [add(engine, owner, Card(f'field-{i}', 'field', 'field', CardType.F_MINION, bp=300))
               for i in range(4)]
    source = add(engine, owner, CARD_REGISTRY['blue_06_01_03_02'])
    locked = add(engine, owner, CARD_REGISTRY['blue_00_00_03_00'], AreaType.BASE)
    legal = add(engine, owner, CARD_REGISTRY['blue_00_01_00_00'], AreaType.BASE)
    engine._resolve_source_effects(source, EffectTiming.ON_ATTACK, Context(controller=owner, source=source))
    assert locked in owner.base and legal in owner.field and fillers[0] in owner.trash
    assert len(owner.field) == 5 and engine.effective_bp(source) == 700


def test_aleshand_moves_selected_mana_and_replaces_three_on_full_field():
    session, engine, owner, _ = setup_game()
    source = add(engine, owner, CARD_REGISTRY['blue_08_02_01_00'])
    fillers = [add(engine, owner, Card(f'field-{i}', 'field', 'field', CardType.F_MINION, bp=300))
               for i in range(4)]
    locked = add(engine, owner, CARD_REGISTRY['blue_00_00_03_00'], AreaType.BASE)
    movable = [add(engine, owner, CARD_REGISTRY['blue_00_01_00_00'], AreaType.BASE) for _ in range(3)]
    engine._resolve_source_effects(source, EffectTiming.ON_SUMMON, Context(controller=owner, source=source))
    assert session.prompt['choiceKind'] == 'ally_minion_base'
    options = {option.get('cardIid'): option['id'] for option in session.prompt['options']
               if option.get('cardIid') is not None}
    assert set(options) == {card.iid for card in movable} and locked.iid not in options
    choices = [options[card.iid] for card in movable]
    result = session.choose(session.prompt['id'], choices[0], {'selectedOptionIds': choices})
    assert result['error'] is None and session.prompt['choiceKind'] == 'ally_minion'
    options = {option.get('cardIid'): option['id'] for option in session.prompt['options']}
    replacements = [options[card.iid] for card in fillers[:3]]
    result = session.choose(session.prompt['id'], replacements[0], {'selectedOptionIds': replacements})
    assert result['error'] is None
    assert all(card in owner.field and not card.rested for card in movable)
    assert all(card in owner.trash for card in fillers[:3]) and locked in owner.base
    assert len(owner.field) == 5 and session._pending_effect is None


@pytest.mark.parametrize('entry', ['movement_right', 'effect'])
def test_moving_minion_mana_triggers_same_base_removal_rules(entry):
    _, engine, owner, _ = setup_game()
    add(engine, owner, CARD_REGISTRY['red_06_02_02_01'])
    mana = add(engine, owner, CARD_REGISTRY['blue_00_01_00_00'], AreaType.BASE)
    owner.movement_right_count = 1
    if entry == 'movement_right':
        engine.move_card(mana, 'base_to_field')
    else:
        engine.move_base_minion_to_field(owner, mana, rested=False)
    assert mana in owner.field
    assert len(owner.base) == 1 and engine._mana_color_of(owner.base[0]) is Color.RED
    assert owner.base[0].rested
    assert owner.movement_right_count == (0 if entry == 'movement_right' else 1)


@pytest.mark.parametrize("entry_method", ["movement", "effect"])
@pytest.mark.parametrize("base_bp", [100, 200])
def test_great_tiger_triggers_when_opponent_minion_moves_from_base(entry_method, base_bp):
    session, engine, owner, opponent = setup_game()
    engine._passive_modifiers.clear()
    tiger = add(engine, opponent, CARD_REGISTRY["green_03_01_03_00"])
    moved = add(engine, owner, Card("moving", "moving", "moving", CardType.F_MINION,
        bp=base_bp, effects=[build_effect("draw_cards", EffectTiming.ON_SUMMON, amount=1)]), AreaType.BASE)
    drawn = add(engine, owner, Card("draw", "draw", "draw", CardType.F_MINION, bp=300), AreaType.DECK)
    owner.movement_right_count = 1
    if entry_method == "movement":
        engine.move_card(moved, "base_to_field")
    else:
        engine.move_base_minion_to_field(owner, moved)
    assert drawn in owner.deck, "moving is not summoning"
    assert owner.movement_right_count == (0 if entry_method == "movement" else 1)
    assert sum(ci is tiger for ci, _, _ in engine.effect_events) == 1
    if base_bp == 100:
        assert moved in owner.trash
    else:
        assert moved in owner.field and engine.effective_bp(moved) == 100


@pytest.mark.parametrize("entry_method", ["movement", "effect"])
def test_great_tiger_does_not_weaken_its_owners_minion_entering_from_base(entry_method):
    _, engine, owner, _ = setup_game()
    engine._passive_modifiers.clear()
    tiger = add(engine, owner, CARD_REGISTRY["green_03_01_03_00"])
    moved = add(engine, owner, Card("moving", "moving", "moving", CardType.F_MINION, bp=100), AreaType.BASE)
    owner.movement_right_count = 1
    if entry_method == "movement":
        engine.move_card(moved, "base_to_field")
    else:
        engine.move_base_minion_to_field(owner, moved)
    assert moved in owner.field and engine.effective_bp(moved) == 100
    assert not any(ci is tiger for ci, _, _ in engine.effect_events)


def test_great_tiger_movement_result_presents_entry_before_bp_zero_destruction():
    session, engine, owner, opponent = setup_game()
    engine._passive_modifiers.clear()
    add(engine, opponent, CARD_REGISTRY["green_03_01_03_00"])
    moved = add(engine, owner, Card("moving", "moving", "moving", CardType.F_MINION, bp=100), AreaType.BASE)
    owner.movement_right_count = 1
    session._refresh_visual_snapshot()
    session._prompt_main_action()
    option = next(option for option in session.prompt["options"] if option.get("kind") == "move_card"
                  and option.get("iid") == moved.iid and option.get("direction") == "base_to_field")
    response = session.choose(session.prompt["id"], option["id"])
    assert response["error"] is None
    assert moved in owner.trash
    events = response["animationEvents"]
    arrival = next(index for index, event in enumerate(events) if event.get("type") == "zone_move"
                   and event.get("card", {}).get("iid") == moved.iid and event.get("toArea") == "field")
    destruction = next(index for index, event in enumerate(events) if event.get("type") == "destroy"
                       and event.get("card", {}).get("iid") == moved.iid)
    assert arrival < destruction


@pytest.mark.parametrize("base_bp", [100, 200])
def test_great_tiger_debuffs_opposing_minion_actually_summoned(base_bp):
    session, engine, owner, opponent = setup_game()
    engine._passive_modifiers.clear()
    add(engine, opponent, CARD_REGISTRY["green_03_01_03_00"])
    summoned = add(engine, owner, Card("summoned", "summoned", "summoned", CardType.F_MINION, bp=base_bp), AreaType.HAND)
    session._refresh_visual_snapshot()
    session._prompt_main_action()
    option = next(option for option in session.prompt["options"] if option.get("kind") == "play_card"
                  and option.get("iid") == summoned.iid)
    result = session.choose(session.prompt["id"], option["id"])
    assert result["error"] is None
    if base_bp == 100:
        assert summoned in owner.trash
    else:
        assert summoned in owner.field and engine.effective_bp(summoned) == 100


@pytest.mark.parametrize("method", ["play", "from_hand", "flash"])
@pytest.mark.parametrize("base_bp", [100, 200])
def test_great_tiger_resolves_before_new_minions_summon_effect(method, base_bp):
    _, engine, owner, opponent = setup_game()
    engine.defer_trigger_choice = None
    engine._passive_modifiers.clear()
    add(engine, opponent, CARD_REGISTRY["green_03_01_03_00"])
    calls = []
    card = Card("summoned-effect", "summoned-effect", "summoned-effect", CardType.F_MINION,
                bp=base_bp, keywords=[Keyword.FLYING], effects=[
                    EffectSpec(EffectTiming.ON_SUMMON, lambda *_: calls.append("summon")),
                    EffectSpec(EffectTiming.ON_DESTROY, lambda *_: calls.append("destroy")),
                ])
    summoned = add(engine, owner, card, AreaType.HAND)
    if method == "play":
        engine.play_card(summoned)
    elif method == "from_hand":
        engine.summon_from_hand(owner, summoned)
    else:
        engine.apply_flash_action(owner, Action("play_card", {"iid": summoned.iid}))
    if base_bp == 100:
        assert summoned in owner.trash
        assert calls == ["destroy"]
    else:
        assert summoned in owner.field and engine.effective_bp(summoned) == 100
        assert calls == ["summon"]


def test_great_tiger_destroyed_summon_does_not_offer_effect_target():
    session, engine, owner, opponent = setup_game()
    engine._passive_modifiers.clear()
    add(engine, opponent, CARD_REGISTRY["green_03_01_03_00"])
    card = Card("summoned-target", "summoned-target", "summoned-target", CardType.F_MINION,
                bp=100, effects=[build_effect("rest_targets", EffectTiming.ON_SUMMON,
                                             target_kind="enemy_minion")])
    summoned = add(engine, owner, card, AreaType.HAND)
    session._refresh_visual_snapshot()
    session._prompt_main_action()
    option = next(option for option in session.prompt["options"]
                  if option.get("kind") == "play_card" and option.get("iid") == summoned.iid)
    response = session.choose(session.prompt["id"], option["id"])
    assert response["error"] is None
    assert summoned in owner.trash
    assert not session.prompt or session.prompt["kind"] != "effect_target"
    assert not any(event.get("type") == "effect" and event.get("card", {}).get("iid") == summoned.iid
                   for event in response["animationEvents"])


def test_summon_effects_already_activated_continue_if_source_is_destroyed():
    _, engine, owner, opponent = setup_game()
    engine.defer_trigger_choice = None
    engine._passive_modifiers.clear()
    add(engine, opponent, CARD_REGISTRY["green_03_01_03_00"])
    calls = []

    def destroy_self(source, state, _ctx):
        calls.append("first")
        state.engine.destroy_target(source, None)

    card = Card("two-effects", "two-effects", "two-effects", CardType.F_MINION, bp=300,
                effects=[EffectSpec(EffectTiming.ON_SUMMON, destroy_self),
                         EffectSpec(EffectTiming.ON_SUMMON, lambda *_: calls.append("second"))])
    summoned = add(engine, owner, card, AreaType.HAND)
    engine.play_card(summoned)
    assert summoned in owner.trash
    assert calls == ["first", "second"]


def test_great_tiger_resolves_before_summon_inside_another_effect():
    _, engine, owner, opponent = setup_game()
    engine.defer_trigger_choice = None
    engine._passive_modifiers.clear()
    add(engine, opponent, CARD_REGISTRY["green_03_01_03_00"])
    calls = []
    card = Card("nested-summon", "nested-summon", "nested-summon", CardType.F_MINION, bp=100,
                effects=[EffectSpec(EffectTiming.ON_SUMMON, lambda *_: calls.append("summon")),
                         EffectSpec(EffectTiming.ON_DESTROY, lambda *_: calls.append("destroy"))])
    summoned = add(engine, owner, card, AreaType.HAND)
    source = add(engine, owner, Card("source", "source", "source", CardType.F_MINION, bp=300))

    def summon_from_effect(_source, state, _ctx):
        state.engine.summon_from_hand(owner, summoned)

    engine._run_effect_callback(summon_from_effect, source, engine.state, Context(controller=owner, source=source))
    assert summoned in owner.trash
    assert calls == ["destroy"]


def test_great_tiger_handles_summon_inside_state_based_destruction():
    _, engine, owner, opponent = setup_game()
    engine.defer_trigger_choice = None
    engine._passive_modifiers.clear()
    add(engine, opponent, CARD_REGISTRY["green_03_01_03_00"])
    calls = []
    card = Card("nested-summon", "nested-summon", "nested-summon", CardType.F_MINION, bp=100,
                effects=[EffectSpec(EffectTiming.ON_SUMMON, lambda *_: calls.append("summon")),
                         EffectSpec(EffectTiming.ON_DESTROY, lambda *_: calls.append("destroy"))])
    summoned = add(engine, owner, card, AreaType.HAND)

    def summon_on_destroy(_source, state, _ctx):
        state.engine.summon_from_hand(owner, summoned)

    dying = add(engine, owner, Card("dying", "dying", "dying", CardType.F_MINION, bp=0,
                                    effects=[EffectSpec(EffectTiming.ON_DESTROY, summon_on_destroy)]))
    engine._resolve_state_based_actions()
    assert dying in owner.trash and summoned in owner.trash
    assert calls == ["destroy"]


def test_summon_listeners_still_observe_a_minion_destroyed_on_entry():
    _, engine, owner, opponent = setup_game()
    engine.defer_trigger_choice = None
    engine._passive_modifiers.clear()
    add(engine, opponent, CARD_REGISTRY["green_03_01_03_00"])
    calls = []
    listener = Card("listener", "listener", "listener", CardType.F_MINION, bp=300,
                    effects=[EffectSpec(EffectTiming.ON_SUMMON, lambda _ci, _state, ctx: calls.append(ctx.source),
                                        condition=lambda ci, _state, ctx: ctx.source is not ci)])
    add(engine, owner, listener)
    summoned = add(engine, owner, Card("summoned", "summoned", "summoned", CardType.F_MINION, bp=100,
                                      effects=[EffectSpec(EffectTiming.ON_SUMMON,
                                                          lambda *_: calls.append("own"))]), AreaType.HAND)
    engine.summon_from_hand(owner, summoned)
    assert summoned in owner.trash
    assert calls == [summoned]


def test_destroyed_summon_cannot_activate_by_returning_to_field():
    _, engine, owner, opponent = setup_game()
    engine.defer_trigger_choice = None
    engine._passive_modifiers.clear()
    add(engine, opponent, CARD_REGISTRY["green_03_01_03_00"])
    calls = []

    def return_from_trash(source, state, _ctx):
        source.permanent_bp_mod = 200
        state.engine.summon_from_trash(source.owner, source)

    card = Card("reviving", "reviving", "reviving", CardType.F_MINION, bp=100, effects=[
        EffectSpec(EffectTiming.ON_SUMMON, lambda *_: calls.append("summon")),
        EffectSpec(EffectTiming.ON_DESTROY, return_from_trash),
    ])
    summoned = add(engine, owner, card, AreaType.HAND)
    engine.summon_from_hand(owner, summoned)
    assert summoned in owner.field
    assert calls == []


def test_entry_choice_finishes_before_tiger_and_dead_summons_effect():
    session, engine, owner, opponent = setup_game()
    engine._passive_modifiers.clear()
    listener = Card("listener", "listener", "listener", CardType.F_MINION, bp=300, effects=[
        build_effect("rest_targets", EffectTiming.ON_ENTER_FIELD, target_kind="enemy_minion",
                     condition=lambda source, _state, ctx: ctx.source is not source),
    ])
    add(engine, owner, listener)
    tiger = add(engine, opponent, CARD_REGISTRY["green_03_01_03_00"])
    card = Card("summoned-target", "summoned-target", "summoned-target", CardType.F_MINION,
                bp=100, effects=[build_effect("rest_targets", EffectTiming.ON_SUMMON,
                                             target_kind="enemy_minion")])
    summoned = add(engine, owner, card, AreaType.HAND)
    session._refresh_visual_snapshot()
    session._prompt_main_action()
    option = next(option for option in session.prompt["options"]
                  if option.get("kind") == "play_card" and option.get("iid") == summoned.iid)
    response = session.choose(session.prompt["id"], option["id"])
    assert response["error"] is None
    assert session.prompt["kind"] == "effect_target"
    assert session.prompt["card"]["cardId"] == "listener"
    option = next(option for option in session.prompt["options"] if option.get("cardIid") == tiger.iid)
    response = session.choose(session.prompt["id"], option["id"])
    assert response["error"] is None
    assert summoned in owner.trash and tiger.rested
    assert not session.prompt or session.prompt["kind"] != "effect_target"


@pytest.mark.parametrize("target_count", [1, 2, 3])
def test_archer_and_millie_offer_and_rest_all_required_targets(target_count):
    session, engine, owner, opponent = setup_game()
    archer = add(engine, owner, CARD_REGISTRY["green_05_01_03_00"], AreaType.HAND)
    add(engine, owner, CARD_REGISTRY["green_04_02_01_01"])
    targets = [add(engine, opponent, Card(f"target-{i}", "target", "target", CardType.F_MINION, bp=500))
               for i in range(target_count)]
    for i in range(5):
        add(engine, owner, Card(f"mana-{i}", "mana", "mana", CardType.B_MINION,
                                mana_color=Color.GREEN), AreaType.BASE)
    session._refresh_visual_snapshot()
    session._prompt_main_action()
    option = next(option for option in session.prompt["options"]
                  if option.get("kind") == "play_card" and option.get("iid") == archer.iid)
    response = session.choose(session.prompt["id"], option["id"])
    assert response["error"] is None
    assert session.prompt["kind"] == "effect_target"
    required = min(2, target_count)
    assert session.prompt["requiredTargetCount"] == required
    options = {option.get("cardIid"): option["id"] for option in session.prompt["options"]}
    assert set(options) == {target.iid for target in targets}
    selected = [options[target.iid] for target in targets[-required:]]
    response = session.choose(session.prompt["id"], selected[0], {"selectedOptionIds": selected})
    assert response["error"] is None
    assert [target.rested for target in targets] == [target.iid in {t.iid for t in targets[-required:]}
                                                      for target in targets]


@pytest.mark.parametrize("force_destroyed", [False, True])
def test_archer_and_millie_respect_sphinx_and_target_availability(force_destroyed):
    from zz.web.debug_tools import replace_debug_forces

    session, engine, owner, opponent = setup_game()
    replace_debug_forces(session, "P2", ["force_sei", "force_chi"])
    next(force for force in opponent.forces if force.force.id == "force_sei").destroyed = force_destroyed
    archer = add(engine, owner, CARD_REGISTRY["green_05_01_03_00"], AreaType.HAND)
    add(engine, owner, CARD_REGISTRY["green_04_02_01_01"])
    low = add(engine, opponent, Card("low", "low", "low", CardType.F_MINION, bp=500,
                                    cost={Color.COLORLESS: 5}))
    high = add(engine, opponent, Card("high", "high", "high", CardType.F_MINION, bp=500,
                                     cost={Color.COLORLESS: 6}))
    for i in range(5):
        add(engine, owner, Card(f"mana-{i}", "mana", "mana", CardType.B_MINION,
                                mana_color=Color.GREEN), AreaType.BASE)
    session._refresh_visual_snapshot()
    session._prompt_main_action()
    option = next(option for option in session.prompt["options"]
                  if option.get("kind") == "play_card" and option.get("iid") == archer.iid)
    response = session.choose(session.prompt["id"], option["id"])
    assert response["error"] is None
    assert session.prompt["kind"] == "effect_target"
    options = {option.get("cardIid"): option["id"] for option in session.prompt["options"]}
    assert set(options) == ({low.iid, high.iid} if force_destroyed else {high.iid})
    selected = list(options.values())
    assert session.prompt["requiredTargetCount"] == len(selected)
    response = session.choose(session.prompt["id"], selected[0], {"selectedOptionIds": selected})
    assert response["error"] is None
    assert high.rested and low.rested is force_destroyed


@pytest.mark.parametrize("base_bp", [100, 200])
def test_multiple_great_tigers_do_not_modify_a_minion_after_it_leaves_field(base_bp):
    _, engine, owner, opponent = setup_game()
    engine._passive_modifiers.clear()
    for _ in range(2):
        add(engine, opponent, CARD_REGISTRY["green_03_01_03_00"])
    moved = add(engine, owner, Card("moving", "moving", "moving", CardType.F_MINION, bp=base_bp), AreaType.BASE)
    owner.movement_right_count = 1
    engine.move_card(moved, "base_to_field")
    assert moved in owner.trash
    assert moved.bp_mod == 0, "an entry effect cannot modify a card after it has left the field"


@pytest.mark.parametrize("base_bp", [100, 200])
def test_great_tiger_triggers_when_opposing_token_enters(base_bp):
    _, engine, owner, opponent = setup_game()
    engine._passive_modifiers.clear()
    tiger = add(engine, opponent, CARD_REGISTRY["green_03_01_03_00"])
    token = engine.create_token(owner, Card("token", "token", "token", CardType.F_MINION, bp=base_bp))
    engine.triggers.resolve_all()
    assert sum(ci is tiger for ci, _, _ in engine.effect_events) == 1
    if base_bp == 100:
        assert token not in owner.field and token not in owner.trash and token not in owner.removed
    else:
        assert token in owner.field and engine.effective_bp(token) == 100


@pytest.mark.parametrize("card_id,mana_color", [
    ("blue_01_01_03_00", Color.BLUE),
    ("green_01_01_03_00", Color.GREEN),
])
def test_conditional_when_destroyed_does_not_listen_to_other_minions(card_id, mana_color):
    session, engine, owner, opponent = setup_game()
    source = add(engine, owner, CARD_REGISTRY[card_id])
    add(engine, owner, Card("evoker", "evoker", "evoker", CardType.B_MINION,
                            mana_color=mana_color, race_jp="エヴォーカー"), AreaType.BASE)
    other = add(engine, opponent, Card("other", "other", "other", CardType.F_MINION, bp=300))
    engine.destroy_target(other, None)
    assert not any(ci is source for ci, _, _ in engine.effect_events)
    assert session.prompt is None


def test_jellygirl_own_destruction_still_offers_legal_blue_magic():
    session, engine, owner, _ = setup_game()
    source = add(engine, owner, CARD_REGISTRY["blue_01_01_03_00"])
    add(engine, owner, Card("evoker", "evoker", "evoker", CardType.B_MINION,
                            mana_color=Color.BLUE, race_jp="エヴォーカー"), AreaType.BASE)
    magic = add(engine, owner, Card("blue-magic", "blue-magic", "blue-magic", CardType.MAGIC,
                                    cost={Color.BLUE: 1}, printed_color=Color.BLUE), AreaType.TRASH)
    engine.destroy_target(source, None)
    assert session.prompt is not None
    option = next(option for option in session.prompt["options"] if option.get("cardIid") == magic.iid)
    assert session.choose(session.prompt["id"], option["id"])["error"] is None
    assert magic in owner.hand


def test_full_field_summon_replaces_jellygirl_without_destroy_triggers():
    session, engine, owner, opponent = setup_game()
    jelly = add(engine, owner, CARD_REGISTRY["blue_01_01_03_00"])
    for i in range(4):
        add(engine, owner, Card(f"filler-{i}", "filler", "filler", CardType.F_MINION, bp=300))
    add(engine, owner, Card("evoker", "evoker", "evoker", CardType.B_MINION,
                            mana_color=Color.BLUE, race_jp="エヴォーカー"), AreaType.BASE)
    magic = add(engine, owner, Card("blue-magic", "blue-magic", "blue-magic", CardType.MAGIC,
                                    cost={Color.BLUE: 1}, printed_color=Color.BLUE), AreaType.TRASH)
    calls = []
    listener = Card("listener", "listener", "listener", CardType.F_MINION, bp=300,
                    effects=[EffectSpec(EffectTiming.ON_DESTROY, lambda *_: calls.append("destroy"),
                                        condition=lambda _ci, _state, ctx: ctx.target is jelly)])
    add(engine, opponent, listener)
    incoming = add(engine, owner, Card("incoming", "incoming", "incoming", CardType.F_MINION, bp=300),
                   AreaType.HAND)
    session._refresh_visual_snapshot()
    session._prompt_main_action()
    option = next(option for option in session.prompt["options"]
                  if option.get("kind") == "play_card" and option.get("iid") == incoming.iid
                  and option.get("replace_field_iid") == jelly.iid)
    result = session.choose(session.prompt["id"], option["id"])
    assert result["error"] is None
    assert jelly in owner.trash and incoming in owner.field and magic in owner.trash
    assert not session.prompt or session.prompt["kind"] != "effect_target"
    assert calls == []
    assert not any(event.get("type") in ("destroy", "effect")
                   and event.get("card", {}).get("iid") == jelly.iid
                   for event in result["animationEvents"])
    assert any(event.get("type") == "zone_move" and event.get("card", {}).get("iid") == jelly.iid
               and event.get("fromArea") == "field" and event.get("toArea") == "trash"
               and event.get("cause") == "replacement"
               for event in result["animationEvents"])


@pytest.mark.parametrize("entry", ["summon", "move", "token"])
@pytest.mark.parametrize("replaced_token", [False, True])
def test_full_field_replacement_is_not_destruction(entry, replaced_token):
    _, engine, owner, opponent = setup_game()
    engine.defer_trigger_choice = None
    calls = []
    victim_card = Card("victim", "victim", "victim", CardType.F_MINION, bp=300,
                       is_token=replaced_token,
                       effects=[EffectSpec(EffectTiming.ON_DESTROY, lambda *_: calls.append("own"))])
    victim = add(engine, owner, victim_card)
    for i in range(4):
        add(engine, owner, Card(f"filler-{i}", "filler", "filler", CardType.F_MINION, bp=300))
    listener = Card("listener", "listener", "listener", CardType.F_MINION, bp=300,
                    effects=[EffectSpec(EffectTiming.ON_DESTROY, lambda *_: calls.append("listener"),
                                        condition=lambda _ci, _state, ctx: ctx.target is victim)])
    add(engine, opponent, listener)
    card = Card("incoming", "incoming", "incoming", CardType.F_MINION, bp=300)
    if entry == "summon":
        incoming = add(engine, owner, card, AreaType.HAND)
        engine.summon_from_hand(owner, incoming, replace_field_iid=victim.iid)
    elif entry == "move":
        incoming = add(engine, owner, card, AreaType.BASE)
        owner.movement_right_count = 1
        engine.move_card(incoming, "base_to_field", replace_field_iid=victim.iid)
    else:
        incoming = engine.create_token(owner, card, replace_field_iid=victim.iid)
        engine.triggers.resolve_all()
    assert incoming in owner.field and victim not in owner.field
    assert (victim in owner.trash) is not replaced_token
    assert not replaced_token or victim not in owner.removed
    assert calls == []
    assert victim not in engine.destroy_events
    assert any(event.get("card") is victim and event.get("from") is AreaType.FIELD
               and event.get("to") is (AreaType.REMOVED if replaced_token else AreaType.TRASH)
               for event in engine.zone_move_events)


def test_replaced_blessed_host_returns_blessing_without_destroy_effects():
    _, engine, owner, _ = setup_game()
    engine.defer_trigger_choice = None
    calls = []
    host = add(engine, owner, Card("host", "host", "host", CardType.F_MINION, bp=300,
                                    effects=[EffectSpec(EffectTiming.ON_DESTROY,
                                                        lambda *_: calls.append("host"))]))
    blessing_card = Card("blessing", "blessing", "blessing", CardType.B_MINION, bp=100,
                         effects=[EffectSpec(EffectTiming.ON_DESTROY, lambda *_: calls.append("blessing"),
                                             params={"granted_by_blessing": True},
                                             active_areas=(AreaType.BLESSING,))])
    blessing = CardInstance(blessing_card, owner, iid=engine.state.allocate_iid(), area=AreaType.BLESSING)
    host.blessings.append(blessing)
    for i in range(4):
        add(engine, owner, Card(f"filler-{i}", "filler", "filler", CardType.F_MINION, bp=300))
    incoming = add(engine, owner, Card("incoming", "incoming", "incoming", CardType.F_MINION, bp=300),
                   AreaType.HAND)
    engine.summon_from_hand(owner, incoming, replace_field_iid=host.iid)
    assert host in owner.trash and incoming in owner.field
    assert blessing in owner.base and blessing.rested and not host.blessings
    assert calls == []


def test_full_field_replacement_allows_owner_to_choose_full_base_for_blessing():
    session, engine, owner, _ = setup_game()
    calls = []
    host = add(engine, owner, Card("host", "host", "host", CardType.F_MINION, bp=300,
                                    effects=[EffectSpec(EffectTiming.ON_DESTROY,
                                                        lambda *_: calls.append("host"))]))
    blessing_card = Card("blessing", "blessing", "blessing", CardType.B_MINION, bp=100,
                         effects=[EffectSpec(EffectTiming.ON_DESTROY, lambda *_: calls.append("blessing"),
                                             params={"granted_by_blessing": True},
                                             active_areas=(AreaType.BLESSING,))])
    blessing = CardInstance(blessing_card, owner, iid=engine.state.allocate_iid(), area=AreaType.BLESSING)
    host.blessings.append(blessing)
    for i in range(4):
        add(engine, owner, Card(f"filler-{i}", "filler", "filler", CardType.F_MINION, bp=300))
    old_mana = [add(engine, owner, Card(f"mana-{i}", "mana", "mana", CardType.B_MINION,
                                        mana_color=Color.GREEN), AreaType.BASE) for i in range(10)]
    incoming = add(engine, owner, Card("incoming", "incoming", "incoming", CardType.F_MINION, bp=300),
                   AreaType.HAND)
    session._refresh_visual_snapshot()
    session._prompt_main_action()
    option = next(option for option in session.prompt["options"]
                  if option.get("kind") == "play_card" and option.get("iid") == incoming.iid
                  and option.get("replace_field_iid") == host.iid)
    response = session.choose(session.prompt["id"], option["id"])
    assert response["error"] is None
    assert session.prompt["kind"] == "blessing_base_replacement"
    assert session.prompt["playerSide"] == owner.side.name
    assert host in owner.trash and incoming in owner.field
    response = session.choose(session.prompt["id"], session.prompt["options"][0]["id"])
    assert response["error"] is None
    assert len(owner.base) == 10 and blessing in owner.base and blessing.rested
    assert sum(card in owner.trash for card in old_mana) == 1
    assert not engine.pending_blessing_returns and calls == []


def test_field_replacement_keeps_effect_that_was_already_triggered():
    _, engine, owner, _ = setup_game()
    engine.defer_trigger_choice = None
    calls = []
    card = Card("attacker", "attacker", "attacker", CardType.F_MINION, bp=300,
                effects=[EffectSpec(EffectTiming.ON_ATTACK, lambda *_: calls.append("attack"),
                                    condition=lambda ci, _state, ctx: ctx.source is ci)])
    source = add(engine, owner, card)
    engine.triggers.emit(EffectTiming.ON_ATTACK, Context(controller=owner, source=source))
    assert engine.triggers.has_pending(instance=source)
    engine._eject_field_card(owner, source)
    engine.triggers.resolve_all()
    assert source in owner.trash and calls == ["attack"]


def test_green_evoker_conditional_self_destruction_still_places_rested_mana():
    _, engine, owner, _ = setup_game()
    source = add(engine, owner, CARD_REGISTRY["green_01_01_03_00"])
    add(engine, owner, Card("evoker", "evoker", "evoker", CardType.B_MINION,
                            mana_color=Color.GREEN, race_jp="エヴォーカー"), AreaType.BASE)
    engine.destroy_target(source, None)
    assert len(owner.base) == 2
    assert owner.base[-1].rested and engine._mana_color_of(owner.base[-1]) is Color.GREEN


@pytest.mark.parametrize("card_id,timing", [
    ("yellow_06_01_03_00", EffectTiming.ON_SUMMON),
    ("yellow_06_01_03_01", EffectTiming.ON_ATTACK),
    ("yellow_06_01_03_02", EffectTiming.ON_ATTACK),
    ("yellow_06_01_03_03", EffectTiming.ON_ATTACK),
    ("blue_03_01_03_02", EffectTiming.ON_ATTACK),
    ("blue_06_01_03_01", EffectTiming.ON_ATTACK),
    ("blue_06_01_03_02", EffectTiming.ON_ATTACK),
    ("green_08_02_01_00", EffectTiming.ON_ATTACK),
])
@pytest.mark.parametrize("other_side", [False, True])
def test_unconditional_summon_and_attack_clauses_only_trigger_for_source(card_id, timing, other_side):
    session, engine, owner, opponent = setup_game()
    source = add(engine, owner, CARD_REGISTRY[card_id])
    other_owner = opponent if other_side else owner
    other = add(engine, other_owner, Card("other", "other", "other", CardType.F_MINION, bp=300))
    effect = next(effect for effect in source.card.effects if effect.timing is timing and effect.target_kind is not None)
    engine.triggers.emit(timing, Context(controller=other_owner, source=other))
    assert not engine.triggers.has_pending(instance=source, trigger=effect)
    engine.triggers.resolve_all()
    assert not any(ci is source and trigger is effect for ci, trigger, _ in engine.effect_events)
    engine.triggers.emit(timing, Context(controller=owner, source=source))
    assert engine.triggers.has_pending(instance=source, trigger=effect)


@pytest.mark.parametrize("card_id,timing", [
    ("yellow_06_01_03_00", EffectTiming.ON_SUMMON),
    ("yellow_06_01_03_01", EffectTiming.ON_ATTACK),
    ("yellow_06_01_03_02", EffectTiming.ON_ATTACK),
    ("yellow_06_01_03_03", EffectTiming.ON_ATTACK),
])
def test_crow_and_godbird_own_trigger_resolves(card_id, timing):
    session, engine, owner, opponent = setup_game()
    source = add(engine, owner, CARD_REGISTRY[card_id])
    target = add(engine, opponent, Card("target", "target", "target", CardType.F_MINION,
                                       cost={Color.COLORLESS: 7}, bp=300))
    engine.triggers.emit(timing, Context(controller=owner, source=source))
    engine.triggers.resolve_all()
    assert sum(ci is source and effect.timing is timing for ci, effect, _ in engine.effect_events) == 1
    option = next(option for option in session.prompt["options"] if option.get("cardIid") == target.iid)
    assert session.choose(session.prompt["id"], option["id"])["error"] is None
    assert target in (opponent.deck if card_id in {"yellow_06_01_03_02", "yellow_06_01_03_03"} else opponent.hand)


@pytest.mark.parametrize("other_side", [False, True])
def test_crow_does_not_announce_when_another_minion_is_really_summoned(other_side):
    session, engine, owner, opponent = setup_game()
    source = add(engine, owner, CARD_REGISTRY["yellow_06_01_03_00"])
    add(engine, opponent, Card("target", "target", "target", CardType.F_MINION,
                              cost={Color.COLORLESS: 7}, bp=300))
    actor = opponent if other_side else owner
    engine.state.active_idx = 1 if other_side else 0
    played = add(engine, actor, Card("played", "played", "played", CardType.F_MINION), AreaType.HAND)
    session._prompt_main_action()
    play = next(option for option in session.prompt["options"] if option.get("kind") == "play_card" and option.get("iid") == played.iid)
    result = session.choose(session.prompt["id"], play["id"])
    assert result["error"] is None
    assert not any(event.get("type") == "effect" and event.get("card", {}).get("iid") == source.iid for event in result["animationEvents"])
    assert not (result["prompt"] and result["prompt"].get("choiceKind") == "enemy_minion")


@pytest.mark.parametrize("other_side", [False, True])
def test_godbird_does_not_announce_when_another_minion_really_attacks(other_side):
    session, engine, owner, opponent = setup_game()
    engine.state.turn = 2
    source = add(engine, owner, CARD_REGISTRY["yellow_06_01_03_02"])
    actor = opponent if other_side else owner
    engine.state.active_idx = 1 if other_side else 0
    attacker = add(engine, actor, Card("attacker", "attacker", "attacker", CardType.F_MINION, bp=300))
    session._declare_attack(attacker, engine.legal_attack_targets(attacker)[0])
    assert session.prompt is None
    assert not any(event.get("type") == "effect" and event.get("card", {}).get("iid") == source.iid for event in session._animation_events)


def test_godbird_lv3_still_listens_for_own_avian_attacking_player():
    _, engine, owner, opponent = setup_game()
    source = add(engine, owner, CARD_REGISTRY["yellow_06_01_03_03"])
    source.rested = True
    avian = add(engine, owner, Card("avian", "avian", "avian", CardType.F_MINION, race_jp="アヴィアン"))
    engine.triggers.emit(EffectTiming.ON_ATTACK, Context(controller=owner, source=avian, target=opponent))
    engine.triggers.resolve_all()
    assert not source.rested


@pytest.mark.parametrize("card_id", ["purple_03_01_03_01", "red_01_01_03_00"])
def test_conditional_self_attack_does_not_trigger_from_another_attacker(card_id):
    _, engine, owner, opponent = setup_game()
    source = add(engine, owner, CARD_REGISTRY[card_id])
    other = add(engine, owner, Card("other", "other", "other", CardType.F_MINION))
    add(engine, owner, Card("evoker", "evoker", "evoker", CardType.B_MINION,
                            mana_color=Color.RED, race_jp="エヴォーカー"), AreaType.BASE)
    target = opponent.forces[0] if card_id.startswith("purple") else opponent
    before_life = target.life
    effect = next(effect for effect in source.card.effects if effect.timing is EffectTiming.ON_ATTACK)
    engine.triggers.emit(EffectTiming.ON_ATTACK, Context(controller=owner, source=other, target=target))
    assert not engine.triggers.has_pending(instance=source, trigger=effect)
    engine.triggers.emit(EffectTiming.ON_ATTACK, Context(controller=owner, source=source, target=target))
    assert engine.triggers.has_pending(instance=source, trigger=effect)
    engine.triggers.resolve_all()
    if card_id.startswith("purple"):
        assert target.life == before_life - 1
    else:
        assert source.battle_dp_mod == 1


def test_previous_set_next_red_summon_listener_keeps_working():
    from zz.enums import Keyword
    _, engine, owner, _ = setup_game()
    source = add(engine, owner, CARD_REGISTRY["red_00_01_01r_00"], AreaType.BASE)
    owner.flags.add("turn:pc01r_next_red_summon_rush")
    blue = add(engine, owner, Card("blue", "blue", "blue", CardType.F_MINION, printed_color=Color.BLUE))
    red = add(engine, owner, Card("red", "red", "red", CardType.F_MINION, printed_color=Color.RED))
    engine.triggers.emit(EffectTiming.ON_SUMMON, Context(controller=owner, source=blue))
    assert not engine.triggers.has_pending(instance=source)
    engine.triggers.emit(EffectTiming.ON_SUMMON, Context(controller=owner, source=red))
    engine.triggers.resolve_all()
    assert engine.has_keyword(red, Keyword.RUSH)
    assert "turn:pc01r_next_red_summon_rush" not in owner.flags


def test_previous_set_other_minion_attack_listeners_keep_working():
    _, engine, owner, opponent = setup_game()
    ashbringer = add(engine, owner, CARD_REGISTRY["purple_02_02_01_01"])
    attacker = add(engine, owner, Card("attacker", "attacker", "attacker", CardType.F_MINION, bp=500))
    before = engine.effective_bp(attacker)
    engine.triggers.emit(EffectTiming.ON_ATTACK, Context(controller=owner, source=attacker, target=opponent.forces[0]))
    engine.triggers.resolve_all()
    assert engine.effective_bp(attacker) == before + 200
    assert sum(ci is ashbringer for ci, _, _ in engine.effect_events) == 1

    other = add(engine, opponent, CARD_REGISTRY["green_03_02_01_00"])
    other.rested = True
    engine.triggers.emit(EffectTiming.ON_ATTACK, Context(controller=owner, source=attacker, target=opponent))
    engine.triggers.resolve_all()
    assert not other.rested


@pytest.mark.parametrize("card_id", ["red_05_01_03_01", "red_05_01_03_02", "red_05_01_03_03"])
def test_flame_ring_attack_targets_the_available_opponent(card_id):
    session, engine, owner, opponent = setup_game()
    source = add(engine, owner, CARD_REGISTRY[card_id])
    target = add(engine, opponent, Card("enemy", "enemy", "enemy", CardType.F_MINION, bp=500))
    ctx = Context(controller=owner, source=source)
    engine._resolve_source_effects(source, EffectTiming.ON_ATTACK, ctx)
    assert session.prompt is not None
    assert session.prompt["requiredTargetCount"] == 1
    option = next(option for option in session.prompt["options"] if option.get("cardIid") == target.iid)
    response = session.choose(session.prompt["id"], option["id"])
    assert response["error"] is None
    assert engine.effective_bp(target) == 300


def test_flame_ring_requires_two_targets_when_two_or_more_exist():
    session, engine, owner, opponent = setup_game()
    source = add(engine, owner, CARD_REGISTRY["red_05_01_03_02"])
    targets = [add(engine, opponent, Card(f"enemy-{i}", "enemy", "enemy", CardType.F_MINION, bp=500)) for i in range(3)]
    engine._resolve_source_effects(source, EffectTiming.ON_ATTACK, Context(controller=owner, source=source))
    assert session.prompt["requiredTargetCount"] == 2
    options = [option for option in session.prompt["options"] if option.get("cardIid") in {target.iid for target in targets}]
    rejected = session.choose(session.prompt["id"], options[0]["id"], {"selectedOptionIds": [options[0]["id"]]})
    assert rejected["error"]["code"] == "illegal_choice"
    accepted = session.choose(session.prompt["id"], options[0]["id"], {"selectedOptionIds": [options[0]["id"], options[1]["id"]]})
    assert accepted["error"] is None
    assert sorted(engine.effective_bp(target) for target in targets) == [300, 300, 500]


@pytest.mark.parametrize("chosen", [(0, 1), (0, 4), (1, 3), (3, 4)])
def test_flame_ring_actual_attack_can_choose_any_two_of_five(chosen):
    session, engine, owner, opponent = setup_game()
    engine.state.turn = 2
    source = add(engine, owner, CARD_REGISTRY["red_05_01_03_02"])
    source.summoning_sickness = False
    targets = [add(engine, opponent, Card(f"enemy-{i}", "enemy", "enemy", CardType.F_MINION, bp=500)) for i in range(5)]
    session._declare_attack(source, engine.legal_attack_targets(source)[0])
    assert session.prompt["requiredTargetCount"] == 2
    options = {option.get("cardIid"): option["id"] for option in session.prompt["options"]}
    assert set(options) == {target.iid for target in targets}
    selected = [options[targets[i].iid] for i in chosen]
    response = session.choose(session.prompt["id"], selected[0], {"selectedOptionIds": selected})
    assert response["error"] is None
    assert [engine.effective_bp(target) for target in targets] == [300 if i in chosen else 500 for i in range(5)]


@pytest.mark.parametrize("force_destroyed", [False, True])
def test_flame_ring_targets_respect_sphinx_protection(force_destroyed):
    from zz.web.debug_tools import replace_debug_forces
    session, engine, owner, opponent = setup_game()
    engine.state.turn = 2
    replace_debug_forces(session, "P2", ["force_sei", "force_chi"])
    next(force for force in opponent.forces if force.force.id == "force_sei").destroyed = force_destroyed
    source = add(engine, owner, CARD_REGISTRY["red_05_01_03_02"])
    targets = [add(engine, opponent, Card(f"enemy-{i}", "enemy", "enemy", CardType.F_MINION,
                                         cost={Color.COLORLESS: 5 if i < 3 else 6}, bp=500)) for i in range(5)]
    session._declare_attack(source, engine.legal_attack_targets(source)[0])
    offered = {option.get("cardIid") for option in session.prompt["options"]}
    assert offered == {target.iid for target in (targets if force_destroyed else targets[3:])}


def test_two_target_magic_affects_the_only_available_minion():
    session, engine, owner, opponent = setup_game()
    source = add(engine, owner, CARD_REGISTRY["blue_06_02_03_00"], AreaType.HAND)
    target = add(engine, opponent, Card("enemy", "enemy", "enemy", CardType.F_MINION, bp=500, dp=2))
    engine._resolve_source_effects(source, EffectTiming.ON_CAST_MAGIC, Context(controller=owner, source=source))
    assert session.prompt["requiredTargetCount"] == 1
    option = next(option for option in session.prompt["options"] if option.get("cardIid") == target.iid)
    assert session.choose(session.prompt["id"], option["id"])["error"] is None
    assert engine.effective_bp(target) == 200
    assert engine.effective_dp(target) == 1


@pytest.mark.parametrize("card_id", ["red_07_02_01_00", "yellow_08_02_02r_00"])
def test_older_two_target_effects_resolve_with_one_legal_minion(card_id):
    session, engine, owner, opponent = setup_game()
    source = add(engine, owner, CARD_REGISTRY[card_id])
    if card_id.startswith("red"):
        target = add(engine, opponent, Card("enemy", "enemy", "enemy", CardType.F_MINION, bp=600))
    else:
        target = source
    before = engine.effective_bp(target)
    engine._resolve_source_effects(source, EffectTiming.ON_SUMMON, Context(controller=owner, source=source))
    assert session.prompt["requiredTargetCount"] == 1
    option = next(option for option in session.prompt["options"] if option.get("cardIid") == target.iid)
    assert session.choose(session.prompt["id"], option["id"])["error"] is None
    assert engine.effective_bp(target) == before + (-400 if card_id.startswith("red") else 300)


def test_older_two_target_effect_passes_available_minimum_to_policy():
    _, engine, owner, opponent = setup_game()
    source = add(engine, owner, CARD_REGISTRY["red_07_02_01_00"])
    target = add(engine, opponent, Card("enemy", "enemy", "enemy", CardType.F_MINION, bp=600))
    class StrictPolicy:
        def choose_target(self, _engine, _kind, minimum, maximum, eligible):
            assert minimum <= len(eligible)
            return eligible[:maximum]
    engine.set_policies(StrictPolicy(), StrictPolicy())
    engine.defer_source_effect_choice = None
    engine._resolve_source_effects(source, EffectTiming.ON_SUMMON, Context(controller=owner, source=source))
    assert engine.effective_bp(target) == 200


def test_older_two_target_move_returns_the_only_legal_minion_to_base():
    session, engine, owner, opponent = setup_game()
    source = add(engine, owner, CARD_REGISTRY["blue_07_02_01_00"])
    target = add(engine, opponent, Card("enemy", "enemy", "enemy", CardType.F_MINION, bp=500))
    engine._resolve_source_effects(source, EffectTiming.ON_SUMMON, Context(controller=owner, source=source))
    option = next(option for option in session.prompt["options"] if option.get("cardIid") == target.iid)
    assert session.choose(session.prompt["id"], option["id"])["error"] is None
    assert target in opponent.base and target.rested


def test_older_two_mana_refresh_with_one_eligible_mana():
    session, engine, owner, _ = setup_game()
    source = add(engine, owner, CARD_REGISTRY["green_07_02_01r_00"], AreaType.BASE)
    source.rested = True
    engine._resolve_source_effects(source, EffectTiming.MOVE_TO_BASE, Context(controller=owner, source=source))
    option = next(option for option in session.prompt["options"] if option.get("cardIid") == source.iid)
    assert session.choose(session.prompt["id"], option["id"])["error"] is None
    assert not source.rested


def test_mana_target_count_uses_current_mana_color():
    session, engine, owner, _ = setup_game()
    source = add(engine, owner, CARD_REGISTRY["green_07_02_01r_00"], AreaType.BASE)
    source.mana_color_override = Color.BLUE
    mana = add(engine, owner, Card("mana", "mana", "mana", CardType.B_MINION, mana_color=Color.GREEN), AreaType.BASE)
    mana.rested = True
    engine._resolve_source_effects(source, EffectTiming.MOVE_TO_BASE, Context(controller=owner, source=source))
    options = [option for option in session.prompt["options"] if option.get("cardIid")]
    assert [option["cardIid"] for option in options] == [mana.iid]
    assert session.prompt["requiredTargetCount"] == 1
    assert session.choose(session.prompt["id"], options[0]["id"])["error"] is None
    assert not mana.rested


@pytest.mark.parametrize("replace_source", [False, True])
@pytest.mark.parametrize("initial_field", [4, 5])
def test_piledriver_summons_and_announces_effect_before_token_replacement(replace_source, initial_field):
    session, engine, owner, _ = setup_game()
    source = add(engine, owner, CARD_REGISTRY["red_04_01_03_00"], AreaType.HAND)
    fillers = [add(engine, owner, Card(f"ally-{i}", "ally", "ally", CardType.F_MINION, bp=500)) for i in range(initial_field)]
    for _ in range(5):
        add(engine, owner, Card("red-mana", "red-mana", "red-mana", CardType.B_MINION, mana_color=Color.RED), AreaType.BASE)
    session._prompt_main_action()
    play = next(option for option in session.prompt["options"] if option.get("kind") == "play_card" and option.get("iid") == source.iid
                and (initial_field == 4 or option.get("replace_field_iid") == fillers[-1].iid))
    result = session.choose(session.prompt["id"], play["id"], {"paymentBaseIids": play["paymentDefaultIids"]})
    assert result["error"] is None
    assert source in owner.field
    prompt = result["prompt"]
    assert prompt["choiceKind"] == "ally_minion"
    assert {option.get("cardIid") for option in prompt["options"]} == {source.iid, *(filler.iid for filler in fillers[:4])}
    events = result["animationEvents"]
    arrival = next(i for i, event in enumerate(events) if event.get("type") == "zone_move" and event.get("card", {}).get("iid") == source.iid)
    effect = next(i for i, event in enumerate(events) if event.get("type") == "effect" and event.get("card", {}).get("iid") == source.iid)
    assert arrival < effect
    chosen = source if replace_source else fillers[0]
    option = next(option for option in prompt["options"] if option.get("cardIid") == chosen.iid)
    result = session.choose(prompt["id"], option["id"])
    assert result["error"] is None
    assert chosen in owner.trash
    assert sum(card.card.id == "s_golem_token" for card in owner.field) == 1
    assert not any(event.get("type") == "effect" and event.get("card", {}).get("iid") == source.iid for event in result["animationEvents"])


def test_griffon_discards_the_available_card_after_incomplete_draw():
    session, engine, owner, _ = setup_game()
    source = add(engine, owner, CARD_REGISTRY["white_07_02_02r_00"])
    hand_card = add(engine, owner, Card("hand", "hand", "hand", CardType.F_MINION), AreaType.HAND)
    engine._resolve_source_effects(source, EffectTiming.ON_SUMMON, Context(controller=owner, source=source))
    assert session.prompt["requiredTargetCount"] == 1
    option = next(option for option in session.prompt["options"] if option.get("cardIid") == hand_card.iid)
    assert session.choose(session.prompt["id"], option["id"])["error"] is None
    assert hand_card in owner.trash


def test_flame_ring_automatic_policy_resolves_one_target_and_none():
    _, engine, owner, opponent = setup_game()
    source = add(engine, owner, CARD_REGISTRY["red_05_01_03_02"])
    target = add(engine, opponent, Card("enemy", "enemy", "enemy", CardType.F_MINION, bp=500))
    class Policy:
        def __init__(self):
            self.minimums = []
        def choose_target(self, _engine, _kind, minimum, maximum, eligible):
            self.minimums.append(minimum)
            return eligible[:maximum]
    policy = Policy()
    engine.set_policies(policy, policy)
    engine.defer_source_effect_choice = None
    ctx = Context(controller=owner, source=source)
    engine._resolve_source_effects(source, EffectTiming.ON_ATTACK, ctx)
    assert policy.minimums == [1] and engine.effective_bp(target) == 300
    opponent.field.clear()
    engine._resolve_source_effects(source, EffectTiming.ON_ATTACK, ctx)
    assert policy.minimums == [1, 0]


def test_flame_ring_red_token_cannot_be_blocked_by_debuffed_minion():
    _, engine, owner, opponent = setup_game()
    source = add(engine, owner, CARD_REGISTRY["red_05_01_03_03"])
    token = add(engine, owner, Card("token", "token", "token", CardType.F_MINION,
                                    cost={Color.RED: 1}, bp=100, is_token=True))
    debuffed = add(engine, opponent, Card("debuffed", "debuffed", "debuffed", CardType.F_MINION, bp=500))
    debuffed.permanent_bp_mod = -200
    normal = add(engine, opponent, Card("normal", "normal", "normal", CardType.F_MINION, bp=50))
    assert debuffed not in engine.legal_blockers(token)
    assert normal in engine.legal_blockers(token)
    owner.field.remove(source)
    assert debuffed in engine.legal_blockers(token)


def test_turn_end_mandatory_token_waits_for_field_replacement_before_next_turn():
    session, engine, owner, opponent = setup_game()
    spider = add(engine, owner, CARD_REGISTRY["red_02_01_03_02"])
    fillers = [add(engine, owner, Card(f"ally-{i}", "ally", "ally", CardType.F_MINION, bp=300)) for i in range(4)]
    add(engine, opponent, Card("draw", "draw", "draw", CardType.F_MINION), AreaType.DECK)
    engine.end_turn()
    assert session.prompt is not None
    assert engine.state.active is owner
    assert engine.state.step is Step.END
    option = next(option for option in session.prompt["options"] if option.get("cardIid") == fillers[0].iid)
    response = session.choose(session.prompt["id"], option["id"])
    assert response["error"] is None
    assert spider in owner.field
    assert any(ci.card.id == "s_golem_token" for ci in owner.field)
    assert engine.state.active is opponent


def test_generated_token_is_animated_before_next_turn_begins():
    _, engine, owner, opponent = setup_game()
    add(engine, owner, CARD_REGISTRY["red_02_01_03_02"])
    add(engine, opponent, Card("draw", "draw", "draw", CardType.F_MINION), AreaType.DECK)
    engine.visual_events.clear()
    engine.end_turn()
    events = engine.visual_events
    token_event = next(i for i, event in enumerate(events)
                       if event.get("type") == "zone_move" and event.get("card").card.id == "s_golem_token")
    turn_event = next(i for i, event in enumerate(events) if event.get("type") == "turn_begin")
    assert token_event < turn_event


def test_session_presents_turn_end_token_before_next_turn_notice():
    session, engine, owner, opponent = setup_game()
    add(engine, owner, CARD_REGISTRY["red_02_01_03_02"])
    add(engine, opponent, Card("draw", "draw", "draw", CardType.F_MINION), AreaType.DECK)
    engine.visual_events.clear()
    session._animation_events.clear()
    session._refresh_visual_snapshot()
    session._prompt_main_action()
    option_id = next(key for key, action in session._options.items() if action.kind == "end_turn")
    response = session.choose(session.prompt["id"], option_id)
    assert response["error"] is None
    events = response["animationEvents"]
    effect = next(i for i, event in enumerate(events) if event.get("type") == "effect" and event.get("card", {}).get("cardId") == "red_02_01_03_02")
    token = next(i for i, event in enumerate(events) if event.get("type") == "zone_move" and event.get("card", {}).get("cardId") == "s_golem_token")
    turn = next(i for i, event in enumerate(events) if event.get("type") == "turn_begin")
    assert effect < token < turn


def test_evolution_event_shows_only_public_cards_and_preserves_old_and_new_faces():
    session, engine, owner, opponent = setup_game()
    beast = add(engine, owner, CARD_REGISTRY["blue_02_01_03_01"])
    summoner = add(engine, owner, CARD_REGISTRY["blue_00_00_03_00"], AreaType.BASE)
    hidden = add(engine, owner, CARD_REGISTRY["blue_00_00_03_00"], AreaType.HAND)
    enemy = add(engine, opponent, CARD_REGISTRY["blue_00_00_03_00"], AreaType.HAND)
    before = session._visual_state_snapshot()
    engine.apply_pc03_evolution(source=beast, context=Context(controller=owner, source=beast),
        upgrades=(("blue_02_01_03_01", "blue_02_01_03_02"), ("blue_00_00_03_00", "blue_00_00_03_01")), family_id="seadra")
    session._record_visual_changes(before)
    event = next(event for event in session._animation_events if event["type"] == "evolution")
    assert {entry["before"]["iid"] for entry in event["cards"]} == {beast.iid, summoner.iid}
    assert {entry["area"] for entry in event["cards"]} == {"field", "base"}
    assert all(entry["before"]["cardId"] != entry["after"]["cardId"] for entry in event["cards"])
    assert hidden.card.id == "blue_00_00_03_01" and enemy.card.id == "blue_00_00_03_00"
    projected = _project_animation_events([event], viewer_side=opponent.side.name, asset_index=session.asset_index)
    assert {entry["before"]["iid"] for entry in projected[0]["cards"]} == {beast.iid, summoner.iid}


def test_medium_golem_token_uses_requested_image(tmp_path):
    from zz.web.assets import AssetIndex
    for name in ("ZENONZARD_CARDLIST/tokens", "audio", "video"):
        (tmp_path / name).mkdir(parents=True)
    expected = tmp_path / "ZENONZARD_CARDLIST/tokens/red_04_00_03.png"
    expected.write_bytes(b"image fixture")
    assert AssetIndex(tmp_path).resolve_asset_id("m_golem_token") == expected
