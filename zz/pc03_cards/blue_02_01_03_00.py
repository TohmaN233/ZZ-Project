from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming, build_effect
from zz.enums import AreaType, CardType
from zz.pc01 import _card_from_row


CARD_ID = "blue_02_01_03_00"


def _self_is_summoned(source: Any, _state: Any, ctx: Any) -> bool:
    return ctx.source is source


def _protect_opponent_hand_field_minion_cost(source: Any, state: Any, _ctx: Any) -> None:
    engine = state.engine
    if engine is None:
        raise RuntimeError("Ray Rider cost protection requires an Engine")
    engine.register_cost_change_immunity(
        source=source,
        target_scope="opponent_hand",
        card_type=CardType.F_MINION,
        prevent_increase=True,
        prevent_decrease=True,
        prevent_zero=True,
    )


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.effects.extend(
        [
            build_effect(
                "draw_cards",
                EffectTiming.ON_SUMMON,
                condition=_self_is_summoned,
                amount=1,
                official_effect="自分はカードを1枚引く",
                official_timing="召喚時",
            ),
            EffectSpec(
                EffectTiming.CONTINUOUS,
                _protect_opponent_hand_field_minion_cost,
                active_areas=(AreaType.FIELD,),
                params={
                    "cost_change_immunity": {
                        "target_scope": "opponent_hand",
                        "card_type": "field_minion",
                        "prevent_increase": True,
                        "prevent_decrease": True,
                        "prevent_zero": True,
                    }
                },
                official_effect="相手の手札にあるフィールド・ミニオンカードのコストは変動しない。（コストは増減せず、0にならない）",
                official_timing="常時",
            ),
        ]
    )
    return card
