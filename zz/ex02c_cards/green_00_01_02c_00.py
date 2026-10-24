from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming
from zz.enums import AreaType, CardType, Keyword
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "green_00_01_02c_00"


def _this_base_minion_was_placed(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source


def _heal_if_two_swords_are_on_field(source: CardInstance, state: Any, _ctx: Context) -> None:
    sword_minions = [
        minion
        for minion in source.owner.field
        if minion.card.type is CardType.F_MINION
        and "ソード" in minion.card.race_jp.split("|")
    ]
    if len(sword_minions) >= 2:
        state.engine.heal(source.owner, 1)


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    if Keyword.CANNOT_BLOCK not in card.keywords:
        card.keywords.append(Keyword.CANNOT_BLOCK)
    card.effects.append(
        EffectSpec(
            timing=EffectTiming.ON_PLACE_BASE,
            fn=_heal_if_two_swords_are_on_field,
            condition=_this_base_minion_was_placed,
            active_areas=(AreaType.BASE,),
            official_effect=(
                "フィールドに自分の種族「ソード」を持つミニオンが2体以上いる場合、"
                "自分のプレイヤーを1回復する。"
            ),
            official_timing="配置時",
        )
    )
    return card
