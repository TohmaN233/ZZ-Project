from __future__ import annotations

from copy import copy
from typing import Any

from zz.cards import CARD_REGISTRY
from zz.effects import EffectSpec, EffectTiming, build_effect
from zz.enums import AreaType, CardType, Color
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row
from zz.transformations import transformation_target_id


CARD_ID = "red_04_01_03_02"
TRANSFORMED_CARD_ID = "red_04_01_03_03"


def _self_summoned(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source and source.area is AreaType.FIELD


def _self_summoned_with_enemy(source: CardInstance, state: Any, ctx: Context) -> bool:
    if not _self_summoned(source, state, ctx):
        return False
    opponent = state.players[1 - state.players.index(source.owner)]
    return any(
        target.area is AreaType.FIELD
        and target.owner is opponent
        and target.card.type is CardType.F_MINION
        for target in opponent.field
    )


def _received_red_bless(source: CardInstance, state: Any, ctx: Context) -> bool:
    mana = ctx.target
    engine = state.engine
    if engine is None:
        raise RuntimeError(f"{CARD_ID} Bless trigger requires an Engine")
    return (
        ctx.source is source
        and source.area is AreaType.FIELD
        and isinstance(mana, CardInstance)
        and mana.area is AreaType.BLESSING
        and mana in source.blessings
        and engine._mana_color_of(mana) is Color.RED
    )


def _transform_on_red_bless(source: CardInstance, state: Any, ctx: Context) -> None:
    mana = ctx.target
    engine = state.engine
    if engine is None:
        raise RuntimeError(f"{CARD_ID} transformation requires an Engine")
    if not isinstance(mana, CardInstance) or mana.area is not AreaType.BLESSING or mana not in source.blessings:
        raise RuntimeError(f"{CARD_ID} transformation requires its attached Bless Mana")
    if engine._mana_color_of(mana) is not Color.RED:
        raise RuntimeError(f"{CARD_ID} transformation received non-Red Bless Mana")
    try:
        target_id = transformation_target_id(CARD_ID, TRANSFORMED_CARD_ID)
        transformed = copy(CARD_REGISTRY[target_id])
    except KeyError as exc:
        raise RuntimeError(f"{CARD_ID} transformed face is not registered: {TRANSFORMED_CARD_ID}") from exc
    transformed.cost = dict(transformed.cost)
    transformed.keywords = list(transformed.keywords)
    transformed.effects = list(transformed.effects)
    transformed.triggers = list(transformed.triggers)
    engine.banish_blessing_mana(source, mana, source=source)
    engine.transform_card(source, transformed, target=mana)


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.can_bless_while_rested = False
    card.effects.extend(
        [
            build_effect(
                "stat_modifier",
                EffectTiming.ON_SUMMON,
                condition=_self_summoned_with_enemy,
                target_kind="enemy_minion",
                bp_delta=-200,
                duration="permanent",
                official_effect="相手のミニオン1体にBP-200を付与する。",
                official_timing="召喚時",
            ),
            EffectSpec(
                EffectTiming.ON_BLESS,
                _transform_on_red_bless,
                condition=_received_red_bless,
                official_effect=(
                    "赤の加護である場合、加護しているマナを除外して、"
                    "「「紅蓮の猛者」レッドビア」に変形する。"
                ),
                official_timing="加護時",
                active_areas=(AreaType.FIELD,),
            ),
        ]
    )
    return card
