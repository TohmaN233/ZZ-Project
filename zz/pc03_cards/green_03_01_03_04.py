from __future__ import annotations

from typing import Any

from zz.enums import AreaType, CardType, Keyword
from zz.model import CardInstance
from zz.pc01 import _card_from_row


CARD_ID = "green_03_01_03_04"


def _reduce_non_arcana_opponent_minion_life_damage(
    source: CardInstance,
    player: Any,
    amount: int,
    damage_source: Any,
    damage_kind: str,
    state: Any,
) -> int:
    if source.area is not AreaType.FIELD or player is not source.owner or state.active is source.owner:
        return amount
    if damage_source is None:
        return max(0, amount - 1) if damage_kind == "minion_dp" else amount
    if (
        not isinstance(damage_source, CardInstance)
        or damage_source.owner is player
        or damage_source.card.type not in (CardType.F_MINION, CardType.B_MINION)
        or "アルカナ" in damage_source.card.race_jp.split("|")
    ):
        return amount
    return max(0, amount - 1)


def _grant_penetrate_to_cost_five_minions(
    source: CardInstance,
    target: CardInstance,
    _state: Any,
) -> list[Keyword]:
    if (
        source.area is AreaType.FIELD
        and target.area is AreaType.FIELD
        and source.owner is target.owner
        and target.card.type in (CardType.F_MINION, CardType.B_MINION)
        and sum(target.card.cost.values()) >= 5
    ):
        return [Keyword.PENETRATE]
    return []


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.life_damage_reducer = _reduce_non_arcana_opponent_minion_life_damage
    card.keywords = [keyword for keyword in card.keywords if keyword is not Keyword.PENETRATE]
    card.keyword_aura = _grant_penetrate_to_cost_five_minions
    return card