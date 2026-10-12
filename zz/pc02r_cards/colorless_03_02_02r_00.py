from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming
from zz.enums import CardType
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "colorless_03_02_02r_00"


def _this_minion_was_destroyed(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.target is source


def _destroy_one_enemy_minion_cost_three_or_less(
    source: CardInstance,
    state: Any,
    _ctx: Context,
) -> None:
    engine = state.engine
    targets = engine.select_target(
        source.owner,
        "enemy_minion",
        1,
        1,
        filter_fn=lambda target: sum(target.card.cost.values()) <= 3,
        source=source,
    )
    if not targets:
        return
    if len(targets) != 1 or targets[0].card.type not in (CardType.F_MINION, CardType.B_MINION):
        raise RuntimeError(f"{CARD_ID} expected one opposing Minion costing 3 or less")
    engine.destroy_target(targets[0], source)


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.effects = list(card.effects) + [
        EffectSpec(
            timing=EffectTiming.ON_DESTROY,
            fn=_destroy_one_enemy_minion_cost_three_or_less,
            condition=_this_minion_was_destroyed,
            target_kind="enemy_minion",
            min_targets=1,
            max_targets=1,
            params={"max_cost": 3},
            official_effect="相手のコスト3以下のミニオン1体を破壊する",
            official_timing="破壊時",
        )
    ]
    return card

