from __future__ import annotations

from typing import Any

from zz.enums import AreaType, CardType
from zz.pc01 import _card_from_row


CARD_ID = "colorless_07_02_02c_02"


def _free_cost_delta(source, target, state) -> int:
    if source is not target or source.area is not AreaType.HAND:
        return 0
    if state.active is not source.owner:
        return 0
    if any(
        card.card.type in (CardType.F_MINION, CardType.B_MINION)
        for card in source.owner.field
    ):
        return 0
    return -3


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.cost_aura = _free_cost_delta
    return card
