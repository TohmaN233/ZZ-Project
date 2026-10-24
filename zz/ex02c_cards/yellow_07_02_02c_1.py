from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming
from zz.enums import AreaType
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "yellow_07_02_02c_1"


def _this_transformed_minion_triggered(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source


def _return_all_enemies_at_most_300_bp(source: CardInstance, state: Any, _ctx: Context) -> None:
    engine = state.engine
    opponent = state.players[1 - state.players.index(source.owner)]
    for target in list(opponent.field):
        if engine.effective_bp(target) <= 300:
            engine.return_to_hand(target, source=source)


def _add_dp_for_each_opponent_hand_card(source: CardInstance, state: Any, _ctx: Context) -> None:
    opponent = state.players[1 - state.players.index(source.owner)]
    count = len(opponent.hand)
    if count:
        state.engine.modify_stat(source, dp_delta=count, duration="turn")


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.effects.extend([
        EffectSpec(
            timing=EffectTiming.ON_TRANSFORM,
            fn=_return_all_enemies_at_most_300_bp,
            condition=_this_transformed_minion_triggered,
            active_areas=(AreaType.FIELD,),
            official_effect="相手のBP300以下のミニオン全てを手札に戻す。",
            official_timing="変形時",
        ),
        EffectSpec(
            timing=EffectTiming.ON_SUMMON,
            fn=_add_dp_for_each_opponent_hand_card,
            condition=_this_transformed_minion_triggered,
            params={"ex02c_switch_races": ["閃光"]},
            active_areas=(AreaType.FIELD,),
            official_effect="このターン中、相手の手札1枚毎に、このミニオンをDP+1する。",
            official_timing="召喚時＆スイッチ",
        ),
    ])
    return card
