from __future__ import annotations

from copy import copy
from typing import Any

from zz.cards import CARD_REGISTRY
from zz.effects import EffectSpec, EffectTiming, build_effect
from zz.enums import AreaType, Color
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row
from zz.transformations import transformation_target_id


CARD_ID = "blue_03_01_03_00"
TRANSFORMED_CARD_ID = "blue_03_01_03_01"


def _self_source(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source


def _received_blue_bless(source: CardInstance, state: Any, ctx: Context) -> bool:
    mana = ctx.target
    return (
        ctx.source is source
        and source.area is AreaType.FIELD
        and isinstance(mana, CardInstance)
        and mana.area is AreaType.BLESSING
        and mana in source.blessings
        and state.engine._mana_color_of(mana) is Color.BLUE
    )


def _transform_on_blue_bless(source: CardInstance, state: Any, ctx: Context) -> None:
    mana = ctx.target
    if not isinstance(mana, CardInstance):
        raise RuntimeError(f"{CARD_ID} transformation requires the attached Blue Bless Mana")
    if mana.area is not AreaType.BLESSING or mana not in source.blessings:
        raise RuntimeError(f"{CARD_ID} transformation target is not attached to this Minion")
    if state.engine._mana_color_of(mana) is not Color.BLUE:
        raise RuntimeError(f"{CARD_ID} transformation received non-Blue Bless Mana")
    try:
        target_id = transformation_target_id(CARD_ID, TRANSFORMED_CARD_ID)
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
    card.ability_jp = (
        "【召喚時】相手のミニオン1体にBP-100と本来の数値にDP-1を付与する。\n"
        "【常時】このミニオンがアクティブ状態でなければ［加護］は付与されない。\n"
        "【加護時】青の加護である場合、加護しているマナを除外して、"
        "「「解放のギタリスト」メタル」に変形する。"
    )
    card.can_bless_while_rested = False
    card.effects.extend(
        [
            build_effect(
                "stat_modifier",
                EffectTiming.ON_SUMMON,
                condition=_self_source,
                target_kind="enemy_minion",
                bp_delta=-100,
                dp_delta=-1,
                duration="permanent",
                official_effect="相手のミニオン1体にBP-100と本来の数値にDP-1を付与する。",
                official_timing="召喚時",
            ),
            EffectSpec(
                EffectTiming.ON_BLESS,
                _transform_on_blue_bless,
                condition=_received_blue_bless,
                official_effect="青の加護である場合、加護しているマナを除外して、"
                "「「解放のギタリスト」メタル」に変形する。",
                official_timing="加護時",
                active_areas=(AreaType.FIELD,),
            ),
        ]
    )
    return card
