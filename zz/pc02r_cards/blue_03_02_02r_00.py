from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "blue_03_02_02r_00"
TIDAL_WAVE_ID = "blue_02_03_01_01"


def _this_minion_was_summoned(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source


def _add_tidal_wave_from_outside(source: CardInstance, state: Any, _ctx: Context) -> None:
    if state.engine is None:
        raise RuntimeError(f"{CARD_ID} requires an Engine")
    state.engine.add_card_from_outside_to_hand(source.owner, TIDAL_WAVE_ID)


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.effects = list(card.effects) + [
        EffectSpec(
            timing=EffectTiming.ON_SUMMON,
            fn=_add_tidal_wave_from_outside,
            condition=_this_minion_was_summoned,
            official_effect="ゲーム外からヴァイオレントストリーム1枚を手札に加える",
            official_timing="召喚時",
        )
    ]
    return card
