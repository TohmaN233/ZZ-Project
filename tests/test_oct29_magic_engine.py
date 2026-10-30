import random

import pytest

from zz.effects import EffectSpec, EffectTiming
from zz.engine import Engine, GameOver
from zz.enums import AreaType, CardType, Side, Step, TriggerTiming
from zz.model import Action, Card, CardInstance, Context, GameState, Player, Trigger


class FirstTarget:
    def choose_target(self, _engine, _kind, _minimum, maximum, eligible):
        return eligible[:maximum]


def game():
    players = [Player("P1", Side.P1, life=10), Player("P2", Side.P2, life=10)]
    engine = Engine(GameState(players=players, step=Step.MAIN), random.Random(8))
    engine.set_policies(FirstTarget(), FirstTarget())
    return engine, *players


def put(engine, owner, card, area=AreaType.HAND):
    ci = CardInstance(card, owner, iid=engine.state.allocate_iid(), area=area)
    getattr(owner, area.value).append(ci)
    return ci


def magic(effects=(), triggers=()):
    return Card("magic", "magic", "magic", CardType.MAGIC, effects=list(effects),
                triggers=list(triggers), flash_timing_ok=True)


def observe(source, state, ctx):
    assert source.area is AreaType.RESOLVING
    assert source in source.owner.resolving
    assert source not in source.owner.trash
    assert ctx.source is source and ctx.controller is source.owner
    source.owner.flags.add("source-callback")


@pytest.mark.parametrize("flash,side", [(False, 0), (True, 0), (True, 1)])
def test_all_source_clauses_resolve_outside_trash_once(flash, side):
    engine, p1, p2 = game()
    owner = [p1, p2][side]
    calls = []
    previous = put(engine, owner, magic(), AreaType.TRASH)
    def clause(source, state, ctx):
        observe(source, state, ctx)
        assert source.owner.trash == [previous]
        calls.append("effect")
        engine.triggers.resolve_all()  # Reentrant listeners cannot run ahead.
    def legacy(source, state, ctx):
        observe(source, state, ctx)
        calls.append("legacy")
    source = put(engine, owner, magic([
        EffectSpec(EffectTiming.ON_CAST_MAGIC, clause, active_areas=(AreaType.TRASH,)),
        EffectSpec(EffectTiming.ON_CAST_MAGIC, clause, condition=lambda c,s,x: len(calls) == 1),
    ], [Trigger(TriggerTiming.ON_PLAY, legacy)]))
    listener = put(engine, owner, Card("listener", "listener", "listener", CardType.F_MINION,
        bp=100, effects=[EffectSpec(EffectTiming.ON_CARD_USED,
            lambda c,s,x: calls.append("listener"))]), AreaType.FIELD)
    if flash:
        engine.apply_flash_action(owner, Action("play_card", {"iid": source.iid}))
    else:
        engine.play_card(source)
    assert calls == ["effect", "effect", "legacy", "listener"]
    assert owner.trash == [previous, source]
    assert not owner.resolving and not engine._magic_cast_frames
    assert [(event["from"], event["to"], event["cause"]) for event in engine.zone_move_events
            if event["card"] is source] == [
                (AreaType.HAND, AreaType.RESOLVING, "cast_start"),
                (AreaType.RESOLVING, AreaType.TRASH, "cast_complete")]


def test_deferred_source_removed_from_queue_still_holds_cast_and_tail_conditions():
    engine, owner, _ = game()
    calls = []
    effects = [EffectSpec(EffectTiming.ON_CAST_MAGIC,
                         lambda c,s,x,i=i: (observe(c,s,x), calls.append(i)),
                         condition=(lambda c,s,x: len(calls) == 1) if i == 1 else None)
               for i in range(3)]
    source = put(engine, owner, magic(effects))
    held = []
    engine.defer_source_effect_choice = lambda c,e,x: held.append((c,e,x)) or True
    engine.play_card(source)
    engine.triggers.resolve_all()
    assert not calls and source in owner.resolving and source not in owner.trash
    c,e,x = held.pop()
    engine._run_effect_callback(e.fn, c, engine.state, x, effect=e)
    pending = []
    engine.defer_trigger_choice = lambda p: pending.append(p) or True
    engine.triggers.resolve_all()
    assert calls == [0] and pending[0].trigger is effects[1]
    engine.triggers.resolve_all()
    assert calls == [0]  # Queue no longer contains clause 2; clause 3 still waits.
    p = pending.pop()
    engine._run_effect_callback(p.trigger.fn, p.instance, engine.state, p.context, effect=p.trigger)
    engine.defer_trigger_choice = None
    engine.triggers.resolve_all()
    assert calls == [0, 1, 2] and owner.trash == [source]


