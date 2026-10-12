from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming
from zz.enums import AreaType
from zz.model import CardInstance, Context, ForceInstance
from zz.pc01 import _card_from_row


CARD_ID = "white_04_02_02r_01"


def _own_force_attacked_by_opponent_minion(
    source: CardInstance,
    state: Any,
    ctx: Context,
) -> bool:
    attacker = ctx.source
    target = ctx.target
    return (
        state.active is not source.owner
        and ctx.controller is not source.owner
        and isinstance(attacker, CardInstance)
        and attacker.owner is not source.owner
        and isinstance(target, ForceInstance)
        and target.owner is source.owner
    )


def _enter_active_state(source: CardInstance, state: Any, _ctx: Context) -> None:
    state.engine.refresh_target(source)


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.effects = list(card.effects) + [
        EffectSpec(
            timing=EffectTiming.ON_ATTACK,
            fn=_enter_active_state,
            condition=_own_force_attacked_by_opponent_minion,
            active_areas=(AreaType.FIELD,),
            official_effect="相手のターン中、自分のForceが相手Minionに攻撃されるたび、このMinionをアクティブにする",
            official_timing="相手のターン中の攻撃時",
        )
    ]
    return card
