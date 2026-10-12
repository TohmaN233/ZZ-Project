from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming
from zz.enums import AreaType, CardType, Color
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "green_02_02_02r_00"


def _neutral_field_minion_hand_cost_aura(
    source: CardInstance,
    target: CardInstance,
    _state: Any,
) -> int:
    if source.area is not AreaType.FIELD:
        return 0
    if target.area is not AreaType.HAND or target.card.type is not CardType.F_MINION:
        return 0
    return int(target.card.printed_color is Color.COLORLESS)


def _rest_enemy_force_when_destroyed(source: CardInstance, state: Any, _ctx: Context) -> None:
    engine = state.engine
    targets = engine.select_target(source.owner, "enemy_force", 1, 1, source=source)
    for force in targets:
        force.rested = True


def _this_minion_was_destroyed(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.target is source


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.cost_aura = _neutral_field_minion_hand_cost_aura
    card.effects = list(card.effects) + [
        EffectSpec(
            timing=EffectTiming.ON_DESTROY,
            fn=_rest_enemy_force_when_destroyed,
            condition=_this_minion_was_destroyed,
            target_kind="enemy_force",
            min_targets=1,
            max_targets=1,
            official_effect="相手のForce1つをレストする",
            official_timing="破壊時",
        )
    ]
    return card
