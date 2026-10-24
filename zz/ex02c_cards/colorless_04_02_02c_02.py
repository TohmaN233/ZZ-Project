from __future__ import annotations

from typing import Any

from zz.effects import EffectTiming, build_effect
from zz.enums import AreaType
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = 'colorless_04_02_02c_02'


def _self_source(source: CardInstance, _state: Any, ctx: Context) -> bool:
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
            min_targets=1,
            max_targets=1,
            bp_delta=100,
            dp_delta=1,
            duration="turn",
            max_cost=2,
            active_areas=(AreaType.FIELD,),
            official_effect="自分のコスト2のミニオン1体にBP+100/DP+1を付与する。",
            official_timing="召喚時＆スイッチ",
            official_condition="スイッチ：「黒の剣士」",
        )
    )
    card.effects[-1].params["ex02c_switch_races"] = ["黒の剣士"]
    return card
