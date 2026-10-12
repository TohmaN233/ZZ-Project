from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "red_04_02_02r_00"


def _this_minion_attacks(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source


def _reduce_one_opponent_minion(source: CardInstance, state: Any, _ctx: Context) -> None:
    engine = state.engine
    targets = engine.select_target(source.owner, "enemy_minion", 1, 1, source=source)
    if not targets:
        return
    engine.modify_stat(targets[0], bp_delta=-200, duration="turn")


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.effects = list(card.effects) + [
        EffectSpec(
            timing=EffectTiming.ON_ATTACK,
            fn=_reduce_one_opponent_minion,
            condition=_this_minion_attacks,
            target_kind="enemy_minion",
            min_targets=1,
            max_targets=1,
            official_effect="相手のミニオン1体にこのターンBP-200を与える",
            official_timing="アタック時",
        )
    ]
    return card
