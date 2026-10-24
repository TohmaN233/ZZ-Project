from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming
from zz.enums import AreaType, CardType
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "colorless_09_02_02c_01"


def _admin_action_restriction(
    source: CardInstance,
    target: CardInstance,
    action: str,
    state: Any,
) -> bool:
    return (
        source.area is AreaType.FIELD
        and target.area is AreaType.FIELD
        and target is not source
        and target.card.type in (CardType.F_MINION, CardType.B_MINION)
        and action in {"attack", "block", "move"}
        and state.engine.effective_bp(target) <= 1000
    )


def _owner_turn_started(source: CardInstance, state: Any, ctx: Context) -> bool:
    return ctx.controller is source.owner and state.active is source.owner


def _buff_all_minions(source: CardInstance, state: Any, _ctx: Context) -> None:
    for player in state.players:
        for target in list(player.field):
            if target.card.type in (CardType.F_MINION, CardType.B_MINION):
                state.engine.modify_stat(target, bp_delta=100, duration="permanent")


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.action_restriction = _admin_action_restriction
    card.effects = list(card.effects) + [
        EffectSpec(
            timing=EffectTiming.TURN_START,
            fn=_buff_all_minions,
            condition=_owner_turn_started,
            active_areas=(AreaType.FIELD,),
            official_effect="ミニオン全てにBP+100を付与する",
            official_timing="自分のターン開始時",
        )
    ]
    return card
