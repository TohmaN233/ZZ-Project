from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming
from zz.enums import AreaType, CardType, Keyword
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "green_03_01_03_00"


def _opponent_minion_entered(source: CardInstance, _state: Any, ctx: Context) -> bool:
    entered = ctx.source
    return (
        source.area is AreaType.FIELD
        and isinstance(entered, CardInstance)
        and entered.area is AreaType.FIELD
        and entered.owner is not source.owner
        and entered.card.type in (CardType.F_MINION, CardType.B_MINION)
    )


def _apply_resurge(source: CardInstance, state: Any, ctx: Context) -> None:
    engine = state.engine
    entered = ctx.source
    if engine is None:
        raise RuntimeError(f"{CARD_ID} Resurge requires an Engine")
    if not isinstance(entered, CardInstance):
        raise RuntimeError(f"{CARD_ID} Resurge event has no Minion source")
    engine.modify_stat(entered, bp_delta=-100, duration="turn")


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    if Keyword.REAWAKEN not in card.keywords:
        card.keywords.append(Keyword.REAWAKEN)
    card.effects.append(
        EffectSpec(
            EffectTiming.ON_ENTER_FIELD,
            _apply_resurge,
            condition=_opponent_minion_entered,
            official_effect="相手のミニオンがフィールドに出るたび、このターン中、そのミニオンをBP-100する。",
            official_timing="常時",
            active_areas=(AreaType.FIELD,),
        )
    )
    return card