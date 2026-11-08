from __future__ import annotations

from typing import Any

from zz.effects import EffectTiming, build_effect
from zz.enums import AreaType
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = 'colorless_07_01_03_00'


def _self_summoned(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.effects.append(
        build_effect(
            "stat_modifier_all",
            EffectTiming.ON_SUMMON,
            condition=_self_summoned,
            target_kind="enemy_minion",
            bp_delta=-200,
            duration="permanent",
            official_effect="相手のミニオン全てにBP-200を付与する。",
            official_timing="召喚時",
            active_areas=(AreaType.FIELD,),
        )
    )
    return card
