from __future__ import annotations

from typing import Any

from zz.effects import EffectTiming, build_effect
from zz.pc01 import _card_from_row


CARD_ID = "yellow_05_02_03_00"


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.effects.append(
        build_effect(
            "stat_modifier_all",
            EffectTiming.ON_CAST_MAGIC,
            target_kind="ally_minion",
            bp_delta=200,
            dp_delta=1,
            duration="turn",
            official_effect="このターン中、自分のミニオン全てにBP+200/DP+1を付与する。",
            official_timing="メイン/フラッシュ",
        )
    )
    return card
