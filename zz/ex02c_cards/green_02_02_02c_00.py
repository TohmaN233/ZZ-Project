from __future__ import annotations

from typing import Any

from zz.effects import EffectTiming, build_effect
from zz.enums import AreaType
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "green_02_02_02c_00"


def _has_another_sword(source: CardInstance) -> bool:
    return any(
        minion is not source
        and minion.area is AreaType.FIELD
        and "ソード" in minion.card.race_jp.split("|")
        for minion in source.owner.field
    )


def _should_refresh_item_mana(source: CardInstance, _state: Any, _ctx: Context) -> bool:
    return source.area is AreaType.FIELD and _has_another_sword(source)


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.ability_jp = (
        "【召喚時】スイッチ：「氷剣」"
        "他の自分の種族「ソード」を持つミニオンがいる場合、"
        "自分の種族「アイテム」を持つマナ1つをアクティブにする。"
    )
    card.effects.append(
        build_effect(
            "refresh_targets",
            EffectTiming.ON_SUMMON,
            condition=_should_refresh_item_mana,
            target_kind="ally_base",
            min_targets=1,
            max_targets=1,
            race="アイテム",
            only_rested=True,
            ex02c_switch_races=["氷剣"],
            official_effect="自分の種族「アイテム」を持つマナ1つをアクティブにする。",
            official_timing="召喚時＆スイッチ",
            official_condition="他の自分の種族「ソード」を持つミニオンがいる場合",
            active_areas=(AreaType.FIELD,),
        )
    )
    return card
