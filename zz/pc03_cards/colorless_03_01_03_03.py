from __future__ import annotations

from typing import Any

from zz.enums import AreaType
from zz.model import CardInstance
from zz.pc01 import _card_from_row


CARD_ID = "colorless_03_01_03_03"


def _mana_cannot_refresh_outside_standby(
    source: CardInstance,
    target: Any,
    action: str,
    state: Any,
) -> bool:
    if source.card.id != CARD_ID or source.area is not AreaType.FIELD or action != "refresh":
        return False
    if not isinstance(target, CardInstance) or target.area not in (AreaType.BASE, AreaType.BLESSING):
        return False
    engine = state.engine
    if engine is None:
        raise RuntimeError(f"{CARD_ID} refresh restriction requires an Engine")
    return not engine.has_pending_standby


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.action_restriction = _mana_cannot_refresh_outside_standby
    return card
