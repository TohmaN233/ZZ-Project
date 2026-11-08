from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming
from zz.enums import AreaType, CardType, Color
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "green_03_01_03_03"
EVOLUTION_FAMILY = "yggsil"
EVOLUTION_RACE = "ツリーフォーク"
EVOLUTION_PAIRS = (
    ("green_00_00_03_01", "green_00_00_03_02"),
    ("green_03_01_03_03", "green_03_01_03_04"),
)


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


def _own_hand_treefolk_summoned(source: CardInstance, state: Any, ctx: Context) -> bool:
    summoned = ctx.source
    engine = state.engine
    if engine is None:
        raise RuntimeError(f"{CARD_ID} evolution condition requires an Engine")
    if (
        source.area is not AreaType.FIELD
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
    return engine.can_pc03_evolve(
        player=source.owner,
        family_id=EVOLUTION_FAMILY,
    )


def _reduce_non_arcana_opponent_minion_life_damage(
    source: CardInstance,
    player: Any,
    amount: int,
    damage_source: Any,
    damage_kind: str,
    state: Any,
) -> int:
    if source.area is not AreaType.FIELD or player is not source.owner or state.active is source.owner:
        return amount
    if damage_source is None:
        return max(0, amount - 1) if damage_kind == "minion_dp" else amount
    if (
        not isinstance(damage_source, CardInstance)
        or damage_source.owner is player
        or damage_source.card.type not in (CardType.F_MINION, CardType.B_MINION)
        or "アルカナ" in damage_source.card.race_jp.split("|")
    ):
        return amount
    return max(0, amount - 1)


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.life_damage_reducer = _reduce_non_arcana_opponent_minion_life_damage
    card.effects.append(
        EffectSpec(
            EffectTiming.ON_SUMMON,
            _apply_evolution,
            condition=_own_hand_treefolk_summoned,
            params={
                "pc03_evolution_pairs": EVOLUTION_PAIRS,
                "pc03_evolution_family": EVOLUTION_FAMILY,
                "pc03_evolution_race": EVOLUTION_RACE,
                "pc03_evolution_source_area": AreaType.HAND.name,
            },
            official_effect="手札から「ツリーフォーク」が召喚されたとき「「観測の召喚士」ラバー」と「「ラバーの召喚獣」ユグシル」をLv3にする。",
            official_timing="進化",
            active_areas=(AreaType.FIELD,),
        )
    )
    return card