from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming, build_effect
from zz.enums import AreaType, CardType
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "blue_05_01_03_01"
EVOLUTION_PAIRS = (
    ("blue_00_00_03_04", "blue_00_00_03_05"),
    ("blue_05_01_03_01", "blue_05_01_03_02"),
)
EVOLUTION_RACE = "マーフォーク"


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


def _own_magic_used(source: CardInstance, _state: Any, ctx: Context) -> bool:
    used = ctx.source
    return (
        source.area is AreaType.FIELD
        and isinstance(used, CardInstance)
        and used.owner is source.owner
        and used.card.type is CardType.MAGIC
        and sum(used.card.cost.values()) >= 3
    )


def _own_attack(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source


def _refresh_after_magic(source: CardInstance, state: Any, _ctx: Context) -> None:
    engine = state.engine
    if engine is None:
        raise RuntimeError(f"{CARD_ID} Magic trigger requires an Engine")
    engine.refresh_target(source)


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.ability_jp = (
        "【アタック時】\n相手のコスト5以下のミニオン1体をレスト状態でベースに移動させる。\n"
        "【常時】\n自分が本来のコストが3以上のマジックを使用するたび、このミニオンをアクティブにする。\n"
        "進化：手札から「マーフォーク」が召喚されたとき"
        "「「魔人の召喚士」ブルーナ」と「「ブルーナの召喚獣」ジャイ」をLv3にする。"
    )
    card.ability_en = (
        "[When Attacking] Move one of your opponent's minions with a cost of 5 or lower into their base in the Rest State.\n"
        "[Passive] Whenever you use a Magic card with an original cost of 3 or higher, this minion enters the Active State.\n"
        "Evolve: When you summon a Merfolk Minion from your hand, "
        "Broona - Conjurer of the Magus and Juy - Of Broona become Lv. 3."
    )
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
                EffectTiming.ON_CARD_USED,
                _refresh_after_magic,
                condition=_own_magic_used,
                official_effect="自分が本来のコストが3以上のマジックを使用するたび、このミニオンをアクティブにする。",
                official_timing="常時",
                active_areas=(AreaType.FIELD,),
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
                official_effect="手札から「マーフォーク」が召喚されたとき「「魔人の召喚士」ブルーナ」と「「ブルーナの召喚獣」ジャイ」をLv3にする。",
                official_timing="進化",
                active_areas=(AreaType.FIELD,),
            ),
        ]
    )
    return card
