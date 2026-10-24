from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming
from zz.enums import AreaType, Color
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "yellow_05_02_02c_00"
_OPPONENT_MINION_RETURNED_THIS_TURN = "turn:ex02c_opponent_minion_returned_to_hand"


def _own_turn_start(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.controller is source.owner


def _heal_or_boost_by_life(source: CardInstance, state: Any, _ctx: Context) -> None:
    if source.owner.life <= 3:
        state.engine.heal(source.owner, 1)
    elif source.owner.life >= 4:
        state.engine.modify_stat(source, bp_delta=300, duration="turn")


def _zero_free_cost_after_opponent_minion_returned(
    source: CardInstance,
    target: CardInstance,
    _state: Any,
) -> int:
    if (
        source is target
        and target.area is AreaType.HAND
        and _OPPONENT_MINION_RETURNED_THIS_TURN in target.owner.flags
    ):
        return -target.card.cost.get(Color.COLORLESS, 0)
    return 0


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.cost_aura = _zero_free_cost_after_opponent_minion_returned
    card.effects.append(
        EffectSpec(
            timing=EffectTiming.TURN_START,
            fn=_heal_or_boost_by_life,
            condition=_own_turn_start,
            params={"ex02c_switch_races": ["絶剣"]},
            active_areas=(AreaType.FIELD,),
            official_effect=(
                "自分のプレイヤーのライフが3以下である場合、自分のプレイヤーを1回復する。"
                "自分のプレイヤーのライフが4以上である場合、代わりに、このターン中、"
                "このミニオンをBP+300する。"
            ),
            official_timing="自分のターン開始時＆スイッチ",
        )
    )
    return card
