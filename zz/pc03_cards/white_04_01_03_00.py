from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming
from zz.enums import AreaType
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row

CARD_ID = "white_04_01_03_00"


def _self_was_attacker_blocked(source: CardInstance, state: Any, ctx: Context) -> bool:
    attacker = ctx.target
    return (
        source.area is AreaType.FIELD
        and state.active is source.owner
        and ctx.controller is not source.owner
        and attacker is source
    )


def _gain_bp_when_blocked(source: CardInstance, state: Any, _ctx: Context) -> None:
    engine = state.engine
    if engine is None:
        raise RuntimeError(f"{CARD_ID} block trigger requires an Engine")
    engine.modify_stat(source, bp_delta=200, duration="permanent")


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.effects.append(
        EffectSpec(
            EffectTiming.ON_BLOCK,
            _gain_bp_when_blocked,
            condition=_self_was_attacker_blocked,
            official_effect="このミニオンがブロックされるたび、このミニオンにBP+200を付与する。",
            official_timing="自分のターン",
            active_areas=(AreaType.FIELD,),
        )
    )
    return card
