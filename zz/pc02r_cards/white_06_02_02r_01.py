from __future__ import annotations

from typing import Any

from zz.enums import AreaType, CardType
from zz.pc01 import _card_from_row


CARD_ID = "white_06_02_02r_01"


def _opponent_field_minion_discount(source, target, state: Any) -> int:
    if source is not target or source.area is not AreaType.HAND or target.area is not AreaType.HAND:
        return 0
    if target.card.type not in (CardType.F_MINION, CardType.B_MINION):
        return 0
    opponent = state.players[1 - state.players.index(source.owner)]
    return -sum(
        1
        for minion in opponent.field
        if minion.card.type in (CardType.F_MINION, CardType.B_MINION)
    )


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.cost_aura = _opponent_field_minion_discount
    return card
