from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming, build_effect
from zz.enums import AreaType, CardType
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "purple_05_01_03_04"
SKELETON_RACE = "スケルトン"


def _self_summoned(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source and source.area is AreaType.FIELD


def _opponent_minion_destroyed(source: CardInstance, _state: Any, ctx: Context) -> bool:
    destroyed = ctx.target
    return (
        source.area is AreaType.FIELD
        and isinstance(destroyed, CardInstance)
        and destroyed.owner is not source.owner
        and destroyed.card.type in (CardType.F_MINION, CardType.B_MINION)
        and destroyed.area is AreaType.TRASH
    )


def _gain_bp_dp(source: CardInstance, state: Any, _ctx: Context) -> None:
    engine = state.engine
    if engine is None:
        raise RuntimeError(f"{CARD_ID} passive effect requires an Engine")
    engine.modify_stat(source, bp_delta=100, dp_delta=1, duration="permanent")


def _self_attacked(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source and source.area is AreaType.FIELD


def _sacrifice_skeleton_then_destroy_enemy(source: CardInstance, state: Any, _ctx: Context) -> None:
    engine = state.engine
    if engine is None:
        raise RuntimeError(f"{CARD_ID} attack effect requires an Engine")
    skeletons = engine.select_target(
        source.owner,
        "ally_minion",
        0,
        1,
        filter_fn=lambda target: target.card.type in (CardType.F_MINION, CardType.B_MINION)
        and SKELETON_RACE in target.card.race_jp.split("|"),
        source=source,
    )
    if not skeletons:
        return
    sacrificed = skeletons[0]
    engine.destroy_target(sacrificed, source=source)
    if sacrificed in source.owner.field:
        return
    enemies = engine.select_target(source.owner, "enemy_minion", 1, 1, source=source)
    if enemies:
        engine.destroy_target(enemies[0], source=source)


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.ability_jp = (
        "【召喚時】相手のコスト4以下のミニオン1体を破壊する。\n"
        "【常時】相手のミニオンが破壊されるたび、このミニオンにBP+100/DP+1を付与する。\n"
        "【アタック時】自分の種族「スケルトン」を持つミニオン1体を破壊できる。"
        "そうした場合、相手のミニオン1体を破壊する。"
    )
    card.ability_en = (
        "[When Summoned] Destroy one of your opponent's minions with a cost of 4 or lower.\n"
        "[Passive] Whenever one of your opponent's minions is destroyed this minion receives +100BP/+1DP.\n"
        "[When Attacking] You can destroy one of your minions belonging to the Skeleton class. "
        "If you do, destroy one of your opponent's minions."
    )
    card.effects.extend(
        [
            build_effect(
                "destroy_targets",
                EffectTiming.ON_SUMMON,
                condition=_self_summoned,
                target_kind="enemy_minion_cost_at_most_4",
                max_cost=4,
                official_effect="相手のコスト4以下のミニオン1体を破壊する。",
                official_timing="召喚時",
            ),
            EffectSpec(
                EffectTiming.ON_DESTROY,
                _gain_bp_dp,
                condition=_opponent_minion_destroyed,
                official_effect="相手のミニオンが破壊されるたび、このミニオンにBP+100/DP+1を付与する。",
                official_timing="常時",
                active_areas=(AreaType.FIELD,),
            ),
            EffectSpec(
                EffectTiming.ON_ATTACK,
                _sacrifice_skeleton_then_destroy_enemy,
                condition=_self_attacked,
                target_kind="ally_minion",
                min_targets=0,
                max_targets=1,
                optional=True,
                params={"race": SKELETON_RACE, "protection_operation": "destroy", "followup_target_kind": "enemy_minion"},
                official_effect="自分の種族「スケルトン」を持つミニオン1体を破壊できる。そうした場合、相手のミニオン1体を破壊する。",
                official_timing="アタック時",
                active_areas=(AreaType.FIELD,),
            ),
        ]
    )
    return card
