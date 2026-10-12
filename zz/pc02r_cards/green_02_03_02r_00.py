from __future__ import annotations

from typing import Any

from zz.effects import EffectTiming, build_effect
from zz.enums import Color
from zz.pc01 import _card_from_row


CARD_ID = "green_02_03_02r_00"


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.effects = list(card.effects) + [
        build_effect(
            "stat_modifier_all",
            EffectTiming.ON_CAST_MAGIC,
            target_kind="ally_minion",
            bp_delta=300,
            color=Color.GREEN,
            duration="turn",
            applies_to_future=True,
            official_effect="このターン中、自分の緑のミニオン全てのBPを+300する",
            official_timing="フラッシュ",
        )
    ]
    return card
