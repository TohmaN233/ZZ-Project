from __future__ import annotations
from collections import deque
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from zz.effects import EffectTiming, EffectSpec, effect_once_per_turn_used
from zz.enums import AreaType, TriggerTiming

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

    def _effect_active_in_area(self, effect: Any, ci: "CardInstance") -> bool:
        active_areas = getattr(effect, "active_areas", None)
        if active_areas is None:
            return ci.area is AreaType.FIELD
        return ci.area in active_areas

    def _trigger_active_in_area(self, ci: "CardInstance") -> bool:
        return ci.area is AreaType.FIELD

    def emit(self, timing: TriggerTiming | EffectTiming, ctx: "Context") -> None:
        state = self._engine.state
        # Active player's permanents fire first, then opponent's
        for player in (state.active, state.opponent):
            for region in (player.field, player.base):
                for ci in region:
                    for effect in ci.card.effects:
                        if effect.timing is not timing:
                            continue
                        # A card's own destroy effect resolves from the destroyed source.
                        # Field/base destroy listeners must opt in with an explicit condition.
                        if timing is EffectTiming.ON_DESTROY and effect.condition is None:
                            continue
                        if not self._effect_active_in_area(effect, ci):
                            continue
                        if isinstance(effect, EffectSpec) and effect_once_per_turn_used(effect, ci):
                            continue
                        if effect.condition and not effect.condition(ci, state, ctx):
                            continue
                        self._queue.append(_Pending(timing, ci, effect, ctx))
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
        while self._queue:
            self._depth += 1
            if self._depth > MAX_TRIGGER_DEPTH:
                raise TriggerLoopError(
                    f"trigger depth exceeded {MAX_TRIGGER_DEPTH}"
                )
            p = self._queue.popleft()
            if isinstance(p.trigger, EffectSpec) and effect_once_per_turn_used(p.trigger, p.instance):
                continue
            defer_choice = getattr(self._engine, "defer_trigger_choice", None)
            if defer_choice is not None and defer_choice(p):
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
                run_callback(p.trigger.fn, p.instance, self._engine.state, p.context)
        self._depth = 0
