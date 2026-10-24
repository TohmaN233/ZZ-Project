from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming
from zz.enums import AreaType
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "colorless_02_02_02c_00"


def _self_source(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source


def _boost_blessed_field_minions(source: CardInstance, state: Any, _ctx: Context) -> None:
    for target in list(source.owner.field):
        if any(
            blessing in target.blessings and blessing.area is AreaType.BLESSING
            for blessing in target.blessings
        ):
            state.engine.modify_stat(target, bp_delta=200, duration="turn")


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.effects.append(
        EffectSpec(
            timing=EffectTiming.MOVE_TO_BASE,
            fn=_boost_blessed_field_minions,
            condition=_self_source,
            official_effect="このターン中、自分の[加護]が付与されているミニオン全てをBP+200する。",
            official_timing="後退時",
            active_areas=(AreaType.BASE,),
        )
    )
    return card
