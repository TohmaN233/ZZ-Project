from __future__ import annotations

from copy import copy
from typing import Any

from zz.effects import EffectSpec, EffectTiming
from zz.model import Context
from zz.pc01 import _card_from_row


CARD_ID = "purple_03_02_02r_00"


def _self_blessed(source, state, ctx: Context) -> bool:
    return ctx.source is source


def _destroy_one_enemy_minion_cost_6_or_less(source, state, ctx: Context) -> None:
    engine = state.engine
    targets = engine.select_target(
        source.owner,
        "enemy_minion",
        1,
        1,
        filter_fn=lambda target: sum(target.card.cost.values()) <= 6,
        source=source,
    )
    if targets:
        engine.destroy_target(targets[0], source)


def _grant_destroy_ability(source, state, ctx: Context) -> None:
    learned = any(
        effect.params.get("learned_by") == CARD_ID
        for effect in source.card.effects
        if isinstance(effect, EffectSpec)
    )
    if learned:
        return
    card = copy(source.card)
    card.effects = list(source.card.effects)
    card.effects.append(
        EffectSpec(
            timing=EffectTiming.ON_DESTROY,
            fn=_destroy_one_enemy_minion_cost_6_or_less,
            target_kind="enemy_minion",
            min_targets=1,
            max_targets=1,
            params={"max_cost": 6, "learned_by": CARD_ID},
            official_effect="相手のコスト6以下のミニオン1体を破壊する",
            official_timing="破壊時",
        )
    )
    source.card = card


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.effects.append(
        EffectSpec(
            timing=EffectTiming.ON_BLESS,
            fn=_grant_destroy_ability,
            condition=_self_blessed,
            official_effect="このミニオンにコスト6以下の相手ミニオンを破壊する能力を付与する",
            official_timing="加護時",
        )
    )
    return card
