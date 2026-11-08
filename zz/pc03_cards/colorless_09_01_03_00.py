from __future__ import annotations

from typing import Any

from zz.effects import EffectTiming, build_effect
from zz.enums import AreaType, CardType
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = 'colorless_09_01_03_00'


def _own_arcana_present(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return (
        ctx.source is source
        and any(
            minion.card.type is CardType.F_MINION
            and "アルカナ" in minion.card.race_jp.split("|")
            for minion in source.owner.field
        )
    )


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.effects.append(
        build_effect(
            "destroy_targets",
            EffectTiming.ON_SUMMON,
            condition=_own_arcana_present,
            target_kind="enemy_minion_cost_at_most_4",
            max_cost=4,
            all_targets=True,
            official_effect="自分の種族「アルカナ」を持つミニオンがいる場合、相手のコスト4以下のミニオン全てを破壊する。",
            official_timing="召喚時",
            active_areas=(AreaType.FIELD,),
        )
    )
    return card
