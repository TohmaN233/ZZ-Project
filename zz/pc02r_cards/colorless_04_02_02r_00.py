from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming
from zz.enums import AreaType, CardType
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "colorless_04_02_02r_00"


def _this_minion_was_summoned(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source


def _destroy_all_enemy_minions_cost_one_or_less(
    source: CardInstance,
    state: Any,
    _ctx: Context,
) -> None:
    opponent = state.players[1 - state.players.index(source.owner)]
    for target in list(opponent.field):
        if (
            target.area is AreaType.FIELD
            and target.card.type in (CardType.F_MINION, CardType.B_MINION)
            and sum(target.card.cost.values()) <= 1
        ):
            state.engine.destroy_target(target, source)


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.effects = list(card.effects) + [
        EffectSpec(
            timing=EffectTiming.ON_SUMMON,
            fn=_destroy_all_enemy_minions_cost_one_or_less,
            condition=_this_minion_was_summoned,
            params={"max_cost": 1, "all_targets": True},
            official_effect="相手のコスト1以下のミニオン全てを破壊する",
            official_timing="召喚時",
        )
    ]
    return card


