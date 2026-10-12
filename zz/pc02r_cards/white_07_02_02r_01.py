from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming
from zz.enums import AreaType, CardType, Keyword
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "white_07_02_02r_01"


def _this_minion_was_transformed(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source


def _grant_charge(source: CardInstance, state: Any, _ctx: Context) -> None:
    engine = state.engine
    for target in list(source.owner.field):
        if target.card.type is not CardType.F_MINION:
            continue
        engine.modify_stat(target, bp_delta=100, duration="permanent")
        engine.add_keyword(target, Keyword.REAWAKEN)


def _won_battle_on_own_turn(source: CardInstance, state: Any, ctx: Context) -> bool:
    target = ctx.target
    return (
        ctx.source is source
        and state.active is source.owner
        and isinstance(target, CardInstance)
        and target.owner is not source.owner
        and target.area is AreaType.FIELD
    )


def _refresh_after_win(source: CardInstance, state: Any, _ctx: Context) -> None:
    if source.area is not AreaType.FIELD:
        raise RuntimeError("Charge battle-win trigger fired after its source left the Field")
    state.engine.refresh_target(source)


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    if Keyword.RUSH not in card.keywords:
        card.keywords = list(card.keywords) + [Keyword.RUSH]
    card.effects = list(card.effects) + [
        EffectSpec(
            timing=EffectTiming.ON_TRANSFORM,
            fn=_grant_charge,
            condition=_this_minion_was_transformed,
            official_effect="自分のミニオン全てにBP+100と再起を与える",
            official_timing="変形時",
        ),
        EffectSpec(
            timing=EffectTiming.ON_BATTLE_WIN,
            fn=_refresh_after_win,
            condition=_won_battle_on_own_turn,
            official_effect="自分のターン中にミニオンとのバトルに勝利した時、このミニオンをアクティブにする",
            official_timing="自分のターン中のバトル勝利時",
        ),
    ]
    return card
