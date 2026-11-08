from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming
from zz.engine import FIELD_CAP
from zz.enums import AreaType, CardType, Color
from zz.model import Card, CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "red_06_02_03_00"
ARCANA_RACE = "アルカナ"


def _flash_timing_condition(player: Any, _state: Any, source: CardInstance) -> bool:
    if source.owner is not player:
        return False
    return any(
        minion.area is AreaType.FIELD
        and minion.owner is player
        and minion.card.type is CardType.F_MINION
        and ARCANA_RACE in minion.card.race_jp.split("|")
        for minion in player.field
    )


def _self_cast(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source


def _fill_field_with_golem_s(source: CardInstance, state: Any, _ctx: Context) -> None:
    engine = state.engine
    if engine is None:
        raise RuntimeError(f"{CARD_ID} summon effect requires an Engine")
    empty_slots = FIELD_CAP - len(source.owner.field)
    if empty_slots < 0:
        raise RuntimeError(f"{CARD_ID} found an over-capacity Field: {len(source.owner.field)}")
    if empty_slots == 0:
        return
    token = Card(
        id="s_golem_token",
        name_jp="S・ゴレイム・トークン",
        name_en="Token Golem S",
        type=CardType.F_MINION,
        cost={Color.RED: 1},
        bp=100,
        dp=1,
        race_jp="ゴレイム",
    )
    engine.create_tokens(source.owner, [token] * empty_slots, source=source)


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.ability_jp = (
        "このカードは自分の種族「アルカナ」を持つミニオンがいないとき、"
        "フラッシュタイミングで使用できない。\n"
        "【メイン】／【フラッシュ】\n"
        "「S・ゴレイム・トークン」を自分のフィールドが上限枚数になるまで出す。"
    )
    card.main_timing_ok = True
    card.flash_timing_ok = True
    card.flash_timing_condition = _flash_timing_condition
    card.effects.append(
        EffectSpec(
            EffectTiming.ON_CAST_MAGIC,
            _fill_field_with_golem_s,
            condition=_self_cast,
            official_effect="「S・ゴレイム・トークン」を自分のフィールドが上限枚数になるまで出す。",
            official_timing="メイン／フラッシュ",
        )
    )
    return card
