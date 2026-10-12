from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming, _target_filter
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "colorless_05_02_02r_01"
_TARGET_FILTER_PARAMS = {"requires_blessing": True}


def _this_minion_was_summoned(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source


def _destroy_one_boosted_enemy_minion(source: CardInstance, state: Any, _ctx: Context) -> None:
    matcher = _target_filter(state.engine, **_TARGET_FILTER_PARAMS)
    targets = state.engine.select_target(
        source.owner,
        "enemy_minion",
        1,
        1,
        filter_fn=matcher,
        source=source,
    )
    if not targets:
        return
    if len(targets) != 1 or not matcher(targets[0]):
        raise RuntimeError(f"{CARD_ID} expected one opposing Minion with a Boost")
    state.engine.destroy_target(targets[0], source)


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.effects = list(card.effects) + [
        EffectSpec(
            timing=EffectTiming.ON_SUMMON,
            fn=_destroy_one_boosted_enemy_minion,
            condition=_this_minion_was_summoned,
            target_kind="enemy_minion",
            min_targets=1,
            max_targets=1,
            params=dict(_TARGET_FILTER_PARAMS),
            official_effect="相手の加護が付与されているミニオン1体を破壊する",
            official_timing="召喚時",
        )
    ]
    return card

