from __future__ import annotations

from typing import Any

from zz.effects import EffectTiming, build_effect
from zz.enums import AreaType, CardType
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "yellow_03_02_03_00"


def _has_arcana_minion(source: CardInstance, _state: Any, _ctx: Context) -> bool:
    return source.area is AreaType.RESOLVING and any(
        target.area is AreaType.FIELD
        and target.card.type is CardType.F_MINION
        and "アルカナ" in target.card.race_jp.split("|")
        for target in source.owner.field
    )


def _lacks_arcana_minion(source: CardInstance, _state: Any, _ctx: Context) -> bool:
    return source.area is AreaType.RESOLVING and not any(
        target.area is AreaType.FIELD
        and target.card.type is CardType.F_MINION
        and "アルカナ" in target.card.race_jp.split("|")
        for target in source.owner.field
    )


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.effects.extend(
        [
            build_effect(
                "return_to_hand",
                EffectTiming.ON_CAST_MAGIC,
                condition=_has_arcana_minion,
                target_kind="enemy_minion",
                max_targets=1,
                official_effect="相手のミニオン1体を手札に戻す。",
                official_timing="メイン/フラッシュ",
                official_condition="自分のフィールドに種族「アルカナ」を持つミニオンがある場合",
            ),
            build_effect(
                "return_to_hand",
                EffectTiming.ON_CAST_MAGIC,
                condition=_lacks_arcana_minion,
                target_kind="enemy_minion",
                max_targets=1,
                max_cost=6,
                official_effect="相手のコスト6以下のミニオン1体を手札に戻す。",
                official_timing="メイン/フラッシュ",
                official_condition="自分のフィールドに種族「アルカナ」を持つミニオンがない場合",
            ),
        ]
    )
    return card
