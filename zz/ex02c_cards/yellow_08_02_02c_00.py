from __future__ import annotations

from typing import Any

from zz.pc01 import _card_from_row


CARD_ID = "yellow_08_02_02c_00"


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    return _card_from_row(row, infer_effects=False)
