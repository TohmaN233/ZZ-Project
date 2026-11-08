from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming
from zz.enums import AreaType, CardType
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = 'colorless_07_01_03_01'


def _self_summoned(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source


def _return_own_goblins_and_gain_stats(source: CardInstance, state: Any, _ctx: Context) -> None:
    engine = state.engine
    if engine is None:
        raise RuntimeError(f"{CARD_ID} summon effect requires an Engine")
    targets = [
        target
        for target in list(source.owner.field)
        if target is not source
        and target.card.type is CardType.F_MINION
        and "ゴブリン" in target.card.race_jp.split("|")
    ]
    returned = sum(
        1
        for target in targets
        if engine.return_to_hand(target, source=source)
    )
    if returned:
        engine.modify_stat(
            source,
            bp_delta=100 * returned,
            dp_delta=returned,
            duration="permanent",
        )


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.effects.append(
        EffectSpec(
            EffectTiming.ON_SUMMON,
            _return_own_goblins_and_gain_stats,
            condition=_self_summoned,
            official_effect=(
                "他の自分の種族「ゴブリン」を持つミニオン全てを手札に戻す。"
                "この効果で戻したミニオン1体毎に、このミニオンにBP+100/DP+1を付与する。"
            ),
            official_timing="召喚時",
            active_areas=(AreaType.FIELD,),
        )
    )
    return card
