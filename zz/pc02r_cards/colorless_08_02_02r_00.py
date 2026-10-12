from __future__ import annotations

from typing import Any

from zz.enums import CardType, Keyword
from zz.pc01 import _card_from_row


CARD_ID = 'colorless_08_02_02r_00'


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.keyword_aura = _grant_revenge_to_other_friendly_monsters
    return card


def _grant_revenge_to_other_friendly_monsters(source, target, _state) -> list[Keyword]:
    if (
        target is source
        or target.owner is not source.owner
        or target.card.type not in (CardType.F_MINION, CardType.B_MINION)
        or "モンスター" not in str(target.card.race_jp or "").split("|")
    ):
        return []
    return [Keyword.DEATH_BLOW]
