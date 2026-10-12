from __future__ import annotations

from typing import Any

from zz.effects import EffectTiming, build_effect
from zz.pc01 import _card_from_row


CARD_ID = "blue_04_02_02r_00"


def _this_minion_was_summoned(source, _state, ctx) -> bool:
    return ctx.source is source


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.effects = list(card.effects) + [
        build_effect(
            "increase_movement_right",
            EffectTiming.ON_SUMMON,
            condition=_this_minion_was_summoned,
            amount=1,
            official_effect="自分の移動権を1増やす",
            official_timing="召喚時",
        )
    ]
    return card
