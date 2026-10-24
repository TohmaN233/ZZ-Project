from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming
from zz.enums import AreaType, Keyword
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "yellow_00_01_02c_00"


def _self_source(source: CardInstance, state: Any, ctx: Context) -> bool:
    return ctx.source is source


def _draw_for_sword(source: CardInstance, state: Any, ctx: Context) -> None:
    if any("ソード" in card.card.race_jp.split("|") for card in source.owner.field):
        state.engine.draw(source.owner, 1)


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    if Keyword.CANNOT_BLOCK not in card.keywords:
        card.keywords.append(Keyword.CANNOT_BLOCK)
    card.effects.append(
        EffectSpec(
            timing=EffectTiming.ON_PLACE_BASE,
            fn=_draw_for_sword,
            condition=_self_source,
            official_effect=(
                "フィールドに自分の種族「ソード」を持つミニオンがいる場合、"
                "自分はカードを1枚引く。"
            ),
            official_timing="配置時",
            active_areas=(AreaType.BASE,),
        )
    )
    return card
