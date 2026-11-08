from __future__ import annotations

from typing import Any

from zz.effects import EffectTiming, build_effect
from zz.enums import AreaType, Keyword
from zz.pc01 import _card_from_row

CARD_ID = "white_06_01_03_02"
ABILITY_JP = "貫通\n【アタック時】\n相手は必ずブロックする。"
ABILITY_EN = "Pierce\n[When Attacking]\nYour opponent must block."


def _self_attack(source: Any, _state: Any, ctx: Any) -> bool:
    return ctx.source is source and source.area is AreaType.FIELD


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.ability_jp = ABILITY_JP
    card.ability_en = ABILITY_EN
    if Keyword.PENETRATE not in card.keywords:
        card.keywords.append(Keyword.PENETRATE)
    card.effects.append(
        build_effect(
            "force_block",
            EffectTiming.ON_ATTACK,
            condition=_self_attack,
            official_effect="相手は必ずブロックする。",
            official_timing="アタック時",
            active_areas=(AreaType.FIELD,),
        )
    )
    return card
