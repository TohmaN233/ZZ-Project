from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "yellow_06_02_02r_00"


def _self_summoned(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source


def _return_all_enemy_minions_cost_three_or_less(source: CardInstance, state: Any, _ctx: Context) -> None:
    engine = state.engine
    opponent = state.players[1 - state.players.index(source.owner)]
    for target in list(opponent.field):
        if sum(target.card.cost.values()) <= 3:
            engine.return_to_hand(target, source=source)


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.effects = list(card.effects) + [
        EffectSpec(
            timing=EffectTiming.ON_SUMMON,
            fn=_return_all_enemy_minions_cost_three_or_less,
            condition=_self_summoned,
            official_effect="相手のコスト3以下のミニオン全てを手札に戻す",
            official_timing="召喚時",
        )
    ]
    return card
