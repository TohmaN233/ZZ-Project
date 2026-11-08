from __future__ import annotations

from typing import Any

from zz.enums import AreaType
from zz.model import CardInstance
from zz.pc01 import _card_from_row


CARD_ID = "colorless_02_01_03_00"
EVOKER_RACE = "エヴォーカー"


def _evoker_base_aura(source: CardInstance, target: CardInstance, _state: Any) -> tuple[int, int]:
    if source.area is not AreaType.FIELD or target is not source:
        return 0, 0
    has_evoker_mana = any(
        mana.area is AreaType.BASE
        and EVOKER_RACE in mana.card.race_jp.split("|")
        for mana in source.owner.base
    )
    return (100, 1) if has_evoker_mana else (0, 0)


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.aura = _evoker_base_aura
    return card
