from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming
from zz.enums import AreaType
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = 'colorless_07_01_03_02'


def _has_enemy_force(source: CardInstance, state: Any, ctx: Context) -> bool:
    if ctx.source is not source:
        return False
    engine = state.engine
    if engine is None:
        raise RuntimeError(f"{CARD_ID} summon effect requires an Engine")
    opponent = state.players[1 - state.players.index(source.owner)]
    return any(not force.destroyed for force in opponent.forces)


def _has_no_enemy_force(source: CardInstance, state: Any, ctx: Context) -> bool:
    if ctx.source is not source:
        return False
    engine = state.engine
    if engine is None:
        raise RuntimeError(f"{CARD_ID} summon effect requires an Engine")
    opponent = state.players[1 - state.players.index(source.owner)]
    return not any(not force.destroyed for force in opponent.forces)


def _destroy_enemy_force(source: CardInstance, state: Any, _ctx: Context) -> None:
    engine = state.engine
    if engine is None:
        raise RuntimeError(f"{CARD_ID} summon effect requires an Engine")
    targets = engine.select_target(source.owner, "enemy_force", 1, 1, source=source)
    if len(targets) != 1:
        raise RuntimeError(f"{CARD_ID} expected one selected enemy Force, got {len(targets)}")
    engine.destroy_target(targets[0], source=source)


def _gain_stats_when_no_enemy_force(source: CardInstance, state: Any, _ctx: Context) -> None:
    engine = state.engine
    if engine is None:
        raise RuntimeError(f"{CARD_ID} summon effect requires an Engine")
    engine.modify_stat(source, bp_delta=100, dp_delta=1, duration="permanent")


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.effects.extend((
        EffectSpec(
            EffectTiming.ON_SUMMON,
            _destroy_enemy_force,
            condition=_has_enemy_force,
            target_kind="enemy_force",
            min_targets=1,
            max_targets=1,
            official_effect=(
                "相手のフォース1つを破壊する。破壊するフォースがない場合、"
                "このミニオンにBP+100/DP+1を付与する。"
            ),
            official_timing="召喚時",
            active_areas=(AreaType.FIELD,),
        ),
        EffectSpec(
            EffectTiming.ON_SUMMON,
            _gain_stats_when_no_enemy_force,
            condition=_has_no_enemy_force,
            min_targets=0,
            max_targets=0,
            official_effect=(
                "相手のフォース1つを破壊する。破壊するフォースがない場合、"
                "このミニオンにBP+100/DP+1を付与する。"
            ),
            official_timing="召喚時",
            active_areas=(AreaType.FIELD,),
        ),
    ))
    return card
