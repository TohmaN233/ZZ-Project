from __future__ import annotations

from typing import Any

from zz.effects import EffectTiming, build_effect
from zz.pc01 import _card_from_row


CARD_ID = "blue_06_02_03_00"


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.ability_jp = "【メイン】／【フラッシュ】相手のミニオン2体にBP-300と本来の数値にDP-1を付与する。"
    card.ability_en = "[Main] / [Flash] Give two of your opponent's Minions -300BP and -1DP based on their original DP."
    card.main_timing_ok = True
    card.flash_timing_ok = True
    card.effects.append(
        build_effect(
            "stat_modifier",
            EffectTiming.ON_CAST_MAGIC,
            target_kind="enemy_minion",
            min_targets=2,
            max_targets=2,
            bp_delta=-300,
            dp_delta=-1,
            duration="permanent",
            official_effect="相手のミニオン2体にBP-300と本来の数値にDP-1を付与する。",
            official_timing="メイン／フラッシュ",
        )
    )
    return card
