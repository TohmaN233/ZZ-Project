from __future__ import annotations

from typing import Any

from zz.effects import EffectTiming, build_effect
from zz.enums import CardType, Color, Keyword
from zz.pc01 import _card_from_row


CARD_ID = "blue_06_01_03_01"
TRASH_MAGIC = "trash_magic"


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.ability_jp = (
        "［潜入］\n【アタック時】自分のトラッシュにあるコスト5以下の青のマジックカード1枚を手札に戻す。"
    )
    card.ability_en = (
        "[Infiltrate]\n[When Attacking] Return one Blue Magic card with a cost of 5 or lower from your Trash to your hand."
    )
    if Keyword.SNEAKING not in card.keywords:
        card.keywords.append(Keyword.SNEAKING)
    card.effects.append(
        build_effect(
            "return_from_trash_to_hand",
            EffectTiming.ON_ATTACK,
            target_kind=TRASH_MAGIC,
            min_targets=1,
            max_targets=1,
            color=Color.BLUE,
            card_type=CardType.MAGIC,
            max_cost=5,
            official_effect="自分のトラッシュにあるコスト5以下の青のマジックカード1枚を手札に戻す。",
            official_timing="アタック時",
        )
    )
    return card
