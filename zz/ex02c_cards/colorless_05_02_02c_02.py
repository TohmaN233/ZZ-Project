from __future__ import annotations

from typing import Any

from zz.effects import EffectTiming, build_effect
from zz.enums import AreaType
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = 'colorless_05_02_02c_02'


def _this_minion_was_blessed(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.effects.append(
        build_effect(
            "draw_cards",
            EffectTiming.ON_BLESS,
            condition=_this_minion_was_blessed,
            amount=1,
            active_areas=(AreaType.FIELD,),
            official_effect="自分はカードを1枚引く。",
            official_timing="加護時",
        )
    )
    return card
