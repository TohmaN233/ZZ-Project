from __future__ import annotations

from typing import Any

from zz.enums import AreaType, CardType, Keyword
from zz.pc01 import _card_from_row


CARD_ID = "purple_05_01_03_00"


def _skeleton_giant_bp_aura(source, target, state) -> tuple[int, int]:
    if source is not target or source.area is not AreaType.FIELD:
        return (0, 0)
    opponent = state.players[1 - state.players.index(source.owner)]
    minion_cards = sum(
        1
        for card in opponent.trash
        if card.card.type in (CardType.F_MINION, CardType.B_MINION)
        and not card.card.is_token
    )
    return (400, 0) if minion_cards >= 3 else (0, 0)


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.ability_jp = "【常時】\n相手のトラッシュにミニオンカードが3枚以上ある場合、このミニオンをBP+400する。"
    if Keyword.RUSH not in card.keywords:
        card.keywords.append(Keyword.RUSH)
    card.stat_aura = _skeleton_giant_bp_aura
    return card
