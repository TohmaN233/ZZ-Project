from __future__ import annotations

from typing import Any

from zz.pc01 import _card_from_row


CARD_ID = "red_03_01_03_01"


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    # Shared Engine stat-effect resolution consumes this declarative modifier.
    card.effect_bp_delta_modifier = -100
    return card
