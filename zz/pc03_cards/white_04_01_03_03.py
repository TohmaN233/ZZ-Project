from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming, build_effect
from zz.enums import AreaType, CardType, Color
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row

CARD_ID = "white_04_01_03_03"
ANDROID_RACE = "アンドロイド"


def _self_transformed(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source and source.area is AreaType.FIELD


def _heal_forces_and_place_white_mana(source: CardInstance, state: Any, _ctx: Context) -> None:
    engine = state.engine
    if engine is None:
        raise RuntimeError(f"{CARD_ID} transform effect requires an Engine")
    for force in source.owner.forces:
        if not force.destroyed:
            engine.heal_target(force, 1)


def _android_bp_aura(source: CardInstance, target: CardInstance, _state: Any) -> tuple[int, int]:
    if source.area is not AreaType.FIELD:
        return 0, 0
    field_sources = [
        instance for instance in source.owner.field
        if instance.area is AreaType.FIELD and instance.card.id == CARD_ID
    ]
    if source not in field_sources:
        raise RuntimeError(f"{CARD_ID} aura source is missing from its owner's Field")
    if source is not min(field_sources, key=lambda instance: instance.iid):
        return 0, 0
    if (
        target.area not in (AreaType.FIELD, AreaType.BASE)
        or source.owner is not target.owner
        or target.card.type not in (CardType.F_MINION, CardType.B_MINION)
        or ANDROID_RACE not in target.card.race_jp.split("|")
    ):
        return 0, 0
    live_forces = any(not force.destroyed for force in source.owner.forces)
    return (200 if live_forces else 100), 0


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.ability_jp = (
        "【変形時】自分のフォース全てを1回復する。白マナ1つをレスト状態でベースに置く。\n"
        "【常時】自分の種族「アンドロイド」を持つミニオン全てをBP+100する。自分のフォースが1つ以上ある場合、"
        "代わりに、自分の種族「アンドロイド」を持つミニオン全てをBP+200する。この効果は重複しない。"
    )
    card.ability_en = (
        "[When Transformed] Restore 1 point to all of your Forces. Place one White Mana into your base in the Rest State.\n"
        "[Passive] All your Android Minions gain +100BP. If you have one or more Forces they gain +200BP instead. This effect cannot stack."
    )
    card.stat_aura = _android_bp_aura
    card.effects.append(
        EffectSpec(
            EffectTiming.ON_TRANSFORM,
            _heal_forces_and_place_white_mana,
            condition=_self_transformed,
            params={"heal_all_owned_forces": 1, "place_mana_color": Color.WHITE.name, "mana_rested": True},
            official_effect="自分のフォース全てを1回復する。白マナ1つをレスト状態でベースに置く。",
            official_timing="変形時",
            active_areas=(AreaType.FIELD,),
        )
    )
    card.effects.append(build_effect(
        "place_colorless_mana", EffectTiming.ON_TRANSFORM,
        condition=_self_transformed, rested=True, mana_color=Color.WHITE,
        official_effect="白マナ1つをレスト状態でベースに置く。",
        official_timing="変形時", active_areas=(AreaType.FIELD,),
    ))
    return card
