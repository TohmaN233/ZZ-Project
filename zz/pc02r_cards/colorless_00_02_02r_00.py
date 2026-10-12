from __future__ import annotations

from typing import Any

from zz.enums import AreaType, CardType
from zz.pc01 import _card_from_row


CARD_ID = "colorless_00_02_02r_00"


def _life_cost_delta_for_this_hand_card(source, target, state: Any) -> int:
    if source is not target or target.area is not AreaType.HAND:
        return 0
    if target.card.type is not CardType.F_MINION:
        return 0
    printed_cost = sum(target.card.cost.values())
    return max(0, target.owner.life - printed_cost)


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.cost_aura = _life_cost_delta_for_this_hand_card
    return card
