from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming
from zz.enums import AreaType
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "green_02_02_02c_03"


def _this_minion_is_blocking(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source


def _add_permanent_bp(source: CardInstance, state: Any, _ctx: Context) -> None:
    state.engine.modify_stat(source, bp_delta=100, duration="permanent")


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.effects.append(
        EffectSpec(
            timing=EffectTiming.ON_BLOCK,
            fn=_add_permanent_bp,
            condition=_this_minion_is_blocking,
            active_areas=(AreaType.FIELD,),
            official_effect="このミニオンにBP+100を付与する。",
            official_timing="ブロック時",
        )
    )
    return card
