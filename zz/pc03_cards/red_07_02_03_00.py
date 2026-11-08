from __future__ import annotations

from typing import Any

from zz.effects import EffectTiming, build_effect
from zz.pc01 import _card_from_row

CARD_ID = "red_07_02_03_00"
ABILITY_JP = "【メイン】/【フラッシュ】\n相手のミニオン全てにBP-300を付与する。"
ABILITY_EN = "[Main]/[Flash]\nDeal -300BP to all of your opponent's minions."


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.ability_jp = ABILITY_JP
    card.ability_en = ABILITY_EN
    card.effects.append(
        build_effect(
            "stat_modifier_all",
            EffectTiming.ON_CAST_MAGIC,
            target_kind="enemy_minion",
            bp_delta=-300,
            duration="turn",
            official_effect="相手のミニオン全てにBP-300を付与する。",
            official_timing="メイン/フラッシュ",
        )
    )
    return card
