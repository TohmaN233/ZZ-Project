from __future__ import annotations

from typing import Any

from zz.effects import EffectTiming, build_effect
from zz.enums import AreaType, CardType
from zz.model import CardInstance
from zz.pc01 import _card_from_row


CARD_ID = "green_04_02_03_00"
ARCANA_RACE = "アルカナ"


def _flash_timing_condition(player: Any, _state: Any, source: CardInstance) -> bool:
    if source.owner is not player:
        return False
    return any(
        minion.area is AreaType.FIELD
        and minion.owner is player
        and minion.card.type is CardType.F_MINION
        and ARCANA_RACE in minion.card.race_jp.split("|")
        for minion in player.field
    )


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.main_timing_ok = True
    card.flash_timing_ok = True
    card.flash_timing_condition = _flash_timing_condition
    card.effects.append(
        build_effect(
            "destroy_targets",
            EffectTiming.ON_CAST_MAGIC,
            target_kind="enemy_minion",
            only_rested=True,
            official_effect="相手のレスト状態であるミニオン1体を破壊する。",
            official_timing="メイン／フラッシュ",
        )
    )
    return card
