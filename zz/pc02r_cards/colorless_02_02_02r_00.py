from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming
from zz.enums import AreaType, CardType
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "colorless_02_02_02r_00"


def _locks_opponent_hand_magic_cost(
    source: CardInstance,
    target: CardInstance,
    _state: Any,
) -> bool:
    return (
        source.area is AreaType.FIELD
        and target.owner is not source.owner
        and target.area is AreaType.HAND
        and target.card.type is CardType.MAGIC
    )


def _this_minion_blocked(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source


def _become_active_after_block(source: CardInstance, _state: Any, _ctx: Context) -> None:
    if source.area is not AreaType.FIELD:
        raise RuntimeError(f"{CARD_ID} ON_BLOCK resolved while this minion was outside the Field")
    source.rested = False


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    # Engine.effective_cost must consult this lock before returning any modified cost.
    card.cost_lock = _locks_opponent_hand_magic_cost
    card.effects = list(card.effects) + [
        EffectSpec(
            timing=EffectTiming.ON_BLOCK,
            fn=_become_active_after_block,
            condition=_this_minion_blocked,
            official_effect="このミニオンをアクティブ状態にする",
            official_timing="ブロック時",
        )
    ]
    return card


