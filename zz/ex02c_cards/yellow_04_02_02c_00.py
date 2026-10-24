from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming
from zz.enums import AreaType
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "yellow_04_02_02c_00"


def _self_source(source: CardInstance, state: Any, ctx: Context) -> bool:
    return ctx.source is source


def _restrain_low_cost_opponents(source: CardInstance, state: Any, ctx: Context) -> None:
    engine = state.engine
    opponent = state.players[1 - state.players.index(source.owner)]
    affected = [
        target
        for target in list(opponent.field)
        if sum(target.card.cost.values()) <= 4
    ]
    for target in affected:
        target.flags.add("turn:pc02_cannot_attack")
        target.flags.add("cannot_move")
    if affected:
        def clear_movement_locks() -> None:
            for target in affected:
                target.flags.discard("cannot_move")

        engine.schedule_turn_end_effect(source.owner, clear_movement_locks)


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.effects.append(
        EffectSpec(
            timing=EffectTiming.ON_SUMMON,
            fn=_restrain_low_cost_opponents,
            condition=_self_source,
            params={"ex02c_switch_races": ["閃光"]},
            official_effect="このターン中、相手のコスト4以下のミニオン全てはアタックと移動ができない。",
            official_timing="召喚時＆スイッチ",
            active_areas=(AreaType.FIELD,),
        )
    )
    return card
