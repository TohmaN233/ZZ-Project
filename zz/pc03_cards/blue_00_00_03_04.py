from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming
from zz.enums import AreaType
from zz.pc01 import _card_from_row


CARD_ID = "blue_00_00_03_04"
SUMMON_BEAST_CARD_ID = "blue_05_01_03_01"


def _self_is_placed(source: Any, _state: Any, ctx: Any) -> bool:
    return ctx.source is source


def _add_summon_beast_from_outside(source: Any, state: Any, _ctx: Any) -> None:
    engine = state.engine
    if engine is None:
        raise RuntimeError("PC03 base placement requires an Engine")
    if source.area is not AreaType.BASE:
        raise RuntimeError(f"{CARD_ID} placement effect resolved outside Base: {source.area!r}")
    source.flags.add("cannot_move")
    engine.add_card_from_outside_to_hand(source.owner, SUMMON_BEAST_CARD_ID)


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.effects.append(
        EffectSpec(
            EffectTiming.ON_PLACE_BASE,
            _add_summon_beast_from_outside,
            condition=_self_is_placed,
            official_effect="「「ブルーナの召喚獣」ジャイ Lv2」1枚を手札に加える。",
            official_timing="配置時",
            active_areas=(AreaType.BASE,),
        )
    )
    return card
