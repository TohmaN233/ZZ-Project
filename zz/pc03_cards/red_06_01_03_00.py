from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming
from zz.enums import AreaType, CardType
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "red_06_01_03_00"


def _self_summoned(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source and source.area is AreaType.FIELD


def _self_summoned_with_weakened_enemy(source: CardInstance, state: Any, ctx: Context) -> bool:
    if not _self_summoned(source, state, ctx):
        return False
    engine = state.engine
    if engine is None:
        raise RuntimeError(f"{CARD_ID} summon condition requires an Engine")
    opponent = state.players[1 - state.players.index(source.owner)]
    return any(
        target.area is AreaType.FIELD
        and target.owner is opponent
        and target.card.type is CardType.F_MINION
        and engine.effective_bp(target) < target.card.bp
        for target in opponent.field
    )


def _destroy_weakened_enemy(source: CardInstance, state: Any, _ctx: Context) -> None:
    engine = state.engine
    if engine is None:
        raise RuntimeError(f"{CARD_ID} summon effect requires an Engine")
    targets = engine.select_target(
        source.owner,
        "enemy_minion",
        1,
        1,
        filter_fn=lambda target: (
            target.card.type is CardType.F_MINION
            and engine.effective_bp(target) < target.card.bp
        ),
        source=source,
    )
    if len(targets) != 1:
        raise RuntimeError(f"{CARD_ID} expected exactly one weakened enemy Minion, got {len(targets)}")
    engine.destroy_target(targets[0], source)


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.effects.append(
        EffectSpec(
            EffectTiming.ON_SUMMON,
            _destroy_weakened_enemy,
            condition=_self_summoned_with_weakened_enemy,
            target_kind="enemy_minion",
            min_targets=1,
            max_targets=1,
            params={"bp_below_original": True},
            official_effect="本来よりBPが低い相手のミニオン1体を破壊する。",
            official_timing="召喚時",
            active_areas=(AreaType.FIELD,),
        )
    )
    return card
