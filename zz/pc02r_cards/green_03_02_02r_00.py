from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "green_03_02_02r_00"
TONE_DOWN_ID = "green_02_03_01r_00"


def _this_minion_was_summoned(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source


def _add_tone_down_from_outside_game(source: CardInstance, state: Any, _ctx: Context) -> None:
    if state.engine is None:
        raise RuntimeError(f"{CARD_ID} requires an Engine")
    state.engine.add_card_from_outside_to_hand(source.owner, TONE_DOWN_ID)


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.effects = list(card.effects) + [
        EffectSpec(
            timing=EffectTiming.ON_SUMMON,
            fn=_add_tone_down_from_outside_game,
            condition=_this_minion_was_summoned,
            official_effect="ゲーム外からTone Down1枚を手札に加える",
            official_timing="召喚時",
        )
    ]
    return card
