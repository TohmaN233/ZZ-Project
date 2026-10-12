from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming
from zz.enums import AreaType
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "blue_00_01_02r_01"


def _cortney_placed(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source and source.area is AreaType.BASE and len(source.owner.base) >= 4


def _draw_for_four_base_mana(source: CardInstance, state: Any, _ctx: Context) -> None:
    state.engine.draw(source.owner, 1)


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.effects = list(card.effects) + [
        EffectSpec(
            timing=EffectTiming.ON_PLACE_BASE,
            fn=_draw_for_four_base_mana,
            condition=_cortney_placed,
            active_areas=(AreaType.BASE,),
            official_effect="ベースのマナがこのカードを含めて4つ以上なら1枚引く",
            official_timing="配置時",
        )
    ]
    return card
