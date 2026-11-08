from __future__ import annotations

from typing import Any

from zz.effects import EffectTiming, build_effect
from zz.pc01 import _card_from_row


CARD_ID = "red_01_02_03_00"


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.ability_jp = "【メイン】/【フラッシュ】\n相手のBP300以下のミニオン1体を破壊する。"
    card.ability_en = "[Main]/[Flash]\nDestroy one of your opponent's minions with 300BP or lower."
    card.main_timing_ok = True
    card.flash_timing_ok = True
    card.effects.append(
        build_effect(
            "destroy_targets",
            EffectTiming.ON_CAST_MAGIC,
            target_kind="enemy_minion",
            max_bp=300,
            official_effect="相手のBP300以下のミニオン1体を破壊する。",
            official_timing="メイン/フラッシュ",
        )
    )
    return card
