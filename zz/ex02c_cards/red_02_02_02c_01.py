from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming
from zz.enums import AreaType
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "red_02_02_02c_01"


def _this_minion_was_summoned(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source


def _grant_movement_if_black_swordsman_is_present(
    source: CardInstance,
    state: Any,
    _ctx: Context,
) -> None:
    if any("黒の剣士" in ci.card.race_jp.split("|") for ci in source.owner.field):
        state.engine.grant_movement_right(source.owner, 1)


def _grant_movement_for_switch(source: CardInstance, state: Any, ctx: Context) -> None:
    _grant_movement_if_black_swordsman_is_present(source, state, ctx)


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.effects = list(card.effects) + [
        EffectSpec(
            timing=EffectTiming.ON_SUMMON,
            fn=_grant_movement_for_switch,
            condition=_this_minion_was_summoned,
            params={"ex02c_switch_races": ["黒の剣士"]},
            active_areas=(AreaType.FIELD,),
            official_effect="フィールドに自分の種族「黒の剣士」を持つミニオンがいる場合、自分の移動権を1増やす",
            official_timing="召喚時",
            official_condition="スイッチ：「黒の剣士」",
        )
    ]
    return card
