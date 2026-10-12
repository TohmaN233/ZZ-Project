from __future__ import annotations

from typing import Any

from zz.effects import EffectTiming, build_effect
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "blue_01_03_02r_00"


def _is_this_magic(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source


def _this_magic_can_spend_movement(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source and source.owner.movement_right_count > 0


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.effects = list(card.effects) + [
        build_effect(
            "draw_cards",
            EffectTiming.ON_CAST_MAGIC,
            condition=_is_this_magic,
            amount=1,
            official_effect="1枚引く",
            official_timing="メイン",
        ),
        build_effect(
            "place_colorless_mana",
            EffectTiming.ON_CAST_MAGIC,
            condition=_this_magic_can_spend_movement,
            consume_movement_right=True,
            rested=True,
            official_effect="1枚引く。移動権を消費できた場合、レスト状態の無色マナを1つ置く",
            official_timing="メイン",
        )
    ]
    return card
