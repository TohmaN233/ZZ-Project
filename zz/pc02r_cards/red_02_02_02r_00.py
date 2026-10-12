from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming
from zz.enums import AreaType
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "red_02_02_02r_00"


def _this_minion_was_blessed(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source


def _prevent_opponent_life_recovery_and_damage_reduction(
    source: CardInstance,
    state: Any,
    _ctx: Context,
) -> None:
    opponent = state.players[1 - state.players.index(source.owner)]
    state.engine.add_turn_target_restriction(
        opponent,
        life_recovery_allowed=False,
        damage_reduction_allowed=False,
        source=source,
    )


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.effects = list(card.effects) + [
        EffectSpec(
            timing=EffectTiming.ON_BLESS,
            fn=_prevent_opponent_life_recovery_and_damage_reduction,
            condition=_this_minion_was_blessed,
            active_areas=(AreaType.FIELD,),
            official_effect="このターン、相手のLifeは回復できず相手のLifeとForceへのダメージは軽減されない",
            official_timing="加護時",
        )
    ]
    return card
