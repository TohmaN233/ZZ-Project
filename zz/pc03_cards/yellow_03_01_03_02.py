from __future__ import annotations
from typing import Any
from zz.effects import EffectSpec, EffectTiming
from zz.enums import AreaType, CardType, Color
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row

CARD_ID = "yellow_03_01_03_02"
TRANSFORMED_CARD_ID = "yellow_03_01_03_03"
_TYPES = (CardType.B_MINION, CardType.F_MINION)

def _self_summoned(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source and source.area is AreaType.FIELD

def _look_top_three(source: CardInstance, state: Any, _ctx: Context) -> None:
    engine = state.engine
    if engine is None:
        raise RuntimeError(f"{CARD_ID} deck-look effect requires an Engine")
    owner = source.owner
    window = list(owner.deck[:3])
    if not window:
        raise RuntimeError(f"{CARD_ID} summon look started with an empty deck")
    selected = engine.select_target(owner, "top3_card", 0, 1, source=source)
    if len(selected) > 1:
        raise RuntimeError(f"{CARD_ID} selected more than one card")
    chosen = selected[0] if selected else None
    if chosen is not None:
        if chosen not in window or chosen.card.type not in _TYPES or engine._card_color(chosen.card) is not Color.YELLOW:
            raise RuntimeError(f"{CARD_ID} selection violated the declared Yellow Minion filter")
        owner.deck.remove(chosen)
        engine.reveal_card(owner, chosen, "top_cards")
        engine.add_to_hand(owner, chosen, from_area=AreaType.DECK)
    remaining = [c for c in window if c is not chosen]
    for candidate in remaining:
        if candidate not in owner.deck:
            raise RuntimeError(f"{CARD_ID} top-three window changed during selection")
        owner.deck.remove(candidate)
    engine.rng.shuffle(remaining)
    owner.deck.extend(remaining)

def _received_yellow_bless(source: CardInstance, state: Any, ctx: Context) -> bool:
    mana = ctx.target
    engine = state.engine
    if engine is None:
        raise RuntimeError(f"{CARD_ID} Bless transformation requires an Engine")
    return ctx.source is source and source.area is AreaType.FIELD and isinstance(mana, CardInstance) and mana.area is AreaType.BLESSING and mana in source.blessings and engine._mana_color_of(mana) is Color.YELLOW

def _transform(source: CardInstance, state: Any, ctx: Context) -> None:
    engine = state.engine
    mana = ctx.target
    if engine is None:
        raise RuntimeError(f"{CARD_ID} transformation requires an Engine")
    if not isinstance(mana, CardInstance) or mana.area is not AreaType.BLESSING or mana not in source.blessings or engine._mana_color_of(mana) is not Color.YELLOW:
        raise RuntimeError(f"{CARD_ID} transformation requires its attached Yellow Bless Mana")
    from copy import copy
    from zz.cards import CARD_REGISTRY
    from zz.transformations import transformation_target_id
    target_id = transformation_target_id(CARD_ID, TRANSFORMED_CARD_ID)
    try:
        transformed = copy(CARD_REGISTRY[target_id])
    except KeyError as exc:
        raise RuntimeError(f"{CARD_ID} transformed face is not registered: {target_id}") from exc
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
    card.ability_jp = "【召喚時】自分のデッキを上から3枚見て、その中の黄のミニオンカード1枚を公開して手札に加える。残りをランダムにデッキの下に戻す。\n【常時】このミニオンがアクティブ状態でなければ［加護］は付与されない。\n【加護時】黄の加護である場合、加護しているマナを除外して、「「隠密の忍者」サスケ」に変形する。"
    card.ability_en = "[When Summoned] Look at the top three cards of your deck and add one Yellow Minion to your hand. Reveal it, then put the rest on the bottom of your deck in random order. [Passive] This Minion cannot receive Bless while Rested. [When Blessed] If the Bless Mana is Yellow, banish it and transform this card into Sasuke - Undercover Shinobi."
    card.can_bless_while_rested = False
    card.effects.extend([
        EffectSpec(EffectTiming.ON_SUMMON, _look_top_three, condition=_self_summoned,
            target_kind="top3_card", min_targets=1, max_targets=1,
            params={"color": Color.YELLOW, "exclude_tokens": True, "card_types": _TYPES},
            official_effect="自分のデッキを上から3枚見て、その中の黄のミニオンカード1枚を公開して手札に加える。残りをランダムにデッキの下に戻す。",
            official_timing="召喚時", active_areas=(AreaType.FIELD,)),
        EffectSpec(EffectTiming.ON_BLESS, _transform, condition=_received_yellow_bless,
            official_effect="黄の加護である場合、加護しているマナを除外して、「「隠密の忍者」サスケ」に変形する。",
            official_timing="加護時", active_areas=(AreaType.FIELD,)),
    ])
    return card
