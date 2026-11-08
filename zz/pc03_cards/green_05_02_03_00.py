from __future__ import annotations

from typing import Any

from zz.effects import EffectTiming, build_effect
from zz.enums import Color
from zz.pc01 import _card_from_row


CARD_ID = "green_05_02_03_00"


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.effects.extend(
        [
            build_effect(
                "draw_cards",
                EffectTiming.ON_CAST_MAGIC,
                amount=2,
                official_effect="自分はカードを2枚引く。",
                official_timing="メイン",
            ),
            build_effect(
                "heal_targets",
                EffectTiming.ON_CAST_MAGIC,
                target_kind="owner_player",
                amount=1,
                official_effect="自分のプレイヤーを1回復する。",
                official_timing="メイン",
            ),
            build_effect(
                "place_colorless_mana",
                EffectTiming.ON_CAST_MAGIC,
                rested=True,
                mana_color=Color.GREEN,
                official_effect="緑マナ1つをレスト状態でベースに置く。",
                official_timing="メイン",
            ),
        ]
    )
    return card
