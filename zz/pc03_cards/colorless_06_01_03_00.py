from __future__ import annotations

from typing import Any

from zz.enums import AreaType, CardType, Color
from zz.model import CardInstance
from zz.pc01 import _card_from_row


CARD_ID = "colorless_06_01_03_00"


def _neutral_opponent_minion_discount(source: CardInstance, target: CardInstance, state: Any) -> int:
    if source is not target or source.area is not AreaType.HAND or state.active is not source.owner:
        return 0
    if target.card.type is not CardType.F_MINION:
        return 0
    opponent = next(player for player in state.players if player is not source.owner)
    if not any(
        minion.card.type is CardType.F_MINION
        and minion.card.printed_color is Color.COLORLESS
        for minion in opponent.field
    ):
        return 0
    return -2


def _opponent_effect_cannot_select_during_opponent_turn(
    target: CardInstance,
    source: CardInstance | None,
    state: Any,
) -> bool:
    return not (
        target.area is AreaType.FIELD
        and source is not None
        and source.owner is not target.owner
        and state.active is not target.owner
    )


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.cost_aura = _neutral_opponent_minion_discount
    card.effect_targetable = _opponent_effect_cannot_select_during_opponent_turn
    return card
