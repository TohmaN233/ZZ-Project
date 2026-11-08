from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming
from zz.enums import AreaType
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "colorless_03_01_03_02"


def _self_source(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source


def _mill_three(source: CardInstance, state: Any, _ctx: Context) -> None:
    engine = state.engine
    if engine is None:
        raise RuntimeError(f"{CARD_ID} mill effect requires an Engine")
    if source.area is not AreaType.FIELD:
        raise RuntimeError(f"{CARD_ID} mill effect resolved outside the Field")
    engine.mill_deck(source.owner, 3, source=source)


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.effects.append(
        EffectSpec(
            EffectTiming.ON_SUMMON,
            _mill_three,
            condition=_self_source,
            official_effect="自分のデッキの上から3枚をトラッシュに置く。",
            official_timing="召喚時",
            active_areas=(AreaType.FIELD,),
        )
    )
    return card
