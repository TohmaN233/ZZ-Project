from __future__ import annotations

from typing import Any

from zz.model import CardInstance
from zz.enums import Keyword
from zz.pc01 import _card_from_row


CARD_ID = "green_06_02_02r_00"


def _protect_rachic_from_return(
    protector: CardInstance,
    target: CardInstance,
    operation: str,
    _state: Any,
) -> bool:
    return (
        target is protector
        and operation in {"return_to_hand", "return_to_deck"}
    )


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    if Keyword.PENETRATE not in card.keywords:
        card.keywords = list(card.keywords) + [Keyword.PENETRATE]
    card.effect_protection = _protect_rachic_from_return
    return card
