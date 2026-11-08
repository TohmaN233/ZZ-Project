from __future__ import annotations

from typing import Any

from zz.enums import Keyword
from zz.pc01 import _card_from_row


CARD_ID = "red_03_01_03_00"


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    if Keyword.DEATH_BLOW not in card.keywords:
        raise RuntimeError(f"{CARD_ID} Japanese keyword did not produce DEATH_BLOW")
    return card
