from __future__ import annotations

from typing import Any

from zz.effects import EffectTiming, build_effect
from zz.enums import AreaType, CardType, Color
from zz.model import Context
from zz.pc01 import _card_from_row


CARD_ID = "purple_04_02_03_00"
ARCANA_RACE = "アルカナ"


def _self_cast(source, _state: Any, ctx: Context) -> bool:
    return ctx.source is source


def _has_own_arcana(source, _state: Any, ctx: Context) -> bool:
    return ctx.source is source and any(
        minion.area is AreaType.FIELD
        and minion.owner is source.owner
        and minion.card.type in (CardType.F_MINION, CardType.B_MINION)
        and ARCANA_RACE in minion.card.race_jp.split("|")
        for minion in source.owner.field
    )


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.effects.extend(
        [
            build_effect(
                "destroy_targets",
                EffectTiming.ON_CAST_MAGIC,
                condition=_self_cast,
                target_kind="enemy_minion",
                max_cost=6,
                official_effect="相手のコスト6以下のミニオン1体を破壊する。",
                official_timing="メイン/フラッシュ",
            ),
            build_effect(
                "return_from_trash_to_hand",
                EffectTiming.ON_CAST_MAGIC,
                condition=_has_own_arcana,
                target_kind="trash_minion",
                color=Color.PURPLE,
                official_effect="自分の種族「アルカナ」を持つミニオンがいる場合、さらに、自分のトラッシュにある紫のミニオンカード1枚を手札に戻す。",
                official_timing="メイン/フラッシュ",
            ),
        ]
    )
    return card
