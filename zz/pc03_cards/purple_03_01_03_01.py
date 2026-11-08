from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming
from zz.enums import AreaType
from zz.model import CardInstance, Context, ForceInstance
from zz.pc01 import _card_from_row


CARD_ID = 'purple_03_01_03_01'


def _attacked_force(source: CardInstance, state: Any, ctx: Context) -> bool:
    return (
        source.area is AreaType.FIELD
        and source.owner is ctx.controller
        and state.active is source.owner
        and isinstance(ctx.target, ForceInstance)
    )


def _deal_one_to_attacked_force(source: CardInstance, state: Any, ctx: Context) -> None:
    force = ctx.target
    if not isinstance(force, ForceInstance):
        raise RuntimeError(f"{CARD_ID} force-attack effect resolved without a Force target")
    engine = state.engine
    if engine is None:
        raise RuntimeError(f"{CARD_ID} requires an Engine")
    engine._damage_force(force, 1, source=source)


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.effects.append(
        EffectSpec(
            EffectTiming.ON_ATTACK,
            _deal_one_to_attacked_force,
            condition=_attacked_force,
            official_effect="このミニオンがフォースにアタックした場合、そのフォースに1ダメージを与える。",
            official_timing="自分のターン",
            active_areas=(AreaType.FIELD,),
        )
    )
    return card
