from __future__ import annotations
from collections import deque
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from zz.effects import EffectTiming, EffectSpec, effect_once_per_turn_used
from zz.enums import AreaType, CardType, TriggerTiming

if TYPE_CHECKING:
    from zz.model import CardInstance, Context, GameState
    from zz.engine import Engine


MAX_TRIGGER_DEPTH = 50


class TriggerLoopError(RuntimeError):
    pass


@dataclass
class _Pending:
    timing: TriggerTiming | EffectTiming
    instance: "CardInstance"
    trigger: Any
    context: "Context"
    evaluate_condition_on_resolution: bool = False


class TriggerRegistry:
    """Owns the queue of pending triggers and resolves them."""

    def __init__(self, engine: "Engine"):
        self._engine = engine
        self._queue: deque[_Pending] = deque()
        self._depth = 0

    def discard_pending(self, *, instance: "CardInstance" | None = None, trigger: Any | None = None) -> None:
        self._queue = deque(
            pending for pending in self._queue
            if not (
                (instance is None or pending.instance is instance)
                and (trigger is None or pending.trigger is trigger)
            )
        )

    def has_pending(self, *, instance: "CardInstance" | None = None, trigger: Any | None = None) -> bool:
        return any(
            (instance is None or pending.instance is instance)
            and (trigger is None or pending.trigger is trigger)
            for pending in self._queue
        )

    def enqueue_source_effects(self, ci: "CardInstance", timing: EffectTiming,
                               ctx: "Context", effects: list[Any], *, after_pending: bool = False) -> None:
        """Resume later source clauses in order after an interactive choice."""
        pending = [_Pending(timing, ci, effect, ctx, True) for effect in effects if effect.timing is timing]
        if after_pending:
            self._queue.extend(pending)
        else:
            self._queue.extendleft(reversed(pending))

    def enqueue_magic_source_clauses(self, ci: "CardInstance", ctx: "Context", clauses: list[Any], *,
                                    after_pending: bool = False) -> None:
        pending = []
        for clause in clauses:
            timing = clause.timing if isinstance(clause, EffectSpec) else clause.when
            pending.append(_Pending(timing, ci, clause, ctx, True))
        if after_pending:
            self._queue.extend(pending)
        else:
            self._queue.extendleft(reversed(pending))

    def _effect_active_in_area(self, effect: Any, ci: "CardInstance") -> bool:
        active_areas = getattr(effect, "active_areas", None)
        if active_areas is None:
            return ci.area is AreaType.FIELD
        return ci.area in active_areas

    def _trigger_active_in_area(self, ci: "CardInstance") -> bool:
        return ci.area is AreaType.FIELD

    def emit(self, timing: TriggerTiming | EffectTiming, ctx: "Context", *,
             exclude_instance: "CardInstance" | None = None) -> None:
        if self._engine._terminal_game_over:
            return
        state = self._engine.state
        switch_contexts: dict[int, Any] = {}
        switch_races: set[str] = set()
        summoned = getattr(ctx, "source", None)
        if (
            timing is EffectTiming.ON_SUMMON
            and getattr(summoned, "card", None) is not None
            and summoned.card.type is CardType.F_MINION
            and summoned.area is AreaType.FIELD
            and summoned in summoned.owner.field
        ):
            switch_races = {
                race for race in summoned.card.race_jp.split("|") if race
            }
        # Active player's permanents fire first, then opponent's
        for player in (state.active, state.opponent):
            blessing_cards = [
                blessing
                for host in player.field
                for blessing in host.blessings
            ]
            regions = (
                player.field,
                player.base,
                player.trash,
                player.hand,
                player.deck,
                player.removed,
                blessing_cards,
            )
            for region in regions:
                for ci in region:
                    # Source effects may already have resolved through the
                    # leave-zone/cast path; other listeners still receive it.
                    if ci is exclude_instance:
                        continue
                    for effect in ci.card.effects:
                        params = getattr(effect, "params", {})
                        effect_switch_races = params.get("ex02c_switch_races", ())
                        if effect_switch_races and (
                            not isinstance(effect_switch_races, (list, tuple, set, frozenset))
                            or any(not isinstance(race, str) or not race for race in effect_switch_races)
                        ):
                            raise ValueError(
                                f"invalid ex02c_switch_races on {ci.card.id}: {effect_switch_races!r}"
                            )
                        is_switch = bool(
                            switch_races
                            and ci is not summoned
                            and summoned.owner is ci.owner
                            and ci.area is AreaType.FIELD
                            and effect_switch_races
                            and switch_races.intersection(effect_switch_races)
                        )
                        if effect.timing is not timing and not is_switch:
                            continue
                        effect_context = ctx
                        pending_timing = timing
                        if is_switch:
                            effect_context = switch_contexts.get(ci.iid)
                            if effect_context is None:
                                from zz.model import Context

                                effect_context = Context(
                                    controller=ci.owner,
                                    source=ci,
                                    target=ci,
                                    switch_source=ci,
                                )
                                switch_contexts[ci.iid] = effect_context
                            pending_timing = effect.timing
                        # A card's own destroy effect resolves from the destroyed source.
                        # Field/base destroy listeners must opt in with an explicit condition.
                        if timing is EffectTiming.ON_DESTROY and effect.condition is None:
                            continue
                        if not self._effect_active_in_area(effect, ci):
                            continue
                        if isinstance(effect, EffectSpec) and effect_once_per_turn_used(effect, ci):
                            continue
                        if effect.condition and not effect.condition(ci, state, effect_context):
                            continue
                        self._queue.append(_Pending(pending_timing, ci, effect, effect_context))
                        should_duplicate = getattr(self._engine, "should_duplicate_summon_effect", lambda source: False)
                        if timing is EffectTiming.ON_SUMMON and ci is ctx.source and should_duplicate(ci):
                            self._queue.append(_Pending(timing, ci, effect, ctx))
                    for trig in ci.card.triggers:
                        if trig.when is not timing:
                            continue
                        if not self._trigger_active_in_area(ci):
                            continue
                        if trig.condition and not trig.condition(ci, state, ctx):
                            continue
                        self._queue.append(_Pending(timing, ci, trig, ctx))
                    if ci.area is AreaType.FIELD and ci.blessings:
                        from zz.pc02 import blessing_effects

                        for effect in blessing_effects(ci, timing, ctx):
                            if effect_once_per_turn_used(effect, ci):
                                continue
                            if effect.condition and not effect.condition(ci, state, ctx):
                                continue
                            self._queue.append(_Pending(timing, ci, effect, ctx))

    def resolve_all(self) -> None:
        if self._engine._terminal_game_over:
            return
        while self._queue and not self._engine._terminal_game_over:
            # An interactive source clause has left this queue for the Session.
            # Its frame remains authoritative until that choice/callback finishes.
            if any(
                frame.running_callbacks or frame.pending_clauses and (
                    frame.dispatching
                    or frame.continuation_queued and not any(
                        pending.instance is frame.source
                        and pending.trigger is frame.pending_clauses[0]
                        for pending in self._queue
                    )
                )
                for frame in self._engine._magic_cast_frames.values()
            ):
                self._depth = 0
                return
            self._depth += 1
            if self._depth > MAX_TRIGGER_DEPTH:
                raise TriggerLoopError(
                    f"trigger depth exceeded {MAX_TRIGGER_DEPTH}"
                )
            p = self._queue.popleft()
            if (p.evaluate_condition_on_resolution and p.trigger.condition
                    and not p.trigger.condition(p.instance, self._engine.state, p.context)):
                self._engine.complete_magic_source_effect(p.instance, p.trigger, p.context)
                continue
            if isinstance(p.trigger, EffectSpec) and effect_once_per_turn_used(p.trigger, p.instance):
                self._engine.complete_magic_source_effect(p.instance, p.trigger, p.context)
                continue
            defer_choice = getattr(self._engine, "defer_trigger_choice", None)
            if defer_choice is not None:
                choice_result = defer_choice(p)
                if choice_result is None:
                    self._queue.appendleft(p)
                    self._depth = 0
                    return
                if choice_result:
                    self._depth = 0
                    return
            run_callback = getattr(self._engine, "_run_effect_callback", None)
            if run_callback is None:
                record_effect = getattr(self._engine, "_record_effect_event", None)
                if record_effect is not None:
                    record_effect(p.instance, p.trigger, p.context)
                p.trigger.fn(p.instance, self._engine.state, p.context)
            else:
                record_effect = getattr(self._engine, "_record_effect_event", None)
                if record_effect is not None:
                    record_effect(p.instance, p.trigger, p.context)
                if isinstance(p.trigger, EffectSpec):
                    run_pre_target = getattr(self._engine, "_run_pre_target_effect", None)
                    if run_pre_target is not None:
                        run_pre_target(p.trigger, p.instance, p.context)
                    run_callback(p.trigger.fn, p.instance, self._engine.state, p.context, effect=p.trigger)
                else:
                    run_callback(p.trigger.fn, p.instance, self._engine.state, p.context, effect=p.trigger)
        self._depth = 0
