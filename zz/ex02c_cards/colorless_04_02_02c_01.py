from __future__ import annotations

from typing import Any

from zz.pc01 import _card_from_row
from zz.effects import EffectTiming, build_effect
from zz.enums import AreaType
from zz.model import CardInstance, Context


CARD_ID = 'colorless_04_02_02c_01'


def _self_source(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.effects.append(
        build_effect(
            "heal_targets",
            EffectTiming.ON_SUMMON,
            condition=_self_source,
            target_kind="ally_force",
            min_targets=1,
            max_targets=1,
            amount=1,
            active_areas=(AreaType.FIELD,),
            official_effect="自分のフォース1つを1回復する。",
            official_timing="召喚時＆スイッチ",
            official_condition="スイッチ：「黒の剣士」",
        )
    )
    card.effects[-1].params["ex02c_switch_races"] = ["黒の剣士"]
    return card
