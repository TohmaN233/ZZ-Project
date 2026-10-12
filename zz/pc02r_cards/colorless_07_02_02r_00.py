from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming
from zz.enums import AreaType
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = 'colorless_07_02_02r_00'
_BOOSTED_ATTACK_FLAG = 'colorless_07_02_02r_00:boosted_attack'


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.effects = list(card.effects) + [
        EffectSpec(
            timing=EffectTiming.ON_SUMMON,
            fn=_refresh_one_resting_mana,
            condition=_this_minion_was_summoned,
            target_kind="ally_base",
            min_targets=1,
            max_targets=1,
            params={"only_rested": True},
            official_effect="自分のマナ1つをアクティブにする",
            official_timing="召喚時",
        ),
        EffectSpec(
            timing=EffectTiming.ON_BLESS,
            fn=_grant_boosted_attack,
            condition=_this_minion_was_boosted,
            active_areas=(AreaType.FIELD,),
            official_effect="このミニオンに、アタック時に相手のBP400以下のミニオン1体を破壊する能力を付与する",
            official_timing="加護時",
        ),
        EffectSpec(
            timing=EffectTiming.ON_ATTACK,
            fn=_destroy_small_enemy_minion,
            condition=_has_boosted_attack,
            target_kind="enemy_minion",
            min_targets=1,
            max_targets=1,
            params={"max_bp": 400},
            official_effect="相手のBP400以下のミニオン1体を破壊する",
            official_timing="アタック時",
        ),
    ]
    return card


def _this_minion_was_summoned(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source


def _refresh_one_resting_mana(source: CardInstance, state: Any, _ctx: Context) -> None:
    targets = state.engine.select_target(
        source.owner,
        "ally_base",
        1,
        1,
        filter_fn=lambda mana: mana.rested,
        source=source,
    )
    if targets:
        state.engine.refresh_target(targets[0])


def _this_minion_was_boosted(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source


def _grant_boosted_attack(source: CardInstance, _state: Any, ctx: Context) -> None:
    if ctx.source is not source:
        raise RuntimeError(f"{CARD_ID} boost trigger resolved for a different minion")
    source.flags.add(_BOOSTED_ATTACK_FLAG)


def _has_boosted_attack(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source and _BOOSTED_ATTACK_FLAG in source.flags


def _destroy_small_enemy_minion(source: CardInstance, state: Any, _ctx: Context) -> None:
    targets = state.engine.select_target(
        source.owner,
        "enemy_minion",
        1,
        1,
        filter_fn=lambda target: state.engine.effective_bp(target) <= 400,
        source=source,
    )
    if targets:
        state.engine.destroy_target(targets[0], source)
