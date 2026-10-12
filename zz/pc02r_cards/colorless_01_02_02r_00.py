from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming
from zz.enums import AreaType, CardType, Color
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "colorless_01_02_02r_00"


def _this_minion_was_summoned(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source


def _colored_zero_dp_nymph_base(card: CardInstance) -> bool:
    return (
        card.card.type is CardType.B_MINION
        and card.card.printed_color is not Color.COLORLESS
        and "ニンフ" in card.card.race_jp
        and card.card.dp == 0
    )


def _search_nymph_base(source: CardInstance, state: Any, _ctx: Context) -> None:
    engine = state.engine
    owner = source.owner
    selected = engine.select_target(
        owner,
        "deck_card",
        0,
        1,
        filter_fn=_colored_zero_dp_nymph_base,
        source=source,
    )
    if not selected:
        return
    if len(selected) != 1 or not _colored_zero_dp_nymph_base(selected[0]):
        raise RuntimeError(f"{CARD_ID} expected one colored DP-0 Nymph Base Minion")
    target = selected[0]
    if target.area is not AreaType.DECK or target not in owner.deck:
        raise RuntimeError(f"{CARD_ID} selected a card outside its owner's Deck")
    owner.deck.remove(target)
    engine.reveal_card(owner, target, "deck_search")
    engine.add_to_hand(owner, target, from_area=AreaType.DECK)
    engine.rng.shuffle(owner.deck)


def _this_minion_retreats(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source


def _rest_when_moved_to_base(source: CardInstance, _state: Any, _ctx: Context) -> None:
    if source.area is not AreaType.BASE:
        raise RuntimeError(f"{CARD_ID} MOVE_TO_BASE resolved outside the Base")
    source.rested = True


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.effects = list(card.effects) + [
        EffectSpec(
            timing=EffectTiming.ON_SUMMON,
            fn=_search_nymph_base,
            condition=_this_minion_was_summoned,
            target_kind="deck_card",
            min_targets=0,
            max_targets=1,
            optional=True,
            params={"card_type": CardType.B_MINION.value, "race": "ニンフ", "max_dp": 0, "exclude_color": Color.COLORLESS},
            official_effect="種族「ニンフ」を持つDP0の有色ベース・ミニオン1枚を公開して手札に加え、デッキをシャッフルできる",
            official_timing="召喚時",
        ),
        EffectSpec(
            timing=EffectTiming.MOVE_TO_BASE,
            fn=_rest_when_moved_to_base,
            condition=_this_minion_retreats,
            active_areas=(AreaType.BASE,),
            official_effect="このミニオンはベースに移動するときレスト状態になる",
            official_timing="後退時",
        ),
    ]
    return card

