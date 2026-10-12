from __future__ import annotations

from typing import Any

from zz.effects import EffectTiming, build_effect
from zz.enums import Keyword
from zz.model import Context
from zz.pc01 import _card_from_row


CARD_ID = "yellow_08_02_02r_00"


def _self_summoned(source, state, ctx: Context) -> bool:
    return ctx.source is source


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    if Keyword.FLYING not in card.keywords:
        card.keywords.append(Keyword.FLYING)
    card.effects.append(
        build_effect(
            "stat_modifier",
            EffectTiming.ON_SUMMON,
            condition=_self_summoned,
            target_kind="ally_minion",
            min_targets=2,
            max_targets=2,
            bp_delta=300,
            duration="turn",
            official_effect="このターン中、自分のミニオン2体をBP+300する",
            official_timing="召喚時",
        )
    )
    return card
