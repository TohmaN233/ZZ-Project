from __future__ import annotations

from copy import copy
from typing import Any

from zz.cards import CARD_REGISTRY
from zz.effects import EffectSpec, EffectTiming
from zz.enums import AreaType, CardType, Color
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row
from zz.transformations import transformation_target_id

CARD_ID = "white_04_01_03_02"
TRANSFORMED_CARD_ID = "white_04_01_03_03"


def _self_summoned(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source


def _prevent_force_damage_until_opponent_end(source: CardInstance, state: Any, _ctx: Context) -> None:
    engine = state.engine
    if engine is None:
        raise RuntimeError(f"{CARD_ID} summon effect requires an Engine")
    opponent = next(player for player in state.players if player is not source.owner)
    engine.prevent_force_damage_until_turn_end(
        source.owner,
        1,
        end_player=opponent,
        source=source,
    )


def _received_white_bless(source: CardInstance, state: Any, ctx: Context) -> bool:
    mana = ctx.target
    engine = state.engine
    if engine is None:
        raise RuntimeError(f"{CARD_ID} Bless trigger requires an Engine")
    return (
        ctx.source is source
        and source.area is AreaType.FIELD
        and isinstance(mana, CardInstance)
        and mana.area is AreaType.BLESSING
        and mana in source.blessings
        and engine._mana_color_of(mana) is Color.WHITE
    )


def _transform_on_white_bless(source: CardInstance, state: Any, ctx: Context) -> None:
    mana = ctx.target
    if not isinstance(mana, CardInstance) or mana.area is not AreaType.BLESSING or mana not in source.blessings:
        raise RuntimeError(f"{CARD_ID} transformation target is not its attached White Bless Mana")
    engine = state.engine
    if engine is None:
        raise RuntimeError(f"{CARD_ID} transformation requires an Engine")
    if engine._mana_color_of(mana) is not Color.WHITE:
        raise RuntimeError(f"{CARD_ID} transformation received non-White Bless Mana")
    try:
        target_id = transformation_target_id(CARD_ID, TRANSFORMED_CARD_ID)
        transformed = copy(CARD_REGISTRY[target_id])
    except KeyError as exc:
        raise RuntimeError(f"{CARD_ID} transformed face is not registered: {TRANSFORMED_CARD_ID}") from exc
    transformed.cost = dict(transformed.cost)
    transformed.keywords = list(transformed.keywords)
    transformed.effects = list(transformed.effects)
    transformed.triggers = list(transformed.triggers)
    engine.banish_blessing_mana(source, mana, source=source)
    engine.transform_card(source, transformed, target=mana)


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.ability_jp = (
        "【召喚時】次の相手のターン終了時まで、自分のフォースに与えられるダメージを1軽減する。\n"
        "【常時】このミニオンがアクティブ状態でなければ［加護］は付与されない。\n"
        "【加護時】白の加護である場合、加護しているマナを除外して、「「市民の警衛」フェイス」に変形する。"
    )
    card.ability_en = (
        "[When Summoned] Damage dealt to your Forces is reduced by 1 until the end of your opponent's turn.\n"
        "[Passive] This minion cannot receive a Boost when not in the Active State.\n"
        "[When Boosted] If Boosted by a White Mana, banish that mana. This card Transforms into Faith - Protector of the Citizens."
    )
    card.can_bless_while_rested = False
    card.effects.extend(
        [
            EffectSpec(
                EffectTiming.ON_SUMMON,
                _prevent_force_damage_until_opponent_end,
                condition=_self_summoned,
                params={"force_damage_reduction": 1, "expiry_player": "opponent_turn_end"},
                official_effect="次の相手のターン終了時まで、自分のフォースに与えられるダメージを1軽減する。",
                official_timing="召喚時",
                active_areas=(AreaType.FIELD,),
            ),
            EffectSpec(
                EffectTiming.ON_BLESS,
                _transform_on_white_bless,
                condition=_received_white_bless,
                params={"blessing_color": Color.WHITE.name, "transform_to": TRANSFORMED_CARD_ID, "banish_blessing": True},
                official_effect="白の加護である場合、加護しているマナを除外して、「「市民の警衛」フェイス」に変形する。",
                official_timing="加護時",
                active_areas=(AreaType.FIELD,),
            ),
        ]
    )
    return card
