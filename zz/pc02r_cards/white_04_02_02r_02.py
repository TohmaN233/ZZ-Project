from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming
from zz.pc01 import _card_from_row


CARD_ID = "white_04_02_02r_02"


def _this_minion_dealt_damage(source, _state, ctx) -> bool:
    return ctx.source is source


def _gain_bp(source, _state, _ctx) -> None:
    source.permanent_bp_mod += 200


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.effects = list(card.effects) + [
        EffectSpec(
            timing=timing,
            fn=_gain_bp,
            condition=_this_minion_dealt_damage,
            official_effect="このミニオンがダメージを与えるたびBP+200",
            official_timing="アタック時",
        )
        for timing in (EffectTiming.ON_DAMAGE_PLAYER, EffectTiming.ON_DAMAGE_FORCE)
    ]
    return card
