from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming
from zz.enums import AreaType, CardType
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "colorless_04_01_03_00"


def _self_source(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source


def _search_evoker_base_minion(source: CardInstance, state: Any, _ctx: Context) -> None:
    engine = state.engine
    if engine is None:
        raise RuntimeError(f"{CARD_ID} search effect requires an Engine")
    if source.area is not AreaType.FIELD:
        raise RuntimeError(f"{CARD_ID} search effect resolved outside the Field")
    selected = engine.select_target(
        source.owner,
        "deck_base_minion",
        0,
        1,
        source=source,
    )
    if len(selected) > 1:
        raise RuntimeError(f"{CARD_ID} search selected more than one card")
    if selected:
        target = selected[0]
        if target not in source.owner.deck or target.card.type is not CardType.B_MINION:
            raise RuntimeError(f"{CARD_ID} search selected an illegal deck target")
        source.owner.deck.remove(target)
        engine.reveal_card(source.owner, target, "deck_search")
        engine.add_to_hand(source.owner, target, from_area=AreaType.DECK)
    engine.rng.shuffle(source.owner.deck)


def _reduce_arcana_free_cost(source: CardInstance, target: CardInstance, state: Any) -> int:
    if source.area is not AreaType.FIELD or state.active is not source.owner:
        return 0
    if target.owner is not source.owner or target.area is not AreaType.HAND:
        return 0
    if target.card.type not in (CardType.F_MINION, CardType.B_MINION):
        return 0
    if "アルカナ" not in target.card.race_jp.split("|"):
        return 0
    return -1


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.effects.append(
        EffectSpec(
            EffectTiming.ON_SUMMON,
            _search_evoker_base_minion,
            condition=_self_source,
            target_kind="deck_base_minion",
            min_targets=0,
            max_targets=1,
            optional=True,
            params={"race": "エヴォーカー", "card_type": CardType.B_MINION},
            official_effect="自分はデッキの中から種族「エヴォーカー」を持つベース・ミニオンカード1枚を公開して手札に加えることができる。その後、自分のデッキをシャッフルする。",
            official_timing="召喚時",
            active_areas=(AreaType.FIELD,),
        )
    )
    card.cost_aura = _reduce_arcana_free_cost
    return card
