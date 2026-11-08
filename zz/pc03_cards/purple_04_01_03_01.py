from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming, build_effect
from zz.enums import AreaType, CardType, Color, Keyword
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "purple_04_01_03_01"
SKELETON_RACE = "スケルトン"


def _self_transformed(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source and source.area is AreaType.FIELD


def _summon_skeleton_from_trash_and_place_purple_mana(source: CardInstance, state: Any, _ctx: Context) -> None:
    engine = state.engine
    if engine is None:
        raise RuntimeError(f"{CARD_ID} transform effect requires an Engine")
    targets = engine.select_target(
        source.owner,
        "trash_field_minion",
        1,
        1,
        filter_fn=lambda target: (
            target.card.type is CardType.F_MINION
            and sum(target.card.cost.values()) <= 6
            and SKELETON_RACE in target.card.race_jp.split("|")
        ),
        source=source,
    )
    if targets:
        engine.summon_from_trash(source.owner, targets[0], rested=False)



def _skeleton_revenge_aura(source: CardInstance, target: CardInstance, _state: Any) -> list[Keyword]:
    if (
        source.area is AreaType.FIELD
        and target.area is AreaType.FIELD
        and source.owner is target.owner
        and target.card.type in (CardType.F_MINION, CardType.B_MINION)
        and SKELETON_RACE in target.card.race_jp.split("|")
    ):
        return [Keyword.DEATH_BLOW]
    return []


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.ability_jp = (
        "【変形時】自分のトラッシュにあるコスト6以下の種族「スケルトン」を持つ"
        "フィールド・ミニオンカード1枚を出す。紫マナ1つをレスト状態でベースに置く。\n"
        "【常時】自分の種族「スケルトン」を持つミニオン全てに[奪命]を与える。"
    )
    card.keyword_aura = _skeleton_revenge_aura
    card.effects.append(
        EffectSpec(
            EffectTiming.ON_TRANSFORM,
            _summon_skeleton_from_trash_and_place_purple_mana,
            condition=_self_transformed,
            target_kind="trash_field_minion",
            min_targets=0,
            max_targets=1,
            params={"max_cost": 6, "race": SKELETON_RACE},
            official_effect="自分のトラッシュにあるコスト6以下の種族「スケルトン」を持つフィールド・ミニオンカード1枚を出す。紫マナ1つをレスト状態でベースに置く。",
            official_timing="変形時",
            active_areas=(AreaType.FIELD,),
        )
    )
    card.effects.append(build_effect(
        "place_colorless_mana", EffectTiming.ON_TRANSFORM,
        condition=_self_transformed, rested=True, mana_color=Color.PURPLE,
        official_effect="紫マナ1つをレスト状態でベースに置く。",
        official_timing="変形時", active_areas=(AreaType.FIELD,),
    ))
    return card
