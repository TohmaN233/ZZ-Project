from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "purple_05_02_02r_00"


def _self_summoned(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source


def _mill_three_then_draw_one(source: CardInstance, state: Any, _ctx: Context) -> None:
    engine = state.engine
    engine.mill_deck(source.owner, 3, source=source)
    engine.draw(source.owner, 1)


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.effects = list(card.effects) + [
        EffectSpec(
            timing=EffectTiming.ON_SUMMON,
            fn=_mill_three_then_draw_one,
            condition=_self_summoned,
            official_effect="自分のデッキの上から3枚を破棄し、その後1枚引く",
            official_timing="召喚時",
        )
    ]
    return card
