from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming, build_effect
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "white_06_02_02r_00"


def _this_minion_was_summoned(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source


def _this_minion_is_attacking(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source


def _gain_bp_for_each_own_force(source: CardInstance, state: Any, _ctx: Context) -> None:
    force_count = sum(1 for force in source.owner.forces if not force.destroyed)
    if force_count:
        state.engine.modify_stat(source, bp_delta=100 * force_count, duration="permanent")


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.effects = list(card.effects) + [
        EffectSpec(
            timing=EffectTiming.ON_SUMMON,
            fn=_gain_bp_for_each_own_force,
            condition=_this_minion_was_summoned,
            official_effect="召喚時、自分のForce1つにつきこのMinionのBPを+100する",
            official_timing="召喚時",
        ),
        build_effect(
            "force_block",
            EffectTiming.ON_ATTACK,
            condition=_this_minion_is_attacking,
            target_kind="enemy_minion",
            min_targets=1,
            max_targets=1,
            choose_target=True,
            only_active=True,
            official_effect="攻撃時、相手のアクティブMinion1体を選び、このバトル中必ずブロックさせる",
            official_timing="攻撃時",
        ),
    ]
    return card
