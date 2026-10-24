from __future__ import annotations

from typing import Any

from zz.effects import EffectTiming, build_effect
from zz.enums import AreaType
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "yellow_06_02_02c_00"


def _this_minion_is_attacking(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.effects.extend([
        build_effect(
            "return_to_hand",
            EffectTiming.ON_ATTACK,
            condition=_this_minion_is_attacking,
            target_kind="enemy_minion",
            min_targets=1,
            max_targets=1,
            max_dp=0,
            active_areas=(AreaType.FIELD,),
            official_effect="相手のDP0のミニオン1体を手札に戻す。",
            official_timing="アタック時",
        ),
        build_effect(
            "return_to_hand",
            EffectTiming.ON_ATTACK,
            condition=_this_minion_is_attacking,
            target_kind="enemy_minion",
            min_targets=1,
            max_targets=1,
            min_dp=1,
            max_dp=1,
            active_areas=(AreaType.FIELD,),
            official_effect="その後、相手のDP1のミニオン1体を手札に戻す。",
            official_timing="アタック時",
        ),
    ])
    return card
