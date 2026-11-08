from __future__ import annotations

from typing import Any

from zz.effects import EffectTiming, build_effect
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "green_05_01_03_00"


def _self_source(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.effects.append(
        build_effect(
            "rest_targets",
            EffectTiming.ON_SUMMON,
            condition=_self_source,
            target_kind="enemy_minion",
            official_effect="相手のミニオン1体をレストする。",
            official_timing="召喚時",
        )
    )
    return card
