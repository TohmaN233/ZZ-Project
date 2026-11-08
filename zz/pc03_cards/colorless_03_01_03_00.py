from __future__ import annotations

from typing import Any

from zz.effects import EffectTiming, build_effect
from zz.pc01 import _card_from_row


CARD_ID = "colorless_03_01_03_00"


def _self_source(source, _state: Any, ctx) -> bool:
    return ctx.source is source


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.effects.append(
        build_effect(
            "stat_modifier",
            EffectTiming.ON_SUMMON,
            condition=_self_source,
            target_kind="ally_minion",
            race="アルカナ",
            bp_delta=100,
            dp_delta=1,
            duration="permanent",
            official_effect="自分の種族「アルカナ」を持つミニオン1体にBP+100/DP+1を付与する。",
            official_timing="召喚時",
        )
    )
    return card
