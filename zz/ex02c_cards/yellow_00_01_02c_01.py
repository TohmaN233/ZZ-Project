from __future__ import annotations

from typing import Any

from zz.effects import EffectTiming, build_effect
from zz.enums import AreaType, Keyword
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "yellow_00_01_02c_01"


def _self_source(source: CardInstance, state: Any, ctx: Context) -> bool:
    return ctx.source is source


def _cost_three_or_more(mana: CardInstance, target: CardInstance, state: Any) -> bool:
    return sum(target.card.cost.values()) >= 3


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    if Keyword.KAGO not in card.keywords:
        card.keywords.append(Keyword.KAGO)
    card.bless_condition = _cost_three_or_more
    card.effects.append(
        build_effect(
            "return_to_hand",
            EffectTiming.ON_PLACE_BASE,
            condition=_self_source,
            target_kind="ally_minion",
            min_targets=1,
            max_targets=1,
            optional=True,
            official_effect="自分の種族「ソード」を持つミニオン1体を手札に戻すことができる。",
            official_timing="配置時",
            active_areas=(AreaType.BASE,),
            race="ソード",
        )
    )
    return card
