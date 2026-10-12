from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming
from zz.enums import AreaType
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "white_00_01_02r_01"


def _this_base_was_placed(source: CardInstance, state: Any, ctx: Context) -> bool:
    return ctx.source is source and state.active is source.owner


def _reduce_force_damage_through_opponent_turn_end(
    source: CardInstance,
    state: Any,
    _ctx: Context,
) -> None:
    state.engine.prevent_force_damage_until_turn_end(
        source.owner,
        1,
        end_player=state.opponent,
        source=source,
    )


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.effects = list(card.effects) + [
        EffectSpec(
            timing=EffectTiming.ON_PLACE_BASE,
            fn=_reduce_force_damage_through_opponent_turn_end,
            condition=_this_base_was_placed,
            active_areas=(AreaType.BASE,),
            official_effect="次の相手のターン終了時まで自分のForceに与えられるダメージを1軽減する",
            official_timing="配置時",
        )
    ]
    return card
