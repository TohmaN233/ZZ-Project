from __future__ import annotations

from copy import copy
from typing import Any

from zz.cards import CARD_REGISTRY
from zz.effects import EffectSpec, EffectTiming
from zz.enums import AreaType, Color
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row
from zz.transformations import transformation_target_id


CARD_ID = "green_08_02_02c_00"
TRANSFORMED_CARD_ID = "green_08_02_02c_01"


def _self_source(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source or getattr(ctx, "switch_source", None) is source


def _rest_for_each_green_minion(source: CardInstance, state: Any, _ctx: Context) -> None:
    engine = state.engine
    own_green_count = sum(
        minion.area is AreaType.FIELD and engine._card_color(minion.card) is Color.GREEN
        for minion in source.owner.field
    )
    legal_targets = engine._eligible_targets(source.owner, "enemy_minion", source=source)
    target_count = min(own_green_count, len(legal_targets))
    if target_count == 0:
        return
    targets = engine.select_target(
        source.owner,
        "enemy_minion",
        target_count,
        target_count,
        source=source,
    )
    for target in targets:
        engine.rest_target(target)


def _received_green_bless(source: CardInstance, state: Any, ctx: Context) -> bool:
    mana = ctx.target
    return (
        ctx.source is source
        and source.area is AreaType.FIELD
        and isinstance(mana, CardInstance)
        and mana.area is AreaType.BLESSING
        and mana in source.blessings
        and state.engine._mana_color_of(mana) is Color.GREEN
    )


def _transform_on_green_bless(source: CardInstance, state: Any, ctx: Context) -> None:
    mana = ctx.target
    if not isinstance(mana, CardInstance):
        raise RuntimeError(f"{CARD_ID} transformation requires the attached Green Bless Mana")
    if mana.area is not AreaType.BLESSING or mana not in source.blessings:
        raise RuntimeError(f"{CARD_ID} transformation target is not attached to this Minion")
    if state.engine._mana_color_of(mana) is not Color.GREEN:
        raise RuntimeError(f"{CARD_ID} transformation received non-Green Bless Mana")
    try:
        target_id = transformation_target_id(source.card.id, TRANSFORMED_CARD_ID)
        transformed = copy(CARD_REGISTRY[target_id])
    except KeyError as exc:
        raise RuntimeError(f"{CARD_ID} transformed face is not registered: {TRANSFORMED_CARD_ID}") from exc
    transformed.cost = dict(transformed.cost)
    transformed.keywords = list(transformed.keywords)
    transformed.effects = list(transformed.effects)
    transformed.triggers = list(transformed.triggers)
    state.engine.banish_blessing_mana(source, mana, source=source)
    state.engine.transform_card(source, transformed, target=mana)


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.ability_jp = (
        "【召喚時】＆スイッチ：「黒の剣士」"
        "自分の緑のミニオン1体毎に、相手のミニオン1体をレストする。\n"
        "【常時】このミニオンがアクティブ状態でなければ［加護］は付与されない。\n"
        "【加護時】緑の加護である場合、加護しているマナを除外して、"
        "「「整合騎士」ユージオ」に変形する。"
    )
    card.can_bless_while_rested = False
    card.effects.extend([
        EffectSpec(
            timing=EffectTiming.ON_SUMMON,
            fn=_rest_for_each_green_minion,
            condition=_self_source,
            target_kind="enemy_minion",
            min_targets=1,
            max_targets=5,
            params={
                "ex02c_switch_races": ["黒の剣士"],
                "exact_target_count_from_own_green_minions": True,
            },
            official_effect="自分の緑のミニオン1体毎に、相手のミニオン1体をレストする。",
            official_timing="召喚時＆スイッチ",
            official_condition="スイッチ：「黒の剣士」",
            active_areas=(AreaType.FIELD,),
        ),
        EffectSpec(
            timing=EffectTiming.ON_BLESS,
            fn=_transform_on_green_bless,
            condition=_received_green_bless,
            official_effect=(
                "緑の加護である場合、加護しているマナを除外して、"
                "「「整合騎士」ユージオ」に変形する。"
            ),
            official_timing="加護時",
            active_areas=(AreaType.FIELD,),
        ),
    ])
    return card
