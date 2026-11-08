from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming, build_effect
from zz.enums import AreaType, CardType
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "red_05_01_03_01"
EVOLUTION_FAMILY = "flame_ring"
EVOLUTION_RACE = "ドワーフ"
EVOLUTION_PAIRS = (
    ("red_00_00_03_03", "red_00_00_03_04"),
    ("red_05_01_03_01", "red_05_01_03_02"),
)


def _own_hand_dwarf_summoned(source: CardInstance, state: Any, ctx: Context) -> bool:
    summoned = ctx.source
    engine = state.engine
    if engine is None:
        raise RuntimeError(f"{CARD_ID} evolution condition requires an Engine")
    if (
        source.area is not AreaType.FIELD
        or source.owner is not ctx.controller
        or state.active is not source.owner
        or not isinstance(summoned, CardInstance)
        or summoned.owner is not source.owner
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
    return engine.can_pc03_evolve(player=source.owner, family_id=EVOLUTION_FAMILY)


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


def _self_attacked_with_two_enemies(source: CardInstance, state: Any, ctx: Context) -> bool:
    if ctx.source is not source or source.area is not AreaType.FIELD or state.active is not source.owner:
        return False
    opponent = state.players[1 - state.players.index(source.owner)]
    return sum(
        target.area is AreaType.FIELD
        and target.owner is opponent
        and target.card.type is CardType.F_MINION
        for target in opponent.field
    ) >= 2


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.effects.extend(
        [
            build_effect(
                "stat_modifier",
                EffectTiming.ON_ATTACK,
                condition=_self_attacked_with_two_enemies,
                target_kind="enemy_minion",
                min_targets=2,
                max_targets=2,
                bp_delta=-200,
                duration="permanent",
                official_effect="相手のミニオン2体にBP-200を付与する。",
                official_timing="アタック時",
            ),
            EffectSpec(
                EffectTiming.ON_SUMMON,
                _apply_evolution,
                condition=_own_hand_dwarf_summoned,
                params={
                    "pc03_evolution_pairs": EVOLUTION_PAIRS,
                    "pc03_evolution_family": EVOLUTION_FAMILY,
                    "pc03_evolution_race": EVOLUTION_RACE,
                    "pc03_evolution_source_area": AreaType.HAND.name,
                },
                official_effect="手札から「ドワーフ」が召喚されたとき「「炎石の召喚士」エミリー」と「「エミリーの召喚獣」フレイムリング」をLv2にする。",
                official_timing="進化",
                active_areas=(AreaType.FIELD,),
            ),
        ]
    )
    return card
