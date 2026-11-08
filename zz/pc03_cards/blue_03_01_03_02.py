from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming, build_effect
from zz.enums import AreaType
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "blue_03_01_03_02"


def _came_from_own_base(source: CardInstance, state: Any, ctx: Context) -> bool:
    if ctx.source is not source or source.area is not AreaType.FIELD:
        return False
    engine = state.engine
    if engine is None:
        raise RuntimeError(f"{CARD_ID} Base-to-Field condition requires an Engine")
    movement = next(
        (event for event in reversed(engine.zone_move_events) if event.get("card") is source),
        None,
    )
    return bool(
        movement
        and movement.get("from") is AreaType.BASE
        and movement.get("to") is AreaType.FIELD
    )


def _enter_active(source: CardInstance, state: Any, _ctx: Context) -> None:
    engine = state.engine
    if engine is None:
        raise RuntimeError(f"{CARD_ID} Base-to-Field effect requires an Engine")
    engine.refresh_target(source)


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.effects.extend(
        [
            build_effect(
                "move_to_base_targets",
                EffectTiming.ON_ATTACK,
                target_kind="enemy_minion",
                max_cost=3,
                rested=True,
                official_effect="相手のコスト3以下のミニオン1体を、レスト状態でベースに移動させる。",
                official_timing="アタック時",
            ),
            EffectSpec(
                EffectTiming.ON_MOVE_TO_FIELD,
                _enter_active,
                condition=_came_from_own_base,
                official_effect="このミニオンがベースからフィールドに移動するとき、アクティブ状態で移動する。",
                official_timing="ベース",
                active_areas=(AreaType.FIELD,),
            ),
        ]
    )
    return card
