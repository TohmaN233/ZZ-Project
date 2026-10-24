from __future__ import annotations

from typing import Any

from zz.effects import EffectTiming, build_effect
from zz.enums import AreaType, CardType
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = 'colorless_05_02_02c_01'


def _opponent_minion_destroyed_on_our_turn(
    source: CardInstance,
    state: Any,
    ctx: Context,
) -> bool:
    destroyed = ctx.target
    return (
        state.active is source.owner
        and isinstance(destroyed, CardInstance)
        and destroyed.owner is not source.owner
        and destroyed.card.type in (CardType.F_MINION, CardType.B_MINION)
    )


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.effects.append(
        build_effect(
            "draw_cards",
            EffectTiming.ON_DESTROY,
            condition=_opponent_minion_destroyed_on_our_turn,
            amount=1,
            active_areas=(AreaType.FIELD,),
            official_effect="相手のミニオンが破壊されるたび、自分はカードを1枚引く。",
            official_timing="自分のターン",
        )
    )
    return card
