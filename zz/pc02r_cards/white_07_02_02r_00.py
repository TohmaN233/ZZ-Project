from __future__ import annotations

from copy import copy
from typing import Any

from zz.cards import CARD_REGISTRY
from zz.effects import EffectSpec, EffectTiming, build_effect
from zz.enums import AreaType, Color
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "white_07_02_02r_00"
TRANSFORMED_CARD_ID = "white_07_02_02r_01"


def _this_minion_was_summoned(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source


def _this_minion_was_white_blessed(source: CardInstance, state: Any, ctx: Context) -> bool:
    mana = ctx.target
    return (
        ctx.source is source
        and isinstance(mana, CardInstance)
        and mana.area is AreaType.BLESSING
        and mana in source.blessings
        and state.engine._mana_color_of(mana) is Color.WHITE
    )


def _transform_with_white_bless(source: CardInstance, state: Any, ctx: Context) -> None:
    mana = ctx.target
    if not isinstance(mana, CardInstance):
        raise RuntimeError(f"{CARD_ID} transformation requires its attached White Mana")
    if mana.area is not AreaType.BLESSING or mana not in source.blessings:
        raise RuntimeError(f"{CARD_ID} transformation target is not attached to this Minion")

    engine = state.engine
    if engine._mana_color_of(mana) is not Color.WHITE:
        raise RuntimeError(f"{CARD_ID} transformation received non-White Bless Mana")
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


def _discard_two_after_drawing(source: CardInstance, state: Any, _ctx: Context) -> None:
    engine = state.engine
    targets = engine.select_target(source.owner, "hand_card", 2, 2, source=source)
    if len(targets) != 2:
        raise RuntimeError(f"{CARD_ID} requires exactly two cards to discard")
    for target in targets:
        engine.discard_from_hand(source.owner, target)


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.can_bless_while_rested = False
    card.effects = list(card.effects) + [
        build_effect(
            "draw_cards",
            EffectTiming.ON_SUMMON,
            condition=_this_minion_was_summoned,
            amount=2,
            official_effect="召喚時、カードを2枚引く",
            official_timing="召喚時",
        ),
        EffectSpec(
            timing=EffectTiming.ON_SUMMON,
            fn=_discard_two_after_drawing,
            condition=_this_minion_was_summoned,
            active_areas=(AreaType.FIELD,),
            target_kind="hand_card",
            min_targets=2,
            max_targets=2,
            official_effect="その後、手札から2枚破棄する",
            official_timing="召喚時",
        ),
        EffectSpec(
            timing=EffectTiming.ON_BLESS,
            fn=_transform_with_white_bless,
            condition=_this_minion_was_white_blessed,
            official_effect="白の加護マナを除外し、氷雪械竜グリフォンに変形する",
            official_timing="加護時",
        ),
    ]
    return card
