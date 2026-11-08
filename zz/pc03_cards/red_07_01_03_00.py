from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming
from zz.enums import AreaType, CardType, Color, Keyword
from zz.model import Card, CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "red_07_01_03_00"
TOKEN_M_ID = "m_golem_token"


def _self_summoned(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source and source.area is AreaType.FIELD


def _destroy_tokens_and_create_equal_m(source: CardInstance, state: Any, _ctx: Context) -> None:
    engine = state.engine
    if engine is None:
        raise RuntimeError(f"{CARD_ID} summon effect requires an Engine")
    token_minions = [
        target
        for target in list(source.owner.field)
        if target.card.type is CardType.F_MINION and target.card.is_token
    ]
    for target in token_minions:
        engine.destroy_target(target, source)
    destroyed_count = sum(target not in target.owner.field for target in token_minions)
    if destroyed_count == 0:
        return
    m_token = Card(
        id=TOKEN_M_ID,
        name_jp="M・ゴレイム・トークン",
        name_en="Token Golem M",
        type=CardType.F_MINION,
        cost={Color.RED: 4},
        bp=500,
        dp=1,
        race_jp="ゴレイム",
        keywords=[Keyword.RUSH],
    )
    engine.create_tokens(source.owner, [m_token] * destroyed_count, source=source)


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.effects.append(
        EffectSpec(
            EffectTiming.ON_SUMMON,
            _destroy_tokens_and_create_equal_m,
            condition=_self_summoned,
            official_effect=(
                "自分のミニオン・トークン全てを破壊する。この効果で破壊したミニオン1体毎に、"
                "「M・ゴレイム・トークン」1体を出す。"
            ),
            official_timing="召喚時",
            active_areas=(AreaType.FIELD,),
        )
    )
    return card
