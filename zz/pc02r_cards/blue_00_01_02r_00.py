from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming
from zz.enums import AreaType, CardType
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "blue_00_01_02r_00"


def _own_magic_was_cast(source: CardInstance, _state: Any, ctx: Context) -> bool:
    magic = ctx.source
    return (
        isinstance(magic, CardInstance)
        and magic.owner is source.owner
        and magic.card.type is CardType.MAGIC
    )


def _gain_bp_for_turn(source: CardInstance, state: Any, _ctx: Context) -> None:
    state.engine.modify_stat(source, bp_delta=200, duration="turn")


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.effects = list(card.effects) + [
        EffectSpec(
            timing=EffectTiming.ON_CAST_MAGIC,
            fn=_gain_bp_for_turn,
            condition=_own_magic_was_cast,
            active_areas=(AreaType.BASE,),
            official_effect="自分がマジックを使用するたび、このターン中、このミニオンのBPを+200する",
            official_timing="マジック使用時",
        )
    ]
    return card
