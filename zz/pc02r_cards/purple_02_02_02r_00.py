from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming
from zz.enums import AreaType, CardType
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "purple_02_02_02r_00"


def _destroyed_source_has_eligible_target(source: CardInstance, state: Any, ctx: Context) -> bool:
    if ctx.target is not source or source.area is not AreaType.TRASH:
        return False
    opponent = state.players[1 - state.players.index(source.owner)]
    max_dp = sum(force.destroyed for force in opponent.forces)
    effect = next(
        effect
        for effect in source.card.effects
        if effect.timing is EffectTiming.ON_DESTROY
        and effect.fn is _destroy_opponent_minion_at_force_threshold
    )
    # Trigger prompts are filtered from EffectSpec.params before the callback runs.
    # Snapshot this event's dynamic threshold so invalid DP targets never appear.
    effect.params["max_dp"] = max_dp
    return any(
        target.card.type in (CardType.F_MINION, CardType.B_MINION)
        and state.engine.effective_dp(target) <= max_dp
        for target in opponent.field
    )


def _destroy_opponent_minion_at_force_threshold(
    source: CardInstance,
    state: Any,
    _ctx: Context,
) -> None:
    engine = state.engine
    opponent = state.players[1 - state.players.index(source.owner)]
    max_dp = sum(force.destroyed for force in opponent.forces)

    def eligible(target: CardInstance) -> bool:
        return (
            target.card.type in (CardType.F_MINION, CardType.B_MINION)
            and engine.effective_dp(target) <= max_dp
        )

    if not any(eligible(target) for target in opponent.field):
        return
    targets = engine.select_target(
        source.owner,
        "enemy_minion",
        1,
        1,
        filter_fn=eligible,
        source=source,
    )
    if len(targets) != 1:
        raise RuntimeError(f"{CARD_ID} expected one eligible opposing minion, got {len(targets)}")
    engine.destroy_target(targets[0], source)


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.effects = list(card.effects) + [
        EffectSpec(
            timing=EffectTiming.ON_DESTROY,
            fn=_destroy_opponent_minion_at_force_threshold,
            condition=_destroyed_source_has_eligible_target,
            target_kind="enemy_minion",
            min_targets=1,
            max_targets=1,
            params={"max_dp": 0},
            active_areas=(AreaType.TRASH,),
            official_effect="相手の破壊されたフォース数以下のDPを持つ相手ミニオン1体を破壊する",
            official_timing="破壊時",
        )
    ]
    return card