@pytest.mark.parametrize("skip", [False, True])
def test_manual_split_clause_and_optional_skip_release_tail(skip):
    engine, owner, _ = game()
    calls = []
    first = EffectSpec(EffectTiming.ON_CAST_MAGIC, observe)
    second = EffectSpec(EffectTiming.ON_CAST_MAGIC, lambda c,s,x: (observe(c,s,x), calls.append(2)))
    source = put(engine, owner, magic([first, second]))
    engine.play_card(source, resolve_source_effects=False, resolve_triggers=False)
    ctx = Context(controller=owner, source=source)
    engine.prepare_manual_magic_effect(source, first, ctx)
    engine.triggers.resolve_all()
    assert not calls and source not in owner.trash
    if skip:
        engine.complete_magic_source_effect(source, first, ctx)
    else:
        engine._run_effect_callback(first.fn, source, engine.state, ctx, effect=first)
    engine.triggers.resolve_all()
    assert calls == [2] and owner.trash == [source]
    engine.complete_magic_source_effect(source, first, ctx)
    assert owner.trash == [source]


@pytest.mark.parametrize("flash", [False, True])
def test_no_legal_target_or_no_source_clauses_finishes(flash):
    engine, owner, _ = game()
    from zz.cards import CARD_REGISTRY
    from zz.decks import AGUMA_RED_RECIPE
    from dataclasses import replace
    # Real Fireball damage template must still execute with an empty legal set.
    definition = replace(CARD_REGISTRY["red_02_03_02r_01"], cost={})
    source = put(engine, owner, definition)
    if flash:
        engine.apply_flash_action(owner, Action("play_card", {"iid": source.iid}))
    else:
        engine.play_card(source)
    assert source in owner.trash and not owner.resolving
    empty = put(engine, owner, magic())
    engine.play_card(empty)
    assert empty in owner.trash and not owner.resolving


def test_game_over_cleans_cast_but_programming_exception_stays_visible():
    for exception in [RuntimeError("broken callback"), GameOver(None, "terminal")]:
        engine, owner, _ = game()
        def fail(c,s,x):
            observe(c,s,x)
            raise exception
        source = put(engine, owner, magic([EffectSpec(EffectTiming.ON_CAST_MAGIC, fail)]))
        with pytest.raises(type(exception), match=str(exception)):
            engine.play_card(source)
        if isinstance(exception, GameOver):
            assert owner.trash == [source] and not engine._magic_cast_frames
        else:
            assert owner.resolving == [source] and source not in owner.trash


def test_magic_discard_is_not_a_cast():
    engine, owner, _ = game()
    source = put(engine, owner, magic([EffectSpec(EffectTiming.ON_CAST_MAGIC, observe)]))
    engine.discard_from_hand(owner, source)
    assert owner.trash == [source] and not owner.resolving and not engine._magic_cast_frames
    assert engine.zone_move_events[-1].get("cause") is None




def test_each_pre_target_clause_executes_once_across_manual_resume():
    engine, owner, _ = game()
    calls = []
    first = EffectSpec(EffectTiming.ON_CAST_MAGIC, observe,
                       pre_target_fn=lambda c,s,x: calls.append("pre-1"))
    second = EffectSpec(EffectTiming.ON_CAST_MAGIC, observe,
                        pre_target_fn=lambda c,s,x: calls.append("pre-2"))
    source = put(engine, owner, magic([first, second]))
    engine.play_card(source, resolve_source_effects=False, resolve_triggers=False)
    ctx = Context(controller=owner, source=source)
    engine.prepare_manual_magic_effect(source, first, ctx)
    engine._run_pre_target_effect(first, source, ctx)
    engine._run_pre_target_effect(first, source, ctx)
    engine._run_effect_callback(first.fn, source, engine.state, ctx, effect=first)
    engine.triggers.resolve_all()
    assert calls == ["pre-1", "pre-2"] and owner.trash == [source]


