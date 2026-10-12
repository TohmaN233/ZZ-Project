from __future__ import annotations

from typing import Any

from zz.enums import CardType, Color
from zz.model import CardInstance
from zz.pc01 import _card_from_row


CARD_ID = "green_05_02_02r_00"


def _protect_olivia_and_green_dragons(
    protector: CardInstance,
    target: CardInstance,
    operation: str,
    _state: Any,
) -> bool:
    return (
        operation in {"destroy", "banish"}
        and target.owner is protector.owner
        and (
            target is protector
            or (
                target.card.type in (CardType.F_MINION, CardType.B_MINION)
                and target.card.printed_color is Color.GREEN
                and "ドラゴン" in target.card.race_jp
            )
        )
    )


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.effect_protection = _protect_olivia_and_green_dragons
    return card
