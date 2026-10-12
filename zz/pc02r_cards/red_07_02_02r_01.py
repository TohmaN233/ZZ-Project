from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming
from zz.enums import AreaType, CardType, Keyword
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "red_07_02_02r_01"


def _this_minion_was_transformed(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source


def _this_minion_attacks_opponent_life(source: CardInstance, state: Any, ctx: Context) -> bool:
    opponent = state.players[1 - state.players.index(source.owner)]
    return (
        ctx.source is source
        and state.active is source.owner
        and ctx.target is opponent
    )


def _weaken_all_opponent_minions(source: CardInstance, state: Any, _ctx: Context) -> None:
    opponent = state.players[1 - state.players.index(source.owner)]
    for target in tuple(opponent.field):
        if target.card.type is CardType.F_MINION:
            state.engine.modify_stat(target, bp_delta=-300, duration="turn")


def _draw_after_life_attack(source: CardInstance, state: Any, _ctx: Context) -> None:
    state.engine.draw(source.owner, 1)


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    if Keyword.RUSH not in card.keywords:
        card.keywords = list(card.keywords) + [Keyword.RUSH]
    card.effects = list(card.effects) + [
        EffectSpec(
            timing=EffectTiming.ON_TRANSFORM,
            fn=_weaken_all_opponent_minions,
            condition=_this_minion_was_transformed,
            active_areas=(AreaType.FIELD,),
            official_effect="相手のミニオン全てにこのターンBP-300を与える",
            official_timing="変形時",
        ),
        EffectSpec(
            timing=EffectTiming.ON_ATTACK,
            fn=_draw_after_life_attack,
            condition=_this_minion_attacks_opponent_life,
            active_areas=(AreaType.FIELD,),
            official_effect="相手プレイヤーのLifeを攻撃した時、カードを1枚引く",
            official_timing="アタック時",
            official_condition="相手プレイヤーのLifeを攻撃",
        ),
    ]
    return card
