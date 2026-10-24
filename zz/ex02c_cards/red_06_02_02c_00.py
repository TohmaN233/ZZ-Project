from __future__ import annotations

from typing import Any

from zz.effects import EffectTiming, build_effect
from zz.enums import AreaType
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "red_06_02_02c_00"


def _heathcliff_is_protected(
    protector: CardInstance,
    target: CardInstance,
    operation: str,
    state: Any,
) -> bool:
    return (
        protector is target
        and state.active is protector.owner
        and state.engine.effective_bp(target) > 0
        and operation in {"destroy", "battle"}
    )


def _attacked_opponent_player(source: CardInstance, state: Any, ctx: Context) -> bool:
    opponent = state.players[1 - state.players.index(source.owner)]
    return (
        ctx.source is source
        and state.active is source.owner
        and ctx.target is opponent
    )


def _this_minion_was_blocked(source: CardInstance, state: Any, ctx: Context) -> bool:
    return (
        ctx.target is source
        and state.active is source.owner
    )


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.effect_protection = _heathcliff_is_protected
    card.effects = list(card.effects) + [
        build_effect(
            "draw_cards",
            EffectTiming.ON_ATTACK,
            condition=_attacked_opponent_player,
            amount=1,
            active_areas=(AreaType.FIELD,),
            official_effect="このミニオンがプレイヤーにアタックした場合、自分はカードを1枚引く",
            official_timing="自分のターン",
        ),
        build_effect(
            "draw_cards",
            EffectTiming.ON_BLOCK,
            condition=_this_minion_was_blocked,
            amount=1,
            active_areas=(AreaType.FIELD,),
            official_effect="このミニオンがブロックされるたび、自分はカードを1枚引く",
            official_timing="自分のターン",
        ),
    ]
    return card
