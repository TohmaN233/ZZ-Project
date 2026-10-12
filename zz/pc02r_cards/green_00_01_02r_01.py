from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming
from zz.enums import AreaType
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "green_00_01_02r_01"


def _this_base_minion_was_placed(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source


def _rest_selected_expensive_minion(source: CardInstance, state: Any, _ctx: Context) -> None:
    engine = state.engine
    eligible = engine._eligible_targets(
        source.owner,
        "enemy_minion",
        filter_fn=lambda target: sum(target.card.cost.values()) >= 5,
        source=source,
    )
    if not eligible:
        return
    targets = engine.select_target(
        source.owner,
        "enemy_minion",
        1,
        1,
        filter_fn=lambda target: sum(target.card.cost.values()) >= 5,
        source=source,
    )
    if len(targets) != 1:
        raise RuntimeError(f"{CARD_ID} placement trigger selected {len(targets)} targets")
    for target in targets:
        engine.rest_target(target)


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.effects = list(card.effects) + [
        EffectSpec(
            timing=EffectTiming.ON_PLACE_BASE,
            fn=_rest_selected_expensive_minion,
            condition=_this_base_minion_was_placed,
            target_kind="enemy_minion",
            min_targets=1,
            max_targets=1,
            params={"min_cost": 5},
            active_areas=(AreaType.BASE,),
            official_effect="相手のコスト5以上のミニオン1体をレストする",
            official_timing="配置時",
        )
    ]
    return card
