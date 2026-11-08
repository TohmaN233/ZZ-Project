from __future__ import annotations

from typing import Any

from zz.effects import build_effect, EffectTiming
from zz.enums import AreaType, CardType
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "red_05_01_03_00"


def _self_summoned_with_enemy(source: CardInstance, state: Any, ctx: Context) -> bool:
    if ctx.source is not source or source.area is not AreaType.FIELD:
        return False
    opponent = state.players[1 - state.players.index(source.owner)]
    return any(
        target.area is AreaType.FIELD
        and target.owner is opponent
        and target.card.type is CardType.F_MINION
        for target in opponent.field
    )


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.effects.append(
        build_effect(
            "stat_modifier",
            EffectTiming.ON_SUMMON,
            condition=_self_summoned_with_enemy,
            target_kind="enemy_minion",
            bp_delta=-200,
            duration="turn",
            official_effect="このターン中、相手のミニオン1体をBP-200する。",
            official_timing="召喚時",
        )
    )
    return card
