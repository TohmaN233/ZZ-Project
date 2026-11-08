from __future__ import annotations

from copy import copy
from typing import Any

from zz.cards import CARD_REGISTRY
from zz.effects import EffectSpec, EffectTiming
from zz.enums import AreaType, Color
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row
from zz.transformations import transformation_target_id


CARD_ID = "purple_04_01_03_00"
TRANSFORMED_CARD_ID = "purple_04_01_03_01"


def _self_summoned(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source and source.area is AreaType.FIELD


def _discard_both_decks(source: CardInstance, state: Any, _ctx: Context) -> None:
    engine = state.engine
    if engine is None:
        raise RuntimeError(f"{CARD_ID} summon effect requires an Engine")
    for player in state.players:
        engine.mill_deck(player, 3, source=source)


def _received_purple_bless(source: CardInstance, state: Any, ctx: Context) -> bool:
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
        and engine._mana_color_of(mana) is Color.PURPLE
    )


def _transform_on_purple_bless(source: CardInstance, state: Any, ctx: Context) -> None:
    mana = ctx.target
    engine = state.engine
    if engine is None:
        raise RuntimeError(f"{CARD_ID} transformation requires an Engine")
    if not isinstance(mana, CardInstance) or mana.area is not AreaType.BLESSING or mana not in source.blessings:
        raise RuntimeError(f"{CARD_ID} transformation requires its attached Bless Mana")
    if engine._mana_color_of(mana) is not Color.PURPLE:
        raise RuntimeError(f"{CARD_ID} transformation received non-Purple Bless Mana")
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
    card.ability_jp = (
        "【召喚時】お互いのデッキを上から3枚ずつ破棄する。\n"
        "【常時】このミニオンがアクティブ状態でなければ[加護]は付与されない。\n"
        "【加護時】紫の加護である場合、加護しているマナを除外して、「「闇夜の狂人」ナイブス」に変形する。"
    )
    card.can_bless_while_rested = False
    card.effects.extend(
        [
            EffectSpec(
                EffectTiming.ON_SUMMON,
                _discard_both_decks,
                condition=_self_summoned,
                official_effect="お互いのデッキを上から3枚ずつ破棄する。",
                official_timing="召喚時",
                active_areas=(AreaType.FIELD,),
            ),
            EffectSpec(
                EffectTiming.ON_BLESS,
                _transform_on_purple_bless,
                condition=_received_purple_bless,
                official_effect="紫の加護である場合、加護しているマナを除外して、「「闇夜の狂人」ナイブス」に変形する。",
                official_timing="加護時",
                active_areas=(AreaType.FIELD,),
            ),
        ]
    )
    return card