def test_conditional_tail_skips_and_turn_end_activates_only_after_cast_completion():
    engine, owner, _ = game()
    calls = []
    held = []
    effects = [
        EffectSpec(EffectTiming.ON_CAST_MAGIC, lambda c,s,x: c.flags.add("turn-end")),
        EffectSpec(EffectTiming.ON_CAST_MAGIC, lambda c,s,x: calls.append("wrong"),
                   condition=lambda c,s,x: False),
        EffectSpec(EffectTiming.TURN_END, lambda c,s,x: calls.append("turn-end"),
                   condition=lambda c,s,x: "turn-end" in c.flags, active_areas=(AreaType.TRASH,)),
    ]
    source = put(engine, owner, magic(effects))
    engine.defer_source_effect_choice = lambda c,e,x: held.append((c,e,x)) or True
    engine.play_card(source)
    ctx = Context(controller=owner, source=source)
    engine.triggers.emit(EffectTiming.TURN_END, ctx)
    assert not any(p.trigger is effects[2] for p in engine.triggers._queue)
    c,e,x = held.pop()
    engine._run_effect_callback(e.fn,c,engine.state,x,effect=e)
    engine.triggers.resolve_all()
    assert source in owner.trash and "turn-end" in source.flags and not calls
    engine.triggers.emit(EffectTiming.TURN_END, ctx)
    engine.triggers.resolve_all()
    assert calls == ["turn-end"]


def test_cast_frame_hash_is_deterministic_and_covers_pre_target_progress():
    import hashlib
    import json
    from zz.multiplayer.hashing import _runtime_value
    hashes = []
    for _ in range(2):
        engine, owner, _ = game()
        first = EffectSpec(EffectTiming.ON_CAST_MAGIC, observe,
                           pre_target_fn=lambda c,s,x: c.flags.add("looked"))
        source = put(engine, owner, magic([first]))
        engine.play_card(source, resolve_source_effects=False, resolve_triggers=False)
        ctx = Context(controller=owner, source=source)
        engine.prepare_manual_magic_effect(source, first, ctx)
        def digest():
            encoded = json.dumps(_runtime_value(engine._magic_cast_frames), sort_keys=True).encode()
            return hashlib.sha256(encoded).hexdigest()
        before = digest()
        engine._run_pre_target_effect(first, source, ctx)
        after = digest()
        assert before != after
        hashes.append((before, after))
    assert hashes[0] == hashes[1]


@pytest.mark.parametrize("flash", [False, True])
@pytest.mark.parametrize("deferred", [False, True])
def test_listener_conditions_observe_finished_source_for_sync_and_deferred_casts(flash, deferred):
    engine, owner, _ = game()
    calls, collected, held = [], [], []
    def source_clause(c,s,x):
        observe(c,s,x)
        c.owner.flags.add("source-finished")
    source_effect = EffectSpec(EffectTiming.ON_CAST_MAGIC, source_clause)
    source = put(engine, owner, magic([source_effect]))
    def condition(label):
        def check(c,s,x):
            collected.append((label, "source-finished" in owner.flags, x.source.area))
            return "source-finished" in owner.flags
        return check
    observer = Card("observer", "observer", "observer", CardType.F_MINION, bp=100,
        effects=[
            EffectSpec(EffectTiming.ON_CAST_MAGIC, lambda c,s,x: calls.append("cast"), condition=condition("cast")),
            EffectSpec(EffectTiming.ON_CARD_USED, lambda c,s,x: calls.append("used"), condition=condition("used")),
        ], triggers=[Trigger(TriggerTiming.ON_PLAY, lambda c,s,x: calls.append("play"), condition=condition("play"))])
    put(engine, owner, observer, AreaType.FIELD)
    if deferred:
        engine.defer_source_effect_choice = lambda c,e,x: held.append((c,e,x)) or True
    if flash:
        engine.apply_flash_action(owner, Action("play_card", {"iid": source.iid}))
    else:
        engine.play_card(source)
    if deferred:
        assert not collected and not calls
        c,e,x = held.pop()
        engine._run_effect_callback(e.fn,c,engine.state,x,effect=e)
        engine.triggers.resolve_all()
    assert collected == [(label, True, AreaType.RESOLVING) for label in ("cast", "play", "used")]
    assert calls == ["cast", "play", "used"]
    assert owner.trash == [source]


