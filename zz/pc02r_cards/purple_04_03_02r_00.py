from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming
from zz.enums import CardType
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "purple_04_03_02r_00"


def _self_cast(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source


def _destroy_one_ally_and_matching_opponents(
    source: CardInstance,
    state: Any,
    _ctx: Context,
) -> None:
    engine = state.engine
    targets = engine.select_target(source.owner, "ally_minion", 1, 1, source=source)
    if len(targets) != 1:
        raise RuntimeError(f"{CARD_ID} requires one allied minion to destroy")
    sacrificed = targets[0]
    sacrificed_cost = sum(sacrificed.card.cost.values())
    engine.destroy_target(sacrificed, source)

    opponent = state.players[1 - state.players.index(source.owner)]
    for target in list(opponent.field):
        if (
            target.card.type in (CardType.F_MINION, CardType.B_MINION)
            and sum(target.card.cost.values()) == sacrificed_cost
        ):
            engine.destroy_target(target, source)


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.main_timing_ok = True
    card.flash_timing_ok = True
    card.effects = list(card.effects) + [
        EffectSpec(
            timing=EffectTiming.ON_CAST_MAGIC,
            fn=_destroy_one_ally_and_matching_opponents,
            condition=_self_cast,
            target_kind="ally_minion",
            min_targets=1,
            max_targets=1,
            official_effect="自分のミニオン1体を破壊し、そのコストと同じコストの相手ミニオン全てを破壊する",
            official_timing="メイン/フラッシュ",
        )
    ]
    return card
