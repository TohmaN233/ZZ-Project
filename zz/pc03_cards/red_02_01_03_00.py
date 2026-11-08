from __future__ import annotations

from typing import Any

from zz.effects import EffectTiming, build_effect
from zz.pc01 import _card_from_row


CARD_ID = "red_02_01_03_00"


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.effects.append(
        build_effect(
            "stat_modifier",
            EffectTiming.ON_DESTROY,
            target_kind="enemy_minion",
            bp_delta=-200,
            duration="permanent",
            official_effect="相手のミニオン1体にBP-200を付与する。",
            official_timing="破壊時",
        )
    )
    return card
