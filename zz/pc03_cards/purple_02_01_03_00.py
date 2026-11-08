from __future__ import annotations

from typing import Any

from zz.enums import AreaType
from zz.model import CardInstance, Context
from zz.effects import EffectTiming, build_effect
from zz.pc01 import _card_from_row


CARD_ID = "purple_02_01_03_00"


def _self_destroyed(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return source.area is AreaType.TRASH and ctx.target is source and ctx.effect_carrier is source


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.effects.append(
        build_effect(
            "draw_cards",
            EffectTiming.ON_DESTROY,
            condition=_self_destroyed,
            amount=1,
            official_effect="自分はカードを1枚引く。",
            official_timing="破壊時",
        )
    )
    return card
