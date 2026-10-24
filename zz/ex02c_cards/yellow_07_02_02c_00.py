from __future__ import annotations

from copy import copy
from typing import Any

from zz.cards import CARD_REGISTRY
from zz.effects import EffectSpec, EffectTiming, build_effect
from zz.enums import AreaType, Color
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row
from zz.transformations import transformation_target_id


CARD_ID = "yellow_07_02_02c_00"
TRANSFORMED_CARD_ID = "yellow_07_02_02c_1"


def _this_minion_was_summoned(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source


def _was_given_a_yellow_bless(source: CardInstance, state: Any, ctx: Context) -> bool:
    mana = ctx.target
    return (
        ctx.source is source
        and isinstance(mana, CardInstance)
        and mana.area is AreaType.BLESSING
        and mana in source.blessings
        and state.engine._mana_color_of(mana) is Color.YELLOW
    )


def _transform_with_yellow_bless(source: CardInstance, state: Any, ctx: Context) -> None:
    mana = ctx.target
    if not isinstance(mana, CardInstance):
        raise RuntimeError(f"{CARD_ID} transformation requires its attached Yellow Mana")
    if mana.area is not AreaType.BLESSING or mana not in source.blessings:
        raise RuntimeError(f"{CARD_ID} transformation target is not attached to this Minion")
    if state.engine._mana_color_of(mana) is not Color.YELLOW:
        raise RuntimeError(f"{CARD_ID} transformation received non-Yellow Bless Mana")
    try:
        target_id = transformation_target_id(source.card.id, TRANSFORMED_CARD_ID)
        transformed = copy(CARD_REGISTRY[target_id])
    except KeyError as exc:
        raise RuntimeError(f"{CARD_ID} transformed face is not registered: {TRANSFORMED_CARD_ID}") from exc
    transformed.cost = dict(transformed.cost)
    transformed.keywords = list(transformed.keywords)
    transformed.effects = list(transformed.effects)
    transformed.triggers = list(transformed.triggers)
    state.engine.banish_blessing_mana(source, mana, source=source)
    state.engine.transform_card(source, transformed, target=mana)


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.can_bless_while_rested = False
    card.effects.extend([
        build_effect(
            "return_to_hand",
            EffectTiming.ON_SUMMON,
            condition=_this_minion_was_summoned,
            target_kind="enemy_minion",
            min_targets=1,
            max_targets=1,
            exclude_color=Color.COLORLESS,
            ex02c_switch_races=["閃光"],
            active_areas=(AreaType.FIELD,),
            official_effect="相手の有色のミニオン1体を手札に戻す。",
            official_timing="召喚時＆スイッチ",
        ),
        EffectSpec(
            timing=EffectTiming.ON_BLESS,
            fn=_transform_with_yellow_bless,
            condition=_was_given_a_yellow_bless,
            active_areas=(AreaType.FIELD,),
            official_effect=(
                "黄の加護である場合、加護しているマナを除外して、"
                "「「絶剣」ユウキ」に変形する。"
            ),
            official_timing="加護時",
        ),
    ])
    return card
