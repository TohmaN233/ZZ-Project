from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming
from zz.enums import AreaType, CardType, Color
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "red_06_02_02c_01"
_NEXT_BLACK_SWORD_FREE_COST = "turn:ex02c_asuna_next_black_sword_free_cost"


def _has_race(card: CardInstance, race: str) -> bool:
    return race in card.card.race_jp.split("|")


def _self_source(source: CardInstance, state: Any, ctx: Context) -> bool:
    return ctx.source is source


def _summon_and_switch(source: CardInstance, state: Any, ctx: Context) -> None:
    engine = state.engine
    opponent = state.players[1 - state.players.index(source.owner)]
    for target in list(opponent.field):
        engine.modify_stat(target, bp_delta=-200, duration="turn")
    for target in list(source.owner.field):
        if _has_race(target, "黒の剣士") or _has_race(target, "閃光"):
            engine.modify_stat(target, bp_delta=200, duration="turn")


def _attack(source: CardInstance, state: Any, ctx: Context) -> None:
    source.flags.add(_NEXT_BLACK_SWORD_FREE_COST)


def _used_black_swordsman_from_hand(source: CardInstance, state: Any, ctx: Context) -> bool:
    used = ctx.source
    return (
        _NEXT_BLACK_SWORD_FREE_COST in source.flags
        and source.area is AreaType.FIELD
        and isinstance(used, CardInstance)
        and used.owner is source.owner
        and used.area is AreaType.FIELD
        and used.card.type is CardType.F_MINION
        and _has_race(used, "黒の剣士")
    )


def _consume_next_free_cost(source: CardInstance, state: Any, ctx: Context) -> None:
    source.flags.discard(_NEXT_BLACK_SWORD_FREE_COST)


def _black_swordsman_cost_aura(source: CardInstance, target: CardInstance, state: Any) -> int:
    if (
        source.area is AreaType.FIELD
        and _NEXT_BLACK_SWORD_FREE_COST in source.flags
        and target.owner is source.owner
        and target.area is AreaType.HAND
        and target.card.type is CardType.F_MINION
        and _has_race(target, "黒の剣士")
    ):
        return -target.card.cost.get(Color.COLORLESS, 0)
    return 0


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.cost_aura = _black_swordsman_cost_aura
    card.effects.extend([
        EffectSpec(
            timing=EffectTiming.ON_SUMMON,
            fn=_summon_and_switch,
            condition=_self_source,
            params={"ex02c_switch_races": ["黒の剣士"]},
            official_effect=(
                "このターン中、相手のミニオン全てをBP-200し、"
                "自分の種族「黒の剣士」または「閃光」を持つミニオン全てをBP+200する。"
            ),
            official_timing="召喚時＆スイッチ",
            active_areas=(AreaType.FIELD,),
        ),
        EffectSpec(
            timing=EffectTiming.ON_ATTACK,
            fn=_attack,
            condition=_self_source,
            official_effect=(
                "このターン、次に自分の手札から種族「黒の剣士」を持つ"
                "ミニオンカードを召喚するとき、そのフリーコストを0にする。"
            ),
            official_timing="アタック時",
            active_areas=(AreaType.FIELD,),
        ),
        EffectSpec(
            timing=EffectTiming.ON_CARD_USED,
            fn=_consume_next_free_cost,
            condition=_used_black_swordsman_from_hand,
            official_effect="次に手札から召喚した種族「黒の剣士」のフリーコストを消費する。",
            official_timing="カード使用時",
            active_areas=(AreaType.FIELD,),
        ),
    ])
    return card
