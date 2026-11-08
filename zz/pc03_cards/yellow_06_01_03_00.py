from __future__ import annotations

from typing import Any

from zz.effects import EffectTiming, build_effect
from zz.pc01 import _card_from_row


CARD_ID = "yellow_06_01_03_00"


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.effects.append(
        build_effect(
            "return_to_hand",
            EffectTiming.ON_SUMMON,
            target_kind="enemy_minion",
            min_cost=7,
            official_effect="相手のコスト7以上のミニオン1体を手札に戻す。",
            official_timing="召喚時",
        )
    )
    return card
