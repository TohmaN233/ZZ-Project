from __future__ import annotations

from typing import Any

from zz.effects import EffectTiming, build_effect
from zz.enums import AreaType
from zz.pc01 import _card_from_row


CARD_ID = "colorless_02_02_02c_05"


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.effects.append(
        build_effect(
            "draw_cards",
            EffectTiming.ON_DESTROY,
            amount=1,
            scope="both",
            active_areas=(AreaType.TRASH,),
            official_effect="お互いはカードを1枚引く。",
            official_timing="破壊時",
        )
    )
    return card
