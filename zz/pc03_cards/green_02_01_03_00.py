from __future__ import annotations

from typing import Any

from zz.enums import Color
from zz.pc01 import _card_from_row


CARD_ID = "green_02_01_03_00"
MANA_VALUE_FOR_ARCANA = 2
MANA_VALUE_RACE = "アルカナ"


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.pc03_mana_value_rule = {
        "mana_color": Color.GREEN,
        "value": MANA_VALUE_FOR_ARCANA,
        "target_race": MANA_VALUE_RACE,
    }
    return card