from __future__ import annotations

from typing import Any

from zz.effects import EffectTiming, build_effect
from zz.enums import AreaType, CardType
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "yellow_02_02_02c_00"


def _self_source(source: CardInstance, state: Any, ctx: Context) -> bool:
    return ctx.source is source


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.effects.append(
        build_effect(
            "look_top_to_hand",
            EffectTiming.ON_SUMMON,
            condition=_self_source,
            target_kind="top2_field_minion",
            min_targets=1,
            max_targets=1,
            official_effect=(
                "自分のデッキを上から2枚見て、その中の種族「ソード」を持つ"
                "フィールド・ミニオンカード1枚を公開して手札に加える。"
                "残りをランダムにデッキの下に戻す。"
            ),
            official_timing="召喚時＆スイッチ",
            active_areas=(AreaType.FIELD,),
            top_n=2,
            card_type=CardType.F_MINION,
            race="ソード",
            ex02c_switch_races=["閃光", "絶剣"],
        )
    )
    return card
