from __future__ import annotations

from typing import Any

from zz.enums import AreaType
from zz.model import CardInstance
from zz.pc01 import _card_from_row


CARD_ID = "red_03_02_02c_00"


def _sword_team_aura(
    source: CardInstance,
    target: CardInstance,
    state: Any,
) -> tuple[int, int]:
    if (
        state.active is source.owner
        and target.owner is source.owner
        and target.area is AreaType.FIELD
        and target is not source
        and "ソード" in target.card.race_jp
    ):
        return 100, 0
    return 0, 0


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.aura = _sword_team_aura
    return card
