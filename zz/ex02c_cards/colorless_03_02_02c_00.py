from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming
from zz.enums import AreaType
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = 'colorless_03_02_02c_00'


def _this_minion_was_destroyed(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.target is source


def _prevent_opponent_minions_from_activating(
    source: CardInstance,
    state: Any,
    _ctx: Context,
) -> None:
    opponent = state.players[1 - state.players.index(source.owner)]
    opponent.flags.add(
        f"turn:zz03c_minions_cannot_activate:{state.turn}:{opponent.side.name}"
    )


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.effects.append(
        EffectSpec(
            timing=EffectTiming.ON_DESTROY,
            fn=_prevent_opponent_minions_from_activating,
            condition=_this_minion_was_destroyed,
            active_areas=(AreaType.FIELD,),
            official_effect=(
                "このターン中、相手のプレイヤーに"
                "「自分のミニオン全てはアクティブにならない。」を与える。"
            ),
            official_timing="破壊時",
        )
    )
    return card
