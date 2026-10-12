from __future__ import annotations

from typing import Any

from zz.pc01 import _card_from_row


CARD_ID = "red_00_01_02r_00"


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    # This is a granted ability of the blessed host, never an aura from Base.
    # Its lifetime is evaluated by the shared blessing_stat_aura path.
    return _card_from_row(row, infer_effects=False)
