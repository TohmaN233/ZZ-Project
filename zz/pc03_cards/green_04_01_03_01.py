from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming, build_effect
from zz.enums import AreaType, Color
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "green_04_01_03_01"


def _self_source(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.ability_en = (
        "[When Transformed] Place two Green Mana into your base in the Rest State. "
        "Destroy one of your opponent's rested Minions with a cost of 3 or lower."
    )
    card.effects.extend(
        [
            build_effect(
                "place_colorless_mana", EffectTiming.ON_TRANSFORM,
                condition=_self_source, rested=True, mana_color=Color.GREEN,
                official_effect="緑マナ2つをレスト状態でベースに置く。",
                official_timing="変形時", active_areas=(AreaType.FIELD,),
            ),
            build_effect(
                "place_colorless_mana", EffectTiming.ON_TRANSFORM,
                condition=_self_source, rested=True, mana_color=Color.GREEN,
                official_effect="緑マナ2つをレスト状態でベースに置く。",
                official_timing="変形時", active_areas=(AreaType.FIELD,),
            ),
            build_effect(
                "destroy_targets",
                EffectTiming.ON_TRANSFORM,
                condition=_self_source,
                target_kind="enemy_minion",
                max_cost=3,
                only_rested=True,
                official_effect="相手のレスト状態である、コスト3以下のミニオン1体を破壊する。",
                official_timing="変形時",
                active_areas=(AreaType.FIELD,),
            ),
        ]
    )
    return card
