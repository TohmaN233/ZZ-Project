from __future__ import annotations

from typing import Any

from zz.effects import EffectTiming, build_effect
from zz.enums import Color
from zz.pc01 import _card_from_row


CARD_ID = "yellow_05_01_03_00"


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.effects.append(
        build_effect(
            "refresh_targets",
            EffectTiming.ON_DESTROY,
            target_kind="ally_minion",
            min_targets=1,
            max_targets=1,
            color=Color.YELLOW,
            official_effect="自分の黄のミニオン1体をアクティブにする。",
            official_timing="破壊時",
        )
    )
    return card
