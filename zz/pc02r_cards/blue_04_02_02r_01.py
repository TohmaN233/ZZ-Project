from __future__ import annotations

from typing import Any

from zz.effects import EffectTiming, build_effect
from zz.enums import AreaType
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "blue_04_02_02r_01"


def _this_minion_retreats(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.effects = list(card.effects) + [
        build_effect(
            "stat_modifier",
            EffectTiming.MOVE_TO_BASE,
            condition=_this_minion_retreats,
            target_kind="enemy_minion",
            bp_delta=-100,
            dp_delta=-1,
            duration="permanent",
            official_effect="相手のミニオン1体にBP-100と本来のDP-1を付与する",
            official_timing="後退時",
            active_areas=(AreaType.BASE,),
        )
    ]
    return card