@pytest.mark.parametrize("mode", ["manual", "skip", "empty"])
def test_listener_events_collected_once_for_manual_skip_and_empty_cast(mode):
    engine, owner, _ = game()
    calls, collected = [], []
    def check(c,s,x):
        collected.append(x.source.iid)
        return "ready" in owner.flags
    put(engine, owner, Card("observer", "observer", "observer", CardType.F_MINION, bp=100,
        effects=[EffectSpec(EffectTiming.ON_CARD_USED, lambda c,s,x: calls.append(x.source.iid), condition=check)]), AreaType.FIELD)
    effect = EffectSpec(EffectTiming.ON_CAST_MAGIC, lambda c,s,x: owner.flags.add("ready"))
    source = put(engine, owner, magic([] if mode == "empty" else [effect]))
    if mode == "empty":
        owner.flags.add("ready")
        engine.play_card(source)
    else:
        engine.play_card(source, resolve_source_effects=False, resolve_triggers=False)
        ctx = Context(controller=owner, source=source)
        engine.prepare_manual_magic_effect(source,effect,ctx)
        assert not collected
        if mode == "skip":
            owner.flags.add("ready")
            engine.complete_magic_source_effect(source,effect,ctx)
        else:
            engine._run_effect_callback(effect.fn,source,engine.state,ctx,effect=effect)
        engine.triggers.resolve_all()
    engine.complete_magic_source_effect(source,effect)
    engine.triggers.resolve_all()
    assert collected == calls == [source.iid]
    assert owner.trash == [source]


def test_game_over_never_flushes_rest_or_cast_listeners_during_unwind():
    engine, owner, _ = game()
    calls, collected = [], []
    def check(c,s,x):
        collected.append("collected")
        return True
    observer = put(engine, owner, Card("observer", "observer", "observer", CardType.F_MINION, bp=100,
        effects=[EffectSpec(EffectTiming.ON_REST, lambda c,s,x: calls.append("rest")),
                 EffectSpec(EffectTiming.ON_CARD_USED, lambda c,s,x: calls.append("used"), condition=check)]), AreaType.FIELD)
    def terminal(c,s,x):
        engine.rest_target(observer)
        raise GameOver(None, "terminal")
    source = put(engine, owner, magic([
        EffectSpec(EffectTiming.ON_CAST_MAGIC, terminal),
        EffectSpec(EffectTiming.ON_CAST_MAGIC, lambda c,s,x: calls.append("tail")),
    ]))
    with pytest.raises(GameOver, match="terminal"):
        engine.play_card(source)
    engine.triggers.resolve_all()
    assert not calls and not collected
    assert observer.rested and owner.trash == [source] and not owner.resolving
    engine.finish_magic_casts_on_game_over()
    engine.finish_magic_casts_on_game_over()
    engine._flush_pending_rest_events()
    engine.triggers.emit(EffectTiming.ON_CARD_USED, Context(controller=owner, source=source))
    engine.triggers.resolve_all()
    assert not calls and not collected and owner.trash == [source]
    assert sum(event.get("cause") == "cast_complete" for event in engine.zone_move_events) == 1


def test_nested_cast_from_listener_collects_completed_sources_once_in_order():
    engine, owner, _ = game()
    calls = []
    def mark(label):
        def callback(c,s,x):
            observe(c,s,x)
            owner.flags.add(label)
        return callback
    child = put(engine, owner, magic([EffectSpec(EffectTiming.ON_CAST_MAGIC, mark("child-ready"))]))
    parent = put(engine, owner, magic([EffectSpec(EffectTiming.ON_CAST_MAGIC, mark("parent-ready"))]))
    def cast_condition(c,s,x):
        assert x.source.area is AreaType.RESOLVING
        return ("parent-ready" if x.source is parent else "child-ready") in owner.flags
    def cast_observer(c,s,x):
        assert x.source in owner.trash
        calls.append(x.source.iid)
    put(engine, owner, Card("observer", "observer", "observer", CardType.F_MINION, bp=100,
        effects=[EffectSpec(EffectTiming.ON_CAST_MAGIC, cast_observer, condition=cast_condition),
                 EffectSpec(EffectTiming.ON_CARD_USED, lambda c,s,x: engine.play_card(child),
                            condition=lambda c,s,x: x.source is parent)]), AreaType.FIELD)
    engine.play_card(parent)
    assert calls == [parent.iid, child.iid]
    assert owner.trash == [parent, child] and not engine._magic_cast_frames


