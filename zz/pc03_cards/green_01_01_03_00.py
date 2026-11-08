from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming, build_effect
from zz.enums import AreaType, CardType, Color
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "green_01_01_03_00"


def _self_was_moved_to_base(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source and source.area is AreaType.BASE


def _rest_self_in_base(source: CardInstance, _state: Any, _ctx: Context) -> None:
    source.rested = True


def _has_evoker_green_or_colorless_mana(
    source: CardInstance,
    state: Any,
    _ctx: Context,
) -> bool:
    engine = state.engine
    if engine is None:
        raise RuntimeError(f"{CARD_ID} destruction condition requires an Engine")
    return any(
        mana.card.type in (CardType.B_MINION, CardType.F_MINION)
        and "エヴォーカー" in mana.card.race_jp.split("|")
        and engine._mana_color_of(mana) in (Color.GREEN, Color.COLORLESS)
        for mana in source.owner.base
    )


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.effects.extend(
        [
            build_effect(
                "place_colorless_mana",
                EffectTiming.ON_DESTROY,
                condition=_has_evoker_green_or_colorless_mana,
                mana_color=Color.GREEN,
                rested=True,
                official_effect="自分の種族「エヴォーカー」を持つ、緑または無色のマナがある場合、緑マナ1つをレスト状態でベースに置く。",
                official_timing="破壊時",
                active_areas=(AreaType.FIELD,),
            ),
            EffectSpec(
                EffectTiming.MOVE_TO_BASE,
                _rest_self_in_base,
                condition=_self_was_moved_to_base,
                official_effect="このミニオンはベースに移動するとき、レスト状態で移動する。",
                official_timing="常時",
                active_areas=(AreaType.BASE,),
            ),
        ]
    )
    return card
