from __future__ import annotations

from typing import Any

from zz.enums import Keyword
from zz.pc01 import _card_from_row


CARD_ID = "purple_00_01_02r_00"


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    if Keyword.KAGO not in card.keywords:
        card.keywords = list(card.keywords) + [Keyword.KAGO]
    # The Boost suppresses a Force's own destroy callback before ON_DAMAGE_FORCE
    # is emitted. That interception belongs to the shared Engine damage path.
    return card
