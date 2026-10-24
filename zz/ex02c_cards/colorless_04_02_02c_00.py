from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming
from zz.enums import AreaType, CardType
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = 'colorless_04_02_02c_00'


def _opponent_minion_returned(source: CardInstance, _state: Any, ctx: Context) -> bool:
    returned = ctx.target
    return (
        isinstance(returned, CardInstance)
        and returned.owner is not source.owner
        and returned.card.type in (CardType.F_MINION, CardType.B_MINION)
    )


def _buff_sleeping_knights_team(
    source: CardInstance,
    state: Any,
    _ctx: Context,
) -> None:
    engine = state.engine
    engine.modify_stat(source, bp_delta=200, dp_delta=1, duration="turn")
    for minion in source.owner.field:
        if minion is source:
            continue
        if {"絶剣", "閃光"}.intersection(minion.card.race_jp.split("|")):
            engine.modify_stat(minion, bp_delta=200, dp_delta=1, duration="turn")


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.effects.append(
        EffectSpec(
            timing=EffectTiming.ON_RETURN_TO_HAND,
            fn=_buff_sleeping_knights_team,
            condition=_opponent_minion_returned,
            active_areas=(AreaType.FIELD,),
            official_effect=(
                "相手のミニオンが1体以上手札に戻るたび、このターン中、"
                "このミニオンと自分の種族「絶剣」または「閃光」を持つミニオン全てを"
                "BP+200/DP+1する。"
            ),
            official_timing="常時",
        )
    )
    return card
