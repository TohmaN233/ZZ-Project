from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming
from zz.enums import AreaType, Keyword
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "red_00_01_02r_01"


def _this_base_minion_was_placed(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source


def _prevent_one_weak_enemy_from_blocking(source: CardInstance, state: Any, _ctx: Context) -> None:
    engine = state.engine
    targets = engine.select_target(
        source.owner,
        "enemy_minion",
        1,
        1,
        filter_fn=lambda target: engine.effective_bp(target) <= 400,
        source=source,
    )
    if not targets:
        return
    engine.add_keyword(targets[0], Keyword.CANNOT_BLOCK, duration="turn")


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.effects = list(card.effects) + [
        EffectSpec(
            timing=EffectTiming.ON_PLACE_BASE,
            fn=_prevent_one_weak_enemy_from_blocking,
            condition=_this_base_minion_was_placed,
            target_kind="enemy_minion",
            min_targets=1,
            max_targets=1,
            params={"max_bp": 400},
            active_areas=(AreaType.BASE,),
            official_effect="BP400以下の相手ミニオン1体をこのターンブロックできなくする",
            official_timing="配置時",
        )
    ]
    return card
