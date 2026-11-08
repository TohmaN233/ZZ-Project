from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming, build_effect
from zz.enums import AreaType, CardType
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "blue_05_01_03_00"
EVOLUTION_PAIRS = (
    ("blue_00_00_03_03", "blue_00_00_03_04"),
    ("blue_05_01_03_00", "blue_05_01_03_01"),
)
EVOLUTION_RACE = "マーフォーク"


def _own_attack(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source


def _apply_evolution(source: CardInstance, state: Any, ctx: Context) -> None:
    engine = state.engine
    if engine is None:
        raise RuntimeError("PC03 Juy evolution requires an Engine")
    engine.apply_pc03_evolution(
        source=source,
        context=ctx,
        upgrades=EVOLUTION_PAIRS,
        family_id="juy",
    )


def _own_hand_merfolk_summoned(source: CardInstance, state: Any, ctx: Context) -> bool:
    summoned = ctx.source
    engine = state.engine
    if engine is None:
        raise RuntimeError("PC03 Juy evolution condition requires an Engine")
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
    return bool(
        movement
        and movement.get("from") is AreaType.HAND
        and movement.get("to") is AreaType.FIELD
    )


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.effects.extend(
        [
            build_effect(
                "move_to_base_targets",
                EffectTiming.ON_ATTACK,
                target_kind="enemy_minion",
                max_cost=5,
                rested=True,
                condition=_own_attack,
                official_effect="相手のコスト5以下のミニオン1体をレスト状態でベースに移動させる。",
                official_timing="アタック時",
            ),
            EffectSpec(
                EffectTiming.ON_SUMMON,
                _apply_evolution,
                condition=_own_hand_merfolk_summoned,
                params={
                    "pc03_evolution_pairs": EVOLUTION_PAIRS,
                    "pc03_evolution_family": "juy",
                    "pc03_evolution_race": EVOLUTION_RACE,
                    "pc03_evolution_source_area": AreaType.HAND.name,
                },
                official_effect="手札から「マーフォーク」が召喚されたとき「「魔人の召喚士」ブルーナ」と「「ブルーナの召喚獣」ジャイ」をLv2にする。",
                official_timing="進化",
                active_areas=(AreaType.FIELD,),
            ),
        ]
    )
    return card
