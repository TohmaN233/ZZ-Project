from __future__ import annotations

from typing import Any

from zz.effects import EffectTiming, build_effect
from zz.enums import AreaType, CardType, Color
from zz.model import CardInstance
from zz.pc01 import _card_from_row


CARD_ID = "blue_05_02_03_00"
ARCANA_RACE = "アルカナ"


def _flash_timing_condition(player: Any, state: Any, source: CardInstance) -> bool:
    if source.owner is not player:
        return False
    return any(
        minion.area is AreaType.FIELD
        and minion.owner is player
        and minion.card.type in (CardType.F_MINION, CardType.B_MINION)
        and ARCANA_RACE in minion.card.race_jp.split("|")
        for minion in player.field
    )


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.ability_jp = (
        "このカードは自分の種族「アルカナ」を持つミニオンがいないとき、"
        "フラッシュタイミングで使用できない。\n"
        "【メイン】／【フラッシュ】「マーフォーク・トークン」2体を出す。"
    )
    card.ability_en = (
        "You cannot use this card during the Flash timing unless you have a Minion "
        "belonging to the Arcana class on your Field.\n"
        "[Main] / [Flash] Two Token Merfolk enter your Field."
    )
    card.main_timing_ok = True
    card.flash_timing_ok = True
    card.flash_timing_condition = _flash_timing_condition
    card.effects.append(
        build_effect(
            "create_tokens",
            EffectTiming.ON_CAST_MAGIC,
            amount=2,
            token_id="merfolk_token",
            name_jp="マーフォーク・トークン",
            color=Color.BLUE,
            cost=2,
            bp=200,
            dp=1,
            race_jp="マーフォーク",
            official_effect="「マーフォーク・トークン」2体を出す。",
            official_timing="メイン／フラッシュ",
        )
    )
    return card
