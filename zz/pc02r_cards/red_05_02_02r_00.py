from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming
from zz.enums import AttackTargetKind
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "red_05_02_02r_00"


def _this_minion_was_blocked_on_its_turn(
    source: CardInstance,
    state: Any,
    ctx: Context,
) -> bool:
    return (
        ctx.target is source
        and state.active is source.owner
        and ctx.attack_target is not None
        and ctx.attack_target.kind is AttackTargetKind.PLAYER
    )


def _refresh_after_being_blocked(source: CardInstance, state: Any, _ctx: Context) -> None:
    state.engine.refresh_target(source)


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.effects = list(card.effects) + [
        EffectSpec(
            timing=EffectTiming.ON_BLOCK,
            fn=_refresh_after_being_blocked,
            condition=_this_minion_was_blocked_on_its_turn,
            official_effect="自分のターンに相手Lifeへの攻撃がブロックされた時、このミニオンをアクティブにする",
            official_timing="自分のターン中",
        )
    ]
    return card
