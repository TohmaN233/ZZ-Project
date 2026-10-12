from __future__ import annotations

from typing import Any

from zz.effects import EffectTiming, build_effect
from zz.model import Context
from zz.pc01 import _card_from_row


CARD_ID = "yellow_03_02_02r_00"


def _self_attacks(source, state, ctx: Context) -> bool:
    return ctx.source is source


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.effects.append(
        build_effect(
            "stat_modifier",
            EffectTiming.ON_ATTACK,
            condition=_self_attacks,
            target_kind="other_ally_minion",
            min_targets=1,
            max_targets=1,
            bp_delta=200,
            duration="turn",
            official_effect="このターン中、他の自分のミニオン1体をBP+200する",
            official_timing="アタック時",
        )
    )
    return card
