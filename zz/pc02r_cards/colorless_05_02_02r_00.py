from __future__ import annotations

from typing import Any

from zz.enums import AreaType, CardType
from zz.model import CardInstance
from zz.pc01 import _card_from_row


CARD_ID = "colorless_05_02_02r_00"


def _loyal_canine_beast_aura(
    source: CardInstance,
    target: CardInstance,
    _state: Any,
) -> tuple[int, int]:
    if source.area is not AreaType.FIELD or target is source:
        return 0, 0
    if target.owner is not source.owner or target.area not in (AreaType.FIELD, AreaType.BASE):
        return 0, 0
    if target.card.type not in (CardType.F_MINION, CardType.B_MINION):
        return 0, 0
    if "ビースト" not in target.card.race_jp:
        return 0, 0
    return 200, 0


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    # Runtime integration must evaluate this callback when computing effective BP/DP.
    card.stat_aura = _loyal_canine_beast_aura
    return card

