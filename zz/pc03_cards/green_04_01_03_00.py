from __future__ import annotations

from copy import copy
from typing import Any

from zz.cards import CARD_REGISTRY
from zz.effects import EffectSpec, EffectTiming, build_effect
from zz.enums import AreaType, CardType, Color
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row
from zz.transformations import transformation_target_id


CARD_ID = "green_04_01_03_00"
TRANSFORMED_CARD_ID = "green_04_01_03_01"


def _self_source(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source


def _received_green_bless(source: CardInstance, state: Any, ctx: Context) -> bool:
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
        and engine._mana_color_of(mana) is Color.GREEN
    )


def _transform_on_green_bless(source: CardInstance, state: Any, ctx: Context) -> None:
    mana = ctx.target
    if not isinstance(mana, CardInstance):
        raise RuntimeError(f"{CARD_ID} transformation requires the attached Green Bless Mana")
    if mana.area is not AreaType.BLESSING or mana not in source.blessings:
        raise RuntimeError(f"{CARD_ID} transformation target is not attached to this Minion")
    engine = state.engine
    if engine is None:
        raise RuntimeError(f"{CARD_ID} transformation requires an Engine")
    if engine._mana_color_of(mana) is not Color.GREEN:
        raise RuntimeError(f"{CARD_ID} transformation received non-Green Bless Mana")
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


def _rest_and_lock_target(source: CardInstance, state: Any, _ctx: Context) -> None:
    engine = state.engine
    if engine is None:
        raise RuntimeError(f"{CARD_ID} summon effect requires an Engine")
    targets = engine.select_target(
        source.owner,
        "enemy_minion_or_force",
        1,
        1,
        source=source,
    )
    for target in targets:
        engine.rest_target(target)
        engine.prevent_activation_until_next_standby_end(target)


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.can_bless_while_rested = False
    card.effects.extend(
        [
            EffectSpec(
                EffectTiming.ON_SUMMON,
                _rest_and_lock_target,
                condition=_self_source,
                target_kind="enemy_minion_or_force",
                params={"max_cost": 3},
                official_effect=(
                    "相手のコスト3以下のミニオン1体か相手のフォース1つをレストする。"
                    "それは次の相手のスタンバイフェイズ終了時までアクティブにならない。"
                ),
                official_timing="召喚時",
                active_areas=(AreaType.FIELD,),
            ),
            EffectSpec(
                EffectTiming.ON_BLESS,
                _transform_on_green_bless,
                condition=_received_green_bless,
                official_effect=(
                    "緑の加護である場合、加護しているマナを除外して、"
                    "「「虹の魔術師」ピオン」に変形する。"
                ),
                official_timing="加護時",
                active_areas=(AreaType.FIELD,),
            ),
        ]
    )
    return card
