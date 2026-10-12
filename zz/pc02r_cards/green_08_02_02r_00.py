from __future__ import annotations

from typing import Any

from zz.effects import EffectTiming, build_effect
from zz.enums import Keyword
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "green_08_02_02r_00"


def _this_minion_was_destroyed(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.target is source


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    if Keyword.PENETRATE not in card.keywords:
        card.keywords = list(card.keywords) + [Keyword.PENETRATE]
    card.effects = list(card.effects) + [
        build_effect(
            "draw_cards",
            EffectTiming.ON_DESTROY,
            condition=_this_minion_was_destroyed,
            amount=3,
            official_effect="カードを3枚引く",
            official_timing="破壊時",
        )
    ]
    return card
