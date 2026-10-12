from __future__ import annotations

from typing import Any

from zz.enums import AreaType, CardType
from zz.model import CardInstance, GameState
from zz.pc01 import _card_from_row


CARD_ID = "colorless_04_02_02r_02"
_GOBLIN_QUEEN_ID = "colorless_03_02_01_04"


def _goblin_queen_is_on_field(source: CardInstance) -> bool:
    return any(card.card.id == _GOBLIN_QUEEN_ID for card in source.owner.field)


def _goblin_turn_aura(
    source: CardInstance,
    target: CardInstance,
    state: GameState,
) -> tuple[int, int]:
    if source.area is not AreaType.FIELD or state.active is not source.owner:
        return 0, 0
    if not _goblin_queen_is_on_field(source):
        return 0, 0
    if target.owner is not source.owner or target.area not in (AreaType.FIELD, AreaType.BASE):
        return 0, 0
    if target.card.type not in (CardType.F_MINION, CardType.B_MINION):
        return 0, 0
    if "ゴブリン" not in target.card.race_jp:
        return 0, 0

    # Multiple copies of this non-stacking passive contribute one bonus total.
    sources = [
        card for card in source.owner.field
        if card.area is AreaType.FIELD and card.card.id == CARD_ID
    ]
    if not sources or source is not min(sources, key=lambda card: card.iid):
        return 0, 0
    return 100, 1


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    # Runtime integration must evaluate this callback when computing effective BP/DP.
    card.stat_aura = _goblin_turn_aura
    return card

