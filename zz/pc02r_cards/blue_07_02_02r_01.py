from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming
from zz.enums import CardType, Color, Keyword
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "blue_07_02_02r_01"


def _this_minion_dealt_damage(source: CardInstance, state: Any, ctx: Context) -> bool:
    return state.active is source.owner and ctx.source is source


def _this_minion_was_transformed(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source


def _grant_sneaking_to_blue_minions(source: CardInstance, state: Any, _ctx: Context) -> None:
    engine = state.engine
    for target in source.owner.field:
        if (
            target.card.type in (CardType.F_MINION, CardType.B_MINION)
            and target.card.id.startswith("blue_")
        ):
            engine.add_keyword(target, Keyword.SNEAKING, duration="turn")


def _activate_own_blue_mana(source: CardInstance, state: Any, _ctx: Context) -> None:
    engine = state.engine
    for mana in source.owner.base:
        if engine._mana_color_of(mana) is Color.BLUE:
            engine.refresh_target(mana)


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    if Keyword.RUSH not in card.keywords:
        card.keywords = list(card.keywords) + [Keyword.RUSH]
    card.effects = list(card.effects) + [
        EffectSpec(
            timing=EffectTiming.ON_TRANSFORM,
            fn=_grant_sneaking_to_blue_minions,
            condition=_this_minion_was_transformed,
            official_effect="変形時に自分の青のミニオン全てにこのターン潜入を与える",
            official_timing="変形時",
        ),
    ] + [
        EffectSpec(
            timing=timing,
            fn=_activate_own_blue_mana,
            condition=_this_minion_dealt_damage,
            official_effect="このミニオンがダメージを与えるたび、自分の青マナをすべてアクティブにする",
            official_timing="自分のターン中のダメージ時",
        )
        for timing in (EffectTiming.ON_DAMAGE_PLAYER, EffectTiming.ON_DAMAGE_FORCE)
    ]
    return card
