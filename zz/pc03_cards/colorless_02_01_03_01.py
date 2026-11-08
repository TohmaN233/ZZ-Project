from __future__ import annotations

from typing import Any

from zz.effects import EffectTiming, build_effect
from zz.enums import AreaType
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "colorless_02_01_03_01"
EVOKER_PLACED_THIS_TURN = "turn:placed_mana_race:エヴォーカー"


def _self_summoned(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source and source.area is AreaType.FIELD


def _self_destroyed(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.target is source and source.area is AreaType.TRASH


def _evoker_mana_was_placed(source: CardInstance, _state: Any, _ctx: Context) -> bool:
    return EVOKER_PLACED_THIS_TURN in source.owner.flags


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.effects.extend(
        [
            build_effect(
                "draw_cards",
                EffectTiming.ON_SUMMON,
                condition=lambda source, state, ctx: _self_summoned(source, state, ctx)
                and _evoker_mana_was_placed(source, state, ctx),
                amount=1,
                official_effect="このターンに自分の種族「エヴォーカー」を持つマナが置かれている場合、自分はカードを1枚引く。",
                official_timing="召喚時",
            ),
            build_effect(
                "draw_cards",
                EffectTiming.ON_DESTROY,
                condition=lambda source, state, ctx: _self_destroyed(source, state, ctx)
                and _evoker_mana_was_placed(source, state, ctx),
                amount=1,
                official_effect="このターンに自分の種族「エヴォーカー」を持つマナが置かれている場合、自分はカードを1枚引く。",
                official_timing="破壊時",
            ),
        ]
    )
    return card
