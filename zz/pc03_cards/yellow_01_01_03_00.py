from __future__ import annotations
from typing import Any
from zz.effects import EffectSpec, EffectTiming, build_effect
from zz.enums import AreaType, CardType, Color
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row

CARD_ID = "yellow_01_01_03_00"

def _has_evoker_mana(source: CardInstance, state: Any, ctx: Context) -> bool:
    if ctx.source is not source or source.area is not AreaType.FIELD or not source.owner.deck:
        return False
    engine = state.engine
    if engine is None:
        raise RuntimeError(f"{CARD_ID} deck-look condition requires an Engine")
    return any(m.card.type is CardType.B_MINION and
        engine._mana_color_of(m) in (Color.YELLOW, Color.COLORLESS) and
        "エヴォーカー" in m.card.race_jp for m in source.owner.base)

def _look_top(source: CardInstance, state: Any, _ctx: Context) -> None:
    engine = state.engine
    if engine is None:
        raise RuntimeError(f"{CARD_ID} deck-look effect requires an Engine")
    owner = source.owner
    if not owner.deck:
        raise RuntimeError(f"{CARD_ID} deck became empty after its look condition")
    selected = engine.select_target(owner, "top1_card", 1, 1, source=source)
    if len(selected) != 1 or owner.deck[0] is not selected[0]:
        raise RuntimeError(f"{CARD_ID} expected the current top card")
    candidate = selected[0]
    if candidate.card.type in (CardType.B_MINION, CardType.F_MINION) and engine._card_color(candidate.card) is Color.YELLOW:
        owner.deck.remove(candidate)
        engine.reveal_card(owner, candidate, "deck_search")
        engine.add_to_hand(owner, candidate, from_area=AreaType.DECK)
    else:
        owner.deck.remove(candidate)
        owner.deck.append(candidate)

def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.effects.extend([
        EffectSpec(EffectTiming.ON_SUMMON, _look_top, condition=_has_evoker_mana,
            target_kind="top1_card", min_targets=1, max_targets=1,
            official_effect="自分の種族「エヴォーカー」を持つ、黄または無色のマナがある場合、自分のデッキを上から1枚見る。黄のミニオンカードの場合、公開して手札に加える。それ以外の場合、デッキの下に戻す。",
            official_timing="召喚時", official_condition="自分の種族「エヴォーカー」を持つ、黄または無色のマナがある場合",
            active_areas=(AreaType.FIELD,)),
        build_effect("move_to_base_rested", EffectTiming.MOVE_TO_BASE,
            official_effect="このミニオンはベースに移動するとき、レスト状態で移動する。",
            official_timing="常時"),
    ])
    return card
