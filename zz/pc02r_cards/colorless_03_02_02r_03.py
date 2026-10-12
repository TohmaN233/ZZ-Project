from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming
from zz.enums import AreaType
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "colorless_03_02_02r_03"
_MAX_HAND_SELECTION = 9


def _this_minion_was_summoned(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source


def _discard_draw_and_randomly_bottom(
    source: CardInstance,
    state: Any,
    _ctx: Context,
) -> None:
    engine = state.engine
    owner = source.owner
    selected = engine.select_target(
        owner,
        "hand_card",
        0,
        _MAX_HAND_SELECTION,
        source=source,
    )
    if len(selected) > _MAX_HAND_SELECTION:
        raise RuntimeError(f"{CARD_ID} selected more cards than the hand limit")
    if len({card.iid for card in selected}) != len(selected):
        raise RuntimeError(f"{CARD_ID} received duplicate hand selections")
    if any(card not in owner.hand or card.area is not AreaType.HAND for card in selected):
        raise RuntimeError(f"{CARD_ID} selected a card outside its owner's hand")

    for card in selected:
        engine.discard_from_hand(owner, card)
    engine.draw(owner, len(selected))

    # Deck lists draw from the front; append the shuffled cards after drawing to
    # return them in a random order at the bottom.
    engine.rng.shuffle(selected)
    for card in selected:
        if card.area is not AreaType.TRASH or card not in owner.trash:
            raise RuntimeError(f"{CARD_ID} lost a discarded card before returning it")
        owner.trash.remove(card)
        card.area = AreaType.DECK
        owner.deck.append(card)
        engine._record_zone_move(card, AreaType.TRASH, AreaType.DECK)


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.effects = list(card.effects) + [
        EffectSpec(
            timing=EffectTiming.ON_SUMMON,
            fn=_discard_draw_and_randomly_bottom,
            condition=_this_minion_was_summoned,
            target_kind="hand_card",
            min_targets=0,
            max_targets=_MAX_HAND_SELECTION,
            optional=True,
            params={"draw_equal_to_selected": True, "return_discarded_to_deck_bottom": True},
            official_effect="自分の手札を好きな枚数破棄し、同じ枚数を引いた後、破棄したカードをランダムな順番でデッキの下に戻す",
            official_timing="召喚時",
        )
    ]
    return card


