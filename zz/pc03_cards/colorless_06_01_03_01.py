from __future__ import annotations

from typing import Any

from zz.effects import EffectTiming, build_effect
from zz.pc01 import _card_from_row


CARD_ID = "colorless_06_01_03_01"


def _self_source(source, _state: Any, ctx) -> bool:
    return ctx.source is source


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.effects.append(
        build_effect(
            "destroy_targets",
            EffectTiming.ON_SUMMON,
            condition=_self_source,
            target_kind="enemy_minion",
            race="ドラゴン",
            card_type="f_minion",
            min_targets=1,
            max_targets=1,
            official_effect="相手の種族「ドラゴン」を持つフィールド・ミニオン1体を破壊する。",
            official_timing="召喚時",
        )
    )
    return card
