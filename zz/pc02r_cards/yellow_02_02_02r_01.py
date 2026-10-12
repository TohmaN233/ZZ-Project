from __future__ import annotations

from typing import Any

from zz.effects import EffectTiming, build_effect
from zz.enums import CardType
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "yellow_02_02_02r_01"


def _self_blessed(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.effects = list(card.effects) + [
        build_effect(
            "look_top_to_hand",
            EffectTiming.ON_BLESS,
            condition=_self_blessed,
            target_kind="top3_field_minion",
            min_targets=1,
            max_targets=1,
            top_n=3,
            card_type=CardType.F_MINION,
            official_effect="デッキの上から3枚を見て、Field Minion1枚を公開して手札に加え、残りをランダムにデッキの下に戻す",
            official_timing="加護時",
        )
    ]
    return card
