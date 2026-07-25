from __future__ import annotations

import math
from typing import Any


def encode_card_slot_norm(slot: int | None, *, max_cards: int) -> float:
    if slot is None or int(max_cards) <= 0:
        return 0.0
    bounded_slot = max(0, min(int(slot), int(max_cards) - 1))
    return float(bounded_slot + 1) / float(max_cards)


def decode_card_slot_norm(value: Any, *, max_cards: int) -> int | None:
    if int(max_cards) <= 0:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(numeric) or numeric <= 0.0:
        return None
    slot = int(round(numeric * int(max_cards))) - 1
    if slot < 0:
        return None
    return min(slot, int(max_cards) - 1)
