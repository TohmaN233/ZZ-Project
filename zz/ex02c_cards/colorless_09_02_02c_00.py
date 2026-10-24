from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming
from zz.enums import AreaType
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "colorless_09_02_02c_00"


def _self_summoned(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source


def _draw_per_item_mana(source: CardInstance, state: Any, _ctx: Context) -> None:
    item_mana_count = sum(
        "アイテム" in mana.card.race_jp.split("|")
        for mana in source.owner.base
    )
    state.engine.draw(source.owner, item_mana_count)


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.effects = list(card.effects) + [
        EffectSpec(
            timing=EffectTiming.ON_SUMMON,
            fn=_draw_per_item_mana,
            condition=_self_summoned,
            active_areas=(AreaType.FIELD,),
            official_effect="自分の種族「アイテム」を持つマナ1つ毎に、自分はカードを１枚引く",
            official_timing="召喚時",
        )
    ]
    return card
