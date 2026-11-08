from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming
from zz.enums import AreaType, CardType
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "red_02_01_03_01"
EVOLUTION_FAMILY = "red_spider"
EVOLUTION_RACE = "ゴレイム"
EVOLUTION_PAIRS = (
    ("red_00_00_03_00", "red_00_00_03_01"),
    ("red_02_01_03_01", "red_02_01_03_02"),
)


def _own_hand_golem_summoned(source: CardInstance, state: Any, ctx: Context) -> bool:
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
    if not (
        movement
        and movement.get("from") is AreaType.HAND
        and movement.get("to") is AreaType.FIELD
    ):
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


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.effects.append(
        EffectSpec(
            EffectTiming.ON_SUMMON,
            _apply_evolution,
            condition=_own_hand_golem_summoned,
            params={
                "pc03_evolution_pairs": EVOLUTION_PAIRS,
                "pc03_evolution_family": EVOLUTION_FAMILY,
                "pc03_evolution_race": EVOLUTION_RACE,
                "pc03_evolution_source_area": AreaType.HAND.name,
            },
            official_effect="手札から「ゴレイム」が召喚されたとき「「火蜘蛛の召喚士」ロック」と「「ロックの召喚獣」レッドスパイダー」をLv2にする。",
            official_timing="進化",
            active_areas=(AreaType.FIELD,),
        )
    )
    return card
