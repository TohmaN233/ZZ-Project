from __future__ import annotations

from copy import copy
from typing import Any

from zz.cards import CARD_REGISTRY
from zz.effects import EffectSpec, EffectTiming
from zz.enums import AreaType, Color
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "blue_07_02_02r_00"
TRANSFORMED_CARD_ID = "blue_07_02_02r_01"


def _this_orka_was_summoned(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source and bool(source.owner.deck)


def _look_at_top_three_and_choose(source: CardInstance, state: Any, _ctx: Context) -> None:
    engine = state.engine
    owner = source.owner
    window = list(owner.deck[:3])
    if not window:
        return
    selected = engine.select_target(
        owner,
        "top3_card",
        1,
        1,
        source=source,
    )
    if not selected:
        return
    chosen = selected[0]
    if chosen not in window:
        raise RuntimeError(f"{CARD_ID} selected a card outside its top-three window")
    owner.deck.remove(chosen)
    engine.reveal_card(owner, chosen, "top_cards")
    engine.add_to_hand(owner, chosen, from_area=AreaType.DECK)
    remaining = [candidate for candidate in window if candidate is not chosen]
    for candidate in remaining:
        owner.deck.remove(candidate)
    engine.rng.shuffle(remaining)
    owner.deck.extend(remaining)


def _this_orka_was_blue_blessed(source: CardInstance, state: Any, ctx: Context) -> bool:
    mana = ctx.target
    return (
        ctx.source is source
        and isinstance(mana, CardInstance)
        and mana.area is AreaType.BLESSING
        and mana in source.blessings
        and state.engine._mana_color_of(mana) is Color.BLUE
    )


def _transform_with_blue_bless(source: CardInstance, state: Any, ctx: Context) -> None:
    mana = ctx.target
    if not isinstance(mana, CardInstance):
        raise RuntimeError(f"{CARD_ID} transformation requires its attached Blue Mana")
    if mana.area is not AreaType.BLESSING or mana not in source.blessings:
        raise RuntimeError(f"{CARD_ID} transformation target is not attached to this Minion")
    engine = state.engine
    if engine._mana_color_of(mana) is not Color.BLUE:
        raise RuntimeError(f"{CARD_ID} transformation received non-Blue Bless Mana")
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
        EffectSpec(
            timing=EffectTiming.ON_SUMMON,
            fn=_look_at_top_three_and_choose,
            condition=_this_orka_was_summoned,
            target_kind="top3_card",
            min_targets=1,
            max_targets=1,
            official_effect="デッキの上から3枚を見て1枚を公開して手札に加え、残りをランダムにデッキの下へ置く",
            official_timing="召喚時",
        ),
        EffectSpec(
            timing=EffectTiming.ON_BLESS,
            fn=_transform_with_blue_bless,
            condition=_this_orka_was_blue_blessed,
            active_areas=(AreaType.FIELD,),
            official_effect="青の加護マナを除外し、荒波王オルカに変形する",
            official_timing="加護時",
        ),
    ]
    return card
