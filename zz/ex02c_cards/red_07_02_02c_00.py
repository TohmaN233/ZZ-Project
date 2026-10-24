from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming
from zz.enums import AreaType, Color
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "red_07_02_02c_00"


def _self_source(source: CardInstance, state: Any, ctx: Context) -> bool:
    return ctx.source is source


def _starburst_stream(source: CardInstance, state: Any, ctx: Context) -> None:
    engine = state.engine
    opponent = state.players[1 - state.players.index(source.owner)]
    for mana in opponent.base:
        if engine._mana_color_of(mana) is Color.COLORLESS:
            mana.rested = True


def _refresh_on_bless(source: CardInstance, state: Any, ctx: Context) -> None:
    source.rested = False


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.effects.extend([
        EffectSpec(
            timing=EffectTiming.ON_TRANSFORM,
            fn=_starburst_stream,
            condition=_self_source,
            official_effect="『スターバースト・ストリーム』相手の無色のマナ全てをレストする。",
            official_timing="変形時",
            active_areas=(AreaType.FIELD,),
        ),
        EffectSpec(
            timing=EffectTiming.ON_BLESS,
            fn=_refresh_on_bless,
            condition=_self_source,
            official_effect="このミニオンをアクティブにする。",
            official_timing="加護時",
            active_areas=(AreaType.FIELD,),
        ),
    ])
    return card
