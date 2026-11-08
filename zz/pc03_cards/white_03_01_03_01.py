from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming
from zz.enums import AreaType, CardType
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row

CARD_ID = "white_03_01_03_01"
EVOLUTION_FAMILY = "icy"
EVOLUTION_RACE = "ハンター"
QUALIFYING_RACES = frozenset({"ハンター", "アルカナ"})
EVOLUTION_PAIRS = (
    ("white_00_00_03_01", "white_00_00_03_02"),
    ("white_03_01_03_01", "white_03_01_03_02"),
)


def _own_hand_hunter_summoned(source: CardInstance, state: Any, ctx: Context) -> bool:
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
    if not (movement and movement.get("from") is AreaType.HAND and movement.get("to") is AreaType.FIELD):
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


def _qualifying_ally_attack(source: CardInstance, state: Any, ctx: Context) -> bool:
    attacker = ctx.source
    return (
        source.area is AreaType.FIELD
        and source.owner is ctx.controller
        and state.active is source.owner
        and isinstance(attacker, CardInstance)
        and attacker.area is AreaType.FIELD
        and attacker.owner is source.owner
        and attacker.card.type in (CardType.F_MINION, CardType.B_MINION)
        and bool(QUALIFYING_RACES.intersection(attacker.card.race_jp.split("|")))
    )


def _require_block(source: CardInstance, state: Any, ctx: Context) -> None:
    attacker = ctx.source
    if not isinstance(attacker, CardInstance):
        raise RuntimeError(f"{CARD_ID} attack trigger lost its attacking Minion")
    # The battle-scoped marker is consumed and cleared by the shared combat path.
    attacker.flags.add("battle:must_be_blocked")


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.ability_jp = (
        "【自分のターン】自分の種族「ハンター」または「アルカナ」を持つミニオンがアタックするたび、相手は必ずブロックする。\n"
        "進化：手札から「ハンター」が召喚されたとき「「氷晶の召喚士」アイシー」と"
        "「「アイシーの召喚獣」フリズリー」をLv3にする。"
    )
    card.effects.extend(
        [
            EffectSpec(
                EffectTiming.ON_SUMMON,
                _apply_evolution,
                condition=_own_hand_hunter_summoned,
                params={
                    "pc03_evolution_pairs": EVOLUTION_PAIRS,
                    "pc03_evolution_family": EVOLUTION_FAMILY,
                    "pc03_evolution_race": EVOLUTION_RACE,
                    "pc03_evolution_source_area": AreaType.HAND.name,
                },
                official_effect=(
                    "手札から「ハンター」が召喚されたとき「「氷晶の召喚士」アイシー」と"
                    "「「アイシーの召喚獣」フリズリー」をLv3にする。"
                ),
                official_timing="進化",
                active_areas=(AreaType.FIELD,),
            ),
            EffectSpec(
                EffectTiming.ON_ATTACK,
                _require_block,
                condition=_qualifying_ally_attack,
                params={"battle_scoped_forced_block": True, "qualifying_races": sorted(QUALIFYING_RACES)},
                official_effect="自分の種族「ハンター」または「アルカナ」を持つミニオンがアタックするたび、相手は必ずブロックする。",
                official_timing="自分のターン",
                active_areas=(AreaType.FIELD,),
            ),
        ]
    )
    return card
