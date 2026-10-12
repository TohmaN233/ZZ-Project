from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = 'colorless_09_02_02r_00'


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.effects = list(card.effects) + [
        EffectSpec(
            timing=EffectTiming.ON_SUMMON,
            fn=_destroy_one_enemy_minion_per_destroyed_force,
            condition=_has_destroyed_force_when_summoned,
            target_kind="enemy_minion",
            min_targets=0,
            max_targets=2,
            params={"exact_target_count_from_own_destroyed_forces": True},
            official_effect="自分の破壊されたフォース1つにつき、相手のミニオン1体を破壊する",
            official_timing="召喚時",
            official_condition="自分のフォースが破壊されている場合",
        )
    ]
    return card


def _has_destroyed_force_when_summoned(source: CardInstance, state: Any, ctx: Context) -> bool:
    return ctx.source is source and state.engine.destroyed_forces_count(source.owner) > 0


def _destroy_one_enemy_minion_per_destroyed_force(source: CardInstance, state: Any, _ctx: Context) -> None:
    engine = state.engine
    destroyed_forces = engine.destroyed_forces_count(source.owner)
    eligible = engine._eligible_targets(source.owner, "enemy_minion", source=source)
    target_count = min(destroyed_forces, len(eligible))
    if target_count <= 0:
        return
    targets = engine.select_target(
        source.owner,
        "enemy_minion",
        target_count,
        target_count,
        source=source,
    )
    for target in targets:
        engine.destroy_target(target, source)
