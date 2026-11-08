from __future__ import annotations

from typing import Any

from zz.enums import AreaType, CardType
from zz.model import CardInstance
from zz.pc01 import _card_from_row


CARD_ID = "colorless_04_01_03_02"


def _opponent_effect_cannot_select_during_own_turn(
    target: CardInstance,
    source: CardInstance | None,
    state: Any,
) -> bool:
    return not (
        target.area is AreaType.FIELD
        and source is not None
        and source.owner is not target.owner
        and state.active is target.owner
    )


def _evoker_base_minion_aura(source: CardInstance, target: CardInstance, state: Any) -> tuple[int, int]:
    if source is not target or source.area is not AreaType.FIELD:
        return 0, 0
    bonus = sum(
        100
        for mana in source.owner.base
        if mana.card.type is CardType.B_MINION
        and "エヴォーカー" in mana.card.race_jp.split("|")
    )
    return bonus, 0


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.effect_targetable = _opponent_effect_cannot_select_during_own_turn
    card.stat_aura = _evoker_base_minion_aura
    return card
