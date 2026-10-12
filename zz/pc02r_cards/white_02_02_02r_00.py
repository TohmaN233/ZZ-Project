from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming
from zz.enums import AreaType
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "white_02_02_02r_00"


def _this_minion_was_blessed(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source


def _restore_and_ready_all_forces(source: CardInstance, state: Any, _ctx: Context) -> None:
    engine = state.engine
    for force in source.owner.forces:
        if force.destroyed:
            continue
        engine.heal_target(force, 1)
        force.rested = False


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.effects = list(card.effects) + [
        EffectSpec(
            timing=EffectTiming.ON_BLESS,
            fn=_restore_and_ready_all_forces,
            condition=_this_minion_was_blessed,
            active_areas=(AreaType.FIELD,),
            official_effect="加護時、自分のForce全てを1回復し、アクティブにする",
            official_timing="加護時",
        )
    ]
    return card
