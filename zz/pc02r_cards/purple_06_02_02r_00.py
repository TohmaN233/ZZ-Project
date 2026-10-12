from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming
from zz.enums import AreaType, CardType
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "purple_06_02_02r_00"


def _self_summoned(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source


def _receives_bp_reduction(target: CardInstance) -> bool:
    if target.area is not AreaType.FIELD:
        return False
    if target.card.type not in (CardType.F_MINION, CardType.B_MINION):
        return False
    race = target.card.race_jp or ""
    return "ドラゴン" not in race and "ヒューマノイド" not in race


def _reduce_non_dragon_humanoid_minions(source: CardInstance, state: Any, _ctx: Context) -> None:
    engine = state.engine
    for player in state.players:
        for target in list(player.field):
            if _receives_bp_reduction(target):
                engine.modify_stat(target, bp_delta=-200, duration="permanent")


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.effects = list(card.effects) + [
        EffectSpec(
            timing=EffectTiming.ON_SUMMON,
            fn=_reduce_non_dragon_humanoid_minions,
            condition=_self_summoned,
            official_effect="種族がドラゴンまたはヒューマノイドでない全ミニオンにBP-200を付与する",
            official_timing="召喚時",
        )
    ]
    return card
