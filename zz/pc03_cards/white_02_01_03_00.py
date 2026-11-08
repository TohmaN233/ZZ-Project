from __future__ import annotations

from typing import Any

from zz.effects import EffectTiming, build_effect
from zz.pc01 import _card_from_row

CARD_ID = "white_02_01_03_00"
ABILITY_JP = "【召喚時】\nフォース1つを１回復する。"
ABILITY_EN = "[When Summoned]\nRestore 1 point to one of your Forces."


def _self_source(source: Any, _state: Any, ctx: Any) -> bool:
    return ctx.source is source


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.ability_jp = ABILITY_JP
    card.ability_en = ABILITY_EN
    card.effects.append(
        build_effect(
            "heal_targets",
            EffectTiming.ON_SUMMON,
            condition=_self_source,
            target_kind="any_force",
            amount=1,
            official_effect="フォース1つを１回復する。",
            official_timing="召喚時",
        )
    )
    return card
