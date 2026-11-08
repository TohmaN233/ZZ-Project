from __future__ import annotations

from typing import Any

from zz.enums import AreaType, Color
from zz.model import CardInstance
from zz.pc01 import _card_from_row


CARD_ID = "green_10_01_03_00"


def _cannot_be_selected_by_effect(target: CardInstance, _source: CardInstance | None, _state: Any) -> bool:
    return target.area is not AreaType.FIELD


def _green_mana_dp_aura(source: CardInstance, target: CardInstance, state: Any) -> tuple[int, int]:
    if source is not target or source.area is not AreaType.FIELD:
        return 0, 0
    engine = state.engine
    if engine is None:
        raise RuntimeError(f"{CARD_ID} DP aura requires an Engine")
    green_mana_count = sum(
        1 for mana in source.owner.base
        if engine._mana_color_of(mana) is Color.GREEN
    )
    return 0, green_mana_count


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.effect_targetable = _cannot_be_selected_by_effect
    card.aura = _green_mana_dp_aura
    return card
