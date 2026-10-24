from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming
from zz.enums import AreaType, CardType
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "colorless_07_02_02c_01"


def _self_summoned(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source


def _destroy_all_low_bp_minions(source: CardInstance, state: Any, _ctx: Context) -> None:
    engine = state.engine

    def eligible(target: CardInstance) -> bool:
        return (
            target.card.type in (CardType.F_MINION, CardType.B_MINION)
            and engine.effective_bp(target) <= 300
            and not engine.is_protected_from_card_effect(
                target,
                source=source,
                operation="destroy",
            )
        )

    targets = engine._eligible_targets(
        source.owner,
        "any_minion",
        filter_fn=eligible,
        source=source,
    )
    for target in list(targets):
        engine.destroy_target(target, source)


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.effects = list(card.effects) + [
        EffectSpec(
            timing=EffectTiming.ON_SUMMON,
            fn=_destroy_all_low_bp_minions,
            condition=_self_summoned,
            params={"max_bp": 300},
            active_areas=(AreaType.FIELD,),
            official_effect="BP300以下のミニオン全てを破壊する",
            official_timing="召喚時",
        )
    ]
    return card