def test_programming_exception_keeps_pending_rest_diagnostics_without_flushing():
    engine, owner, _ = game()
    collected = []
    observer = put(engine, owner, Card("observer", "observer", "observer", CardType.F_MINION, bp=100,
        effects=[EffectSpec(EffectTiming.ON_REST, lambda c,s,x: collected.append("ran"),
                            condition=lambda c,s,x: collected.append("collected") or True)]), AreaType.FIELD)
    def fail(c,s,x):
        engine.rest_target(observer)
        raise RuntimeError("broken callback")
    source = put(engine, owner, magic([EffectSpec(EffectTiming.ON_CAST_MAGIC, fail)]))
    with pytest.raises(RuntimeError, match="broken callback"):
        engine.play_card(source)
    assert not collected and engine._pending_rest_minions == [observer]
    assert owner.resolving == [source] and not engine._terminal_game_over


@pytest.mark.parametrize("is_magic", [True, False])
def test_source_waits_for_nested_prompt_without_executing_unoffered_clause(is_magic):
    engine, owner, _ = game()
    calls, busy = [], [False]
    timing = EffectTiming.ON_CAST_MAGIC if is_magic else EffectTiming.ON_DESTROY
    def first(c,s,x):
        calls.append(1)
        busy[0] = True  # A nested source now owns the interactive prompt.
    def later(c,s,x):
        calls.append(2)
        if is_magic:
            observe(c,s,x)
    effects = [EffectSpec(timing,first), EffectSpec(timing,later),
               EffectSpec(timing,lambda c,s,x: calls.append(3))]
    definition = magic(effects) if is_magic else Card("minion", "minion", "minion", CardType.F_MINION, bp=100, effects=effects)
    source = put(engine,owner,definition,AreaType.HAND if is_magic else AreaType.FIELD)
    engine.defer_source_effect_choice = lambda c,e,x: None if busy[0] else False
    engine.defer_trigger_choice = lambda pending: None if busy[0] else False
    if is_magic:
        engine.play_card(source)
    else:
        engine.destroy_target(source,None)
    assert calls == [1]
    assert engine.triggers.has_pending(instance=source,trigger=effects[1])
    if is_magic:
        assert owner.resolving == [source] and source not in owner.trash
    engine.triggers.resolve_all()
    assert calls == [1]
    busy[0] = False
    engine.triggers.resolve_all()
    assert calls == [1,2,3]
    assert owner.trash == [source] and not owner.resolving


def test_nested_source_continuation_finishes_before_parent_magic_later_clauses():
    engine, owner, _ = game()
    calls, held, busy = [], [], [False]
    child_effects = [EffectSpec(EffectTiming.ON_DESTROY,lambda c,s,x: calls.append("child-first")),
                     EffectSpec(EffectTiming.ON_DESTROY,lambda c,s,x: calls.append("child-tail"))]
    child = put(engine,owner,Card("child", "child", "child", CardType.F_MINION, bp=100, effects=child_effects),AreaType.FIELD)
    def first(c,s,x):
        calls.append("parent-first")
        engine._resolve_source_effects(child,EffectTiming.ON_DESTROY,Context(controller=owner,source=child))
    parent = put(engine,owner,magic([
        EffectSpec(EffectTiming.ON_CAST_MAGIC,first),
        EffectSpec(EffectTiming.ON_CAST_MAGIC,lambda c,s,x: calls.append("parent-tail")),
    ]))
    def defer(c,e,x):
        if c is child and e is child_effects[0]:
            held.append((c,e,x))
            busy[0] = True
            return True
        return None if busy[0] else False
    engine.defer_source_effect_choice = defer
    engine.defer_trigger_choice = lambda pending: None if busy[0] else False
    engine.play_card(parent)
    assert calls == ["parent-first"] and parent in owner.resolving
    c,e,x = held.pop()
    busy[0] = False
    engine._run_effect_callback(e.fn,c,engine.state,x,effect=e)
    engine.triggers.resolve_all()
    assert calls == ["parent-first", "child-first", "child-tail", "parent-tail"]
    assert parent in owner.trash and not owner.resolving
