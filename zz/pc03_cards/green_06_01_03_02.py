from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming
from zz.enums import AreaType, CardType
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "green_06_01_03_02"
ELF_RACE = "エルフ"


def _self_source(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source


def _own_turn_end(source: CardInstance, state: Any, ctx: Context) -> bool:
    return source.area is AreaType.FIELD and ctx.controller is source.owner and state.active is source.owner


def _rest_and_lock_minion(source: CardInstance, state: Any, _ctx: Context) -> None:
    engine = state.engine
    if engine is None:
        raise RuntimeError(f"{CARD_ID} summon effect requires an Engine")
    targets = engine.select_target(source.owner, "enemy_minion", 1, 1, source=source)
    for target in targets:
        engine.rest_target(target)
        engine.prevent_activation_until_next_standby_end(target)


def _elf_stat_aura(source: CardInstance, target: CardInstance, _state: Any) -> tuple[int, int]:
    if (
        source.area is AreaType.FIELD
        and target.area is AreaType.FIELD
        and source.owner is target.owner
        and target.card.type is CardType.F_MINION
        and ELF_RACE in target.card.race_jp.split("|")
    ):
        return 100, 1
    return 0, 0


def _destroy_lowest_rest_minions(source: CardInstance, state: Any, _ctx: Context) -> None:
    engine = state.engine
    if engine is None:
        raise RuntimeError(f"{CARD_ID} turn-end effect requires an Engine")
    opponent = state.players[1 - state.players.index(source.owner)]
    eligible = [
        target
        for target in opponent.field
        if target.area is AreaType.FIELD
        and target.card.type is CardType.F_MINION
        and target.rested
    ]
    if not eligible:
        return
    lowest_cost = min(sum(target.card.cost.values()) for target in eligible)
    for target in eligible:
        if sum(target.card.cost.values()) == lowest_cost:
            engine.destroy_target(target, source=source)


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.stat_aura = _elf_stat_aura
    card.effects.extend(
        [
            EffectSpec(
                EffectTiming.ON_SUMMON,
                _rest_and_lock_minion,
                condition=_self_source,
                target_kind="enemy_minion",
                official_effect=(
                    "相手のミニオン1体をレストする。そのミニオンは次の相手の"
                    "スタンバイフェイズ終了時までアクティブにならない。"
                ),
                official_timing="召喚時",
                active_areas=(AreaType.FIELD,),
            ),
            EffectSpec(
                EffectTiming.TURN_END,
                _destroy_lowest_rest_minions,
                condition=_own_turn_end,
                official_effect="相手のレスト状態であるミニオンの中で、最もコストの低いミニオン全てを破壊する。",
                official_timing="自分のターン終了時",
                active_areas=(AreaType.FIELD,),
            ),
        ]
    )
    return card
