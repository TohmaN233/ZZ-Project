from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming
from zz.enums import AreaType, CardType
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "yellow_03_02_02c_00"


def _other_ally_minion_entered(source: CardInstance, state: Any, ctx: Context) -> bool:
    entered = ctx.source
    return (
        isinstance(entered, CardInstance)
        and entered is not source
        and entered.owner is source.owner
        and entered.area is AreaType.FIELD
        and entered.card.type in (CardType.B_MINION, CardType.F_MINION)
    )


def _buff_all_own_sword_minions(source: CardInstance, state: Any, ctx: Context) -> None:
    for target in list(source.owner.field):
        if "ソード" in target.card.race_jp.split("|"):
            state.engine.modify_stat(target, bp_delta=100, duration="turn")


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.effects.append(
        EffectSpec(
            timing=EffectTiming.ON_ENTER_FIELD,
            fn=_buff_all_own_sword_minions,
            condition=_other_ally_minion_entered,
            official_effect=(
                "他の自分のミニオンがフィールドに出るたび、"
                "このターン中、自分の種族「ソード」を持つミニオン全てをBP+100する。"
            ),
            official_timing="常時",
            active_areas=(AreaType.FIELD,),
        )
    )
    return card
