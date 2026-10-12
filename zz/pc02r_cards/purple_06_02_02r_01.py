from __future__ import annotations

from typing import Any

from zz.enums import AreaType, CardType
from zz.pc01 import _card_from_row


CARD_ID = "purple_06_02_02r_01"


def _revenge_free_cost_delta(source, target, state) -> int:
    if source is not target or source.area is not AreaType.HAND:
        return 0
    if state.active is not source.owner:
        return 0
    return -sum(
        card.card.type is CardType.F_MINION and card.area is AreaType.TRASH
        for card in source.owner.trash
    )


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.cost_aura = _revenge_free_cost_delta
    return card
