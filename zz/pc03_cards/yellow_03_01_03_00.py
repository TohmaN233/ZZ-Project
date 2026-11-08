from __future__ import annotations
from typing import Any
from zz.enums import AreaType, CardType
from zz.model import CardInstance
from zz.pc01 import _card_from_row

CARD_ID = "yellow_03_01_03_00"

def _reduce_chimera_free_cost(source: CardInstance, target: CardInstance, state: Any) -> int:
    if source.area is not AreaType.FIELD or state.active is not source.owner or target.owner is not source.owner or target.area is not AreaType.HAND or target.card.type is not CardType.F_MINION or "キマイラ" not in target.card.race_jp.split("|"):
        return 0
    return -2

def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.ability_jp = "【常時】自分の手札にある種族「キマイラ」を持つフィールド・ミニオンカードのフリーコストを2減らす。"
    card.ability_en = "[Passive] Reduce the Free Cost of Field Minions belonging to the Chimera class in your hand by 2."
    card.cost_aura = _reduce_chimera_free_cost
    return card
