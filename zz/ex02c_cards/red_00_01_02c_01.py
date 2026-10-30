from __future__ import annotations

from typing import Any

from zz.effects import EffectTiming, build_effect
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "red_00_01_02c_01"


def _this_base_minion_was_placed(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source


def _has_two_sword_minions(source: CardInstance, _state: Any, _ctx: Context) -> bool:
    return sum("ソード" in ci.card.race_jp for ci in source.owner.field) >= 2


def _cost_three_or_more(_mana: CardInstance, target: CardInstance, _state: Any) -> bool:
    return sum(target.card.cost.values()) >= 3


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.bless_condition = _cost_three_or_more
    card.effects = list(card.effects) + [
        build_effect(
            "increase_movement_right",
            EffectTiming.ON_PLACE_BASE,
            condition=lambda source, state, ctx: (
                _this_base_minion_was_placed(source, state, ctx)
                and _has_two_sword_minions(source, state, ctx)
            ),
            amount=1,
            official_effect="自分の移動権を1増やす",
            official_timing="配置時",
        )
    ]
    return card
