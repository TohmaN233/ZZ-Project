from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming
from zz.enums import AreaType, CardType
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "green_04_02_02c_00"


def _opponent_minion_attacked(source: CardInstance, _state: Any, ctx: Context) -> bool:
    attacker = ctx.source
    return (
        source.area is AreaType.FIELD
        and isinstance(attacker, CardInstance)
        and attacker.area is AreaType.FIELD
        and attacker.owner is not source.owner
        and attacker.card.type in (CardType.F_MINION, CardType.B_MINION)
    )


def _refresh_this_minion(source: CardInstance, state: Any, _ctx: Context) -> None:
    state.engine.refresh_target(source)


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.ability_jp = "【相手のターン】相手のミニオンがアタックするたび、このミニオンをアクティブにする。"
    card.effects.append(
        EffectSpec(
            timing=EffectTiming.ON_ATTACK,
            fn=_refresh_this_minion,
            condition=_opponent_minion_attacked,
            official_effect="相手のミニオンがアタックするたび、このミニオンをアクティブにする。",
            official_timing="相手のターン",
            active_areas=(AreaType.FIELD,),
        )
    )
    return card
