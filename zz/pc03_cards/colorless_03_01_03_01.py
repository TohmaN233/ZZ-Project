from __future__ import annotations

from typing import Any

from zz.effects import EffectTiming, build_effect
from zz.enums import CardType, Color
from zz.pc01 import _card_from_row


CARD_ID = "colorless_03_01_03_01"


def _self_source(source, _state: Any, ctx) -> bool:
    return ctx.source is source


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.effects.append(
        build_effect(
            "return_from_trash_to_hand",
            EffectTiming.ON_SUMMON,
            condition=_self_source,
            target_kind="trash_field_minion",
            card_type=CardType.F_MINION,
            race="ドラゴン",
            exclude_color=Color.COLORLESS,
            max_targets=1,
            official_effect="自分のトラッシュにある種族「ドラゴン」を持つ、有色のフィールド・ミニオンカード1枚を手札に戻す。",
            official_timing="召喚時",
        )
    )
    return card
