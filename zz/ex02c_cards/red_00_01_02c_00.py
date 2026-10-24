from __future__ import annotations

from typing import Any

from zz.effects import EffectTiming, build_effect
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "red_00_01_02c_00"


def _this_base_minion_was_placed(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.effects = list(card.effects) + [
        build_effect(
            "stat_modifier",
            EffectTiming.ON_PLACE_BASE,
            condition=_this_base_minion_was_placed,
            target_kind="enemy_minion",
            min_targets=1,
            max_targets=1,
            bp_delta=-100,
            duration="turn",
            official_effect="このターン中、相手のミニオン1体をBP-100する",
            official_timing="配置時",
        )
    ]
    return card
