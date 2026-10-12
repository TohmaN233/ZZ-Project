from __future__ import annotations

from typing import Any

from zz.enums import AreaType, CardType
from zz.model import CardInstance, Player
from zz.pc01 import _card_from_row


CARD_ID = "green_04_02_02r_00"


def _reduce_opponent_minion_life_damage(
    source: CardInstance,
    target: Player,
    amount: int,
    damage_source: CardInstance | None,
    damage_kind: str,
    state: Any,
) -> int:
    if (
        source.area is not AreaType.FIELD
        or source not in source.owner.field
        or target is not source.owner
        or state.active is source.owner
        or damage_kind != "minion_dp"
    ):
        return amount
    if damage_source is None:
        return max(0, amount - 1)
    if (
        damage_source.owner is source.owner
        or damage_source.card.type not in (CardType.F_MINION, CardType.B_MINION)
        or sum(damage_source.card.cost.values()) > 5
    ):
        return amount
    return max(0, amount - 1)


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.life_damage_reducer = _reduce_opponent_minion_life_damage
    return card
