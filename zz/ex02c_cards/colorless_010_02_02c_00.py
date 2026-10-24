from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming, build_effect
from zz.enums import AreaType, CardType
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "colorless_010_02_02c_00"


def _self_summoned(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source


def _reduce_enemy_minions_by_force_life(source: CardInstance, state: Any, _ctx: Context) -> None:
    engine = state.engine
    opponent = state.players[1 - state.players.index(source.owner)]
    reduction = sum(force.life for force in source.owner.forces) * 100
    for target in list(opponent.field):
        if target.card.type in (CardType.F_MINION, CardType.B_MINION):
            engine.modify_stat(target, bp_delta=-reduction, duration="permanent")


def _own_turn_ended(source: CardInstance, state: Any, ctx: Context) -> bool:
    return ctx.controller is source.owner and state.active is source.owner


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.effects = list(card.effects) + [
        EffectSpec(
            timing=EffectTiming.ON_SUMMON,
            fn=_reduce_enemy_minions_by_force_life,
            condition=_self_summoned,
            active_areas=(AreaType.FIELD,),
            official_effect="相手のミニオン全てにBP-Xを付与する。Xは自分のフォースのライフ全ての合計×100とする",
            official_timing="召喚時",
        ),
        build_effect(
            "heal_targets",
            EffectTiming.TURN_END,
            condition=_own_turn_ended,
            target_kind="owner_player",
            amount=1,
            active_areas=(AreaType.FIELD,),
            official_effect="自分のプレイヤーを1回復する",
            official_timing="自分のターン終了時",
        ),
    ]
    return card
