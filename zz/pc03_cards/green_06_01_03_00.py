from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming
from zz.enums import AreaType, CardType
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "green_06_01_03_00"
ELF_RACE = "エルフ"
EVOLUTION_PAIRS = (
    ("green_00_00_03_03", "green_00_00_03_04"),
    ("green_06_01_03_00", "green_06_01_03_01"),
)


def _self_source(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source


def _own_hand_elf_summoned(source: CardInstance, state: Any, ctx: Context) -> bool:
    summoned = ctx.source
    controller = ctx.controller
    engine = state.engine
    if engine is None:
        raise RuntimeError(f"{CARD_ID} evolution condition requires an Engine")
    if (
        source.area is not AreaType.FIELD
        or source.owner is not controller
        or state.active is not controller
        or not isinstance(summoned, CardInstance)
        or summoned.owner is not controller
        or summoned.area is not AreaType.FIELD
        or summoned.card.type is not CardType.F_MINION
        or ELF_RACE not in summoned.card.race_jp.split("|")
    ):
        return False
    movement = next(
        (event for event in reversed(engine.zone_move_events) if event.get("card") is summoned),
        None,
    )
    return bool(
        movement
        and movement.get("from") is AreaType.HAND
        and movement.get("to") is AreaType.FIELD
    )


def _apply_evolution(source: CardInstance, state: Any, ctx: Context) -> None:
    engine = state.engine
    if engine is None:
        raise RuntimeError(f"{CARD_ID} evolution requires an Engine")
    engine.apply_pc03_evolution(
        source=source,
        context=ctx,
        upgrades=EVOLUTION_PAIRS,
        family_id="ove",
    )


def _rest_and_lock_minion(source: CardInstance, state: Any, _ctx: Context) -> None:
    engine = state.engine
    if engine is None:
        raise RuntimeError(f"{CARD_ID} summon effect requires an Engine")
    targets = engine.select_target(source.owner, "enemy_minion", 1, 1, source=source)
    for target in targets:
        engine.rest_target(target)
        engine.prevent_activation_until_next_standby_end(target)


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
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
                EffectTiming.ON_SUMMON,
                _apply_evolution,
                condition=_own_hand_elf_summoned,
                params={
                    "pc03_evolution_pairs": EVOLUTION_PAIRS,
                    "pc03_evolution_family": "ove",
                    "pc03_evolution_race": ELF_RACE,
                    "pc03_evolution_source_area": AreaType.HAND.name,
                },
                official_effect=(
                    "手札から「エルフ」が召喚されたとき"
                    "「「深森の召喚士」オーブ」と「「オーブの召喚獣」ムーンクイーン」をLv2にする。"
                ),
                official_timing="進化",
                active_areas=(AreaType.FIELD,),
            ),
        ]
    )
    return card
