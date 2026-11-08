from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming, build_effect
from zz.enums import AreaType, CardType, Color
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "blue_03_01_03_01"


def _self_source(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source


def _own_magic_used(source: CardInstance, _state: Any, ctx: Context) -> bool:
    used = ctx.source
    return (
        source.area is AreaType.FIELD
        and isinstance(used, CardInstance)
        and used.owner is source.owner
        and used.card.type is CardType.MAGIC
    )


def _gain_bp_for_own_magic(source: CardInstance, state: Any, _ctx: Context) -> None:
    engine = state.engine
    if engine is None:
        raise RuntimeError(f"{CARD_ID} Magic trigger requires an Engine")
    engine.modify_stat(source, bp_delta=300, duration="turn")


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.effects.extend(
        [
            build_effect(
                "draw_cards",
                EffectTiming.ON_TRANSFORM,
                condition=_self_source,
                amount=2,
                official_effect="自分はカードを2枚引く。",
                official_timing="変形時",
            ),
            build_effect(
                "place_colorless_mana", EffectTiming.ON_TRANSFORM,
                rested=True, mana_color=Color.BLUE,
                condition=_self_source,
                official_effect="青マナ1つをレスト状態でベースに置く。",
                official_timing="変形時",
                active_areas=(AreaType.FIELD,),
            ),
            EffectSpec(
                EffectTiming.ON_CARD_USED,
                _gain_bp_for_own_magic,
                condition=_own_magic_used,
                official_effect="自分がマジックを使用するたび、このターン中、このミニオンをBP+300する。",
                official_timing="常時",
                active_areas=(AreaType.FIELD,),
            ),
        ]
    )
    return card
