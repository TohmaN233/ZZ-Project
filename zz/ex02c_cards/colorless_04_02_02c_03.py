from __future__ import annotations

from typing import Any

from zz.enums import CardType
from zz.model import CardInstance
from zz.pc01 import _card_from_row


CARD_ID = 'colorless_04_02_02c_03'


def _opponent_magic_cannot_select(
    target: CardInstance,
    source: CardInstance | None,
    _state: Any,
) -> bool:
    return not (
        source is not None
        and source.card.type is CardType.MAGIC
        and source.owner is not target.owner
    )


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.effect_targetable = _opponent_magic_cannot_select
    return card
