from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming
from zz.enums import Keyword
from zz.pc01 import _card_from_row


CARD_ID = "blue_02_02_02r_00"


def _this_minion_was_blessed(source, _state, ctx) -> bool:
    return ctx.source is source


def _grant_sneaking(source, state, _ctx) -> None:
    state.engine.add_keyword(source, Keyword.SNEAKING)


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.effects = list(card.effects) + [
        EffectSpec(
            timing=EffectTiming.ON_BLESS,
            fn=_grant_sneaking,
            condition=_this_minion_was_blessed,
            official_effect="潜入を付与",
            official_timing="加護時",
        )
    ]
    return card
