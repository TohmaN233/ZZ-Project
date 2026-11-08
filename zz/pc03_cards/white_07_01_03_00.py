from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming
from zz.enums import AreaType, CardType
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row

CARD_ID = "white_07_01_03_00"
EVOLUTION_FAMILY = "metallic_steed"
EVOLUTION_RACE = "アンドロイド"
EVOLUTION_PAIRS = (
    ("white_00_00_03_03", "white_00_00_03_04"),
    ("white_07_01_03_00", "white_07_01_03_01"),
)
ABILITY_JP = (
    "【召喚時】\n"
    "最もライフが多い自分のフォースのライフ1毎に、相手のミニオン全てにBP-100を付与する。\n"
    "進化：手札から「アンドロイド」が召喚されたとき\n"
    "「「機馬の召喚士」サラ」と「「サラの召喚獣」メタリック・スティード」をLv2にする。"
)
ABILITY_EN = (
    "For every point your Force with the highest point value has, deal -100BP to all your opponent's minions.\n"
    "Evolve: Summon minion from the Android class "
    "\"Serah - Conjurer of the Metallic Steed Lv.1\" and "
    "\"Chrome Charger - Of Serah Lv.1\" become Lv.2."
)


def _self_summoned(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source and source.area is AreaType.FIELD


def _reduce_opponent_minions_by_highest_force_life(
    source: CardInstance, state: Any, _ctx: Context
) -> None:
    engine = state.engine
    if engine is None:
        raise RuntimeError(f"{CARD_ID} summon effect requires an Engine")
    living_force_lives = [
        force.life for force in source.owner.forces if not force.destroyed
    ]
    if not living_force_lives:
        raise RuntimeError(f"{CARD_ID} summon effect requires a living Force")
    amount = max(living_force_lives) * 100
    opponent = state.players[1 - state.players.index(source.owner)]
    for target in list(opponent.field):
        if target.card.type not in (CardType.F_MINION, CardType.B_MINION):
            continue
        engine.modify_stat(target, bp_delta=-amount, duration="turn")


def _own_hand_android_summoned(
    source: CardInstance, state: Any, ctx: Context
) -> bool:
    engine = state.engine
    if engine is None:
        raise RuntimeError(f"{CARD_ID} evolution condition requires an Engine")
    controller = ctx.controller
    summoned = ctx.source
    if (
        source.area is not AreaType.FIELD
        or source.owner is not controller
        or state.active is not controller
        or not isinstance(summoned, CardInstance)
        or summoned.owner is not controller
        or summoned.area is not AreaType.FIELD
        or summoned.card.type is not CardType.F_MINION
        or EVOLUTION_RACE not in summoned.card.race_jp.split("|")
    ):
        return False
    movement = next(
        (event for event in reversed(engine.zone_move_events) if event.get("card") is summoned),
        None,
    )
    if not (
        movement
        and movement.get("from") is AreaType.HAND
        and movement.get("to") is AreaType.FIELD
    ):
        return False
    return engine.can_pc03_evolve(player=controller, family_id=EVOLUTION_FAMILY)


def _apply_evolution(source: CardInstance, state: Any, ctx: Context) -> None:
    engine = state.engine
    if engine is None:
        raise RuntimeError(f"{CARD_ID} evolution requires an Engine")
    engine.apply_pc03_evolution(
        source=source,
        context=ctx,
        upgrades=EVOLUTION_PAIRS,
        family_id=EVOLUTION_FAMILY,
    )


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.ability_jp = ABILITY_JP
    card.ability_en = ABILITY_EN
    card.effects.extend(
        [
            EffectSpec(
                EffectTiming.ON_SUMMON,
                _reduce_opponent_minions_by_highest_force_life,
                condition=_self_summoned,
                official_effect=(
                    "最もライフが多い自分のフォースのライフ1毎に、"
                    "相手のミニオン全てにBP-100を付与する。"
                ),
                official_timing="召喚時",
                active_areas=(AreaType.FIELD,),
            ),
            EffectSpec(
                EffectTiming.ON_SUMMON,
                _apply_evolution,
                condition=_own_hand_android_summoned,
                params={
                    "pc03_evolution_pairs": EVOLUTION_PAIRS,
                    "pc03_evolution_family": EVOLUTION_FAMILY,
                    "pc03_evolution_race": EVOLUTION_RACE,
                    "pc03_evolution_source_area": AreaType.HAND.name,
                },
                official_effect=(
                    "手札から「アンドロイド」が召喚されたとき"
                    "「「機馬の召喚士」サラ」と"
                    "「「サラの召喚獣」メタリック・スティード」をLv2にする。"
                ),
                official_timing="進化",
                active_areas=(AreaType.FIELD,),
            ),
        ]
    )
    return card
