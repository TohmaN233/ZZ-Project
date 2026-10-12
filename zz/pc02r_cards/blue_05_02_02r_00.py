from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming
from zz.enums import CardType, Color
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "blue_05_02_02r_00"


def _has_blue_dragon(source: CardInstance) -> bool:
    return any(
        ci.card.type in (CardType.B_MINION, CardType.F_MINION)
        and ci.card.printed_color is Color.BLUE
        and "ドラゴン" in ci.card.race_jp
        for ci in source.owner.field
    )


def _selene_summoned_with_blue_dragon(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source and _has_blue_dragon(source)


def _search_magic(source: CardInstance, state: Any, _ctx: Context) -> None:
    engine = state.engine
    chosen = engine.select_target(
        source.owner,
        "deck_card",
        0,
        1,
        filter_fn=lambda target: target.card.type is CardType.MAGIC,
        source=source,
    )
    if not chosen:
        return
    target = chosen[0]
    source.owner.deck.remove(target)
    engine.reveal_card(source.owner, target, "deck_search")
    engine.add_to_hand(source.owner, target, from_area=target.area)
    engine.rng.shuffle(source.owner.deck)


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.effects = list(card.effects) + [
        EffectSpec(
            timing=EffectTiming.ON_SUMMON,
            fn=_search_magic,
            condition=_selene_summoned_with_blue_dragon,
            target_kind="deck_card",
            min_targets=0,
            max_targets=1,
            optional=True,
            params={"card_type": CardType.MAGIC.value},
            official_effect="自分の青のドラゴンがいる場合、デッキからマジック1枚を公開して手札に加え、デッキをシャッフルできる",
            official_timing="召喚時",
        )
    ]
    return card
