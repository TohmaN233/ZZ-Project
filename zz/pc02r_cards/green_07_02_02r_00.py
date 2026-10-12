from __future__ import annotations

from copy import copy
from typing import Any

from zz.cards import CARD_REGISTRY
from zz.effects import EffectSpec, EffectTiming, build_effect
from zz.enums import AreaType, Color
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "green_07_02_02r_00"
TRANSFORMED_CARD_ID = "green_07_02_02r_01"


def _this_rory_was_summoned(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source


def _this_rory_was_green_blessed(source: CardInstance, state: Any, ctx: Context) -> bool:
    mana = ctx.target
    return (
        ctx.source is source
        and isinstance(mana, CardInstance)
        and state.engine._mana_color_of(mana) is Color.GREEN
    )


def _transform_with_green_bless(source: CardInstance, state: Any, ctx: Context) -> None:
    mana = ctx.target
    if not isinstance(mana, CardInstance):
        raise RuntimeError(f"{CARD_ID} transformation requires its attached Green Mana")
    if mana.area is not AreaType.BLESSING or mana not in source.blessings:
        raise RuntimeError(f"{CARD_ID} transformation target is not attached to this Minion")
    engine = state.engine
    if engine._mana_color_of(mana) is not Color.GREEN:
        raise RuntimeError(f"{CARD_ID} transformation received non-Green Bless Mana")
    try:
        transformed = copy(CARD_REGISTRY[TRANSFORMED_CARD_ID])
    except KeyError as exc:
        raise RuntimeError(f"{CARD_ID} transformed face is not registered: {TRANSFORMED_CARD_ID}") from exc
    transformed.cost = dict(transformed.cost)
    transformed.keywords = list(transformed.keywords)
    transformed.effects = list(transformed.effects)
    transformed.triggers = list(transformed.triggers)

    source.blessings.remove(mana)
    engine._reset_card_zone_state(mana)
    mana.area = AreaType.REMOVED
    mana.owner.removed.append(mana)
    engine._record_zone_move(mana, AreaType.BLESSING, AreaType.REMOVED)
    engine.transform_card(source, transformed, target=mana)


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.can_bless_while_rested = False
    card.effects = list(card.effects) + [
        build_effect(
            "place_colorless_mana",
            EffectTiming.ON_SUMMON,
            condition=_this_rory_was_summoned,
            active_areas=(AreaType.FIELD,),
            mana_color=Color.GREEN,
            official_effect="自分のベースに緑マナを1つ置く",
            official_timing="召喚時",
        ),
        EffectSpec(
            timing=EffectTiming.ON_BLESS,
            fn=_transform_with_green_bless,
            condition=_this_rory_was_green_blessed,
            active_areas=(AreaType.FIELD,),
            official_effect="緑の加護マナを除外し、Rory - Barbarian of the Earthに変形する",
            official_timing="加護時",
        ),
    ]
    return card
