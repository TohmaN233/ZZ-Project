from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming
from zz.enums import AreaType
from zz.model import Context
from zz.pc01 import _card_from_row


CARD_ID = "red_08_02_02r_00"


def _self_attacks(source, state, ctx: Context) -> bool:
    return ctx.source is source


def _own_turn(source, state, ctx: Context) -> bool:
    return state.active is source.owner


def _reduce_all_opponent_minions(source, state, ctx: Context) -> None:
    opponent = state.players[1 - state.players.index(source.owner)]
    for target in tuple(opponent.field):
        state.engine.modify_stat(target, bp_delta=-100, duration="permanent")


def _return_from_trash(source, state, ctx: Context) -> None:
    if source.area is AreaType.TRASH:
        state.engine.add_to_hand(source.owner, source, from_area=AreaType.TRASH)


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.effects.extend(
        [
            EffectSpec(
                timing=EffectTiming.ON_ATTACK,
                fn=_reduce_all_opponent_minions,
                condition=_self_attacks,
                official_effect="相手のミニオン全てにBP-100を付与する",
                official_timing="アタック時",
            ),
            EffectSpec(
                timing=EffectTiming.ON_DESTROY,
                fn=_return_from_trash,
                condition=_own_turn,
                official_effect="自分のターンである場合、このミニオンを手札に戻す",
                official_timing="破壊時",
                official_condition="自分のターン",
            ),
        ]
    )
    return card
