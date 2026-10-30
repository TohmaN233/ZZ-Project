from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "white_05_03_02r_00"


def _this_magic_was_cast(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source


def _draw_three_then_discard_destroyed_force_count(
    source: CardInstance,
    state: Any,
    _ctx: Context,
) -> None:
    engine = state.engine
    engine.draw(source.owner, 3)
    discard_count = min(sum(1 for force in source.owner.forces if force.destroyed), len(source.owner.hand))
    if discard_count == 0:
        return
    targets = engine.select_target(
        source.owner,
        "hand_card",
        discard_count,
        discard_count,
        source=source,
    )
    if len(targets) != discard_count:
        raise RuntimeError(
            f"{CARD_ID} expected {discard_count} discarded cards, got {len(targets)}"
        )
    for target in targets:
        engine.discard_from_hand(source.owner, target)


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.effects = list(card.effects) + [
        EffectSpec(
            timing=EffectTiming.ON_CAST_MAGIC,
            fn=_draw_three_then_discard_destroyed_force_count,
            condition=_this_magic_was_cast,
            target_kind="hand_card",
            min_targets=0,
            max_targets=2,
            params={
                "post_draw_discard_hand": True,
                "draw_amount": 3,
                "discard_count_from_destroyed_forces": True,
            },
            official_effect="抽3枚、その後自分の破壊されたForce数と同じ枚数を手札から破棄する",
            official_timing="メイン",
        )
    ]
    return card
