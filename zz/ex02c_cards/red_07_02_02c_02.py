from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming
from zz.enums import AreaType, Color
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "red_07_02_02c_02"
TRANSFORMED_CARD_ID = "red_07_02_02c_00"
_ALLOW_RESTED_BLESS = "turn:pc02_ex02c_allow_rested_bless"


def _self_source(source: CardInstance, state: Any, ctx: Context) -> bool:
    return ctx.source is source


def _summon(source: CardInstance, state: Any, ctx: Context) -> None:
    if _ALLOW_RESTED_BLESS not in source.owner.flags:
        source.owner.flags.add(_ALLOW_RESTED_BLESS)
        state.engine.schedule_turn_end_effect(
            source.owner,
            lambda: source.owner.flags.discard(_ALLOW_RESTED_BLESS),
        )
    other_minions = [card for card in source.owner.field if card is not source]
    if not other_minions:
        state.engine.grant_movement_right(source.owner, 1)


def _transform_on_red_bless(source: CardInstance, state: Any, ctx: Context) -> None:
    mana = ctx.target
    if not isinstance(mana, CardInstance) or state.engine._mana_color_of(mana) is not Color.RED:
        return
    state.engine.banish_blessing_mana(source, mana, source=source)
    from zz.cards import CARD_REGISTRY

    state.engine.transform_card(source, CARD_REGISTRY[TRANSFORMED_CARD_ID], target=mana)


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.can_bless_while_rested = False
    card.effects.extend([
        EffectSpec(
            timing=EffectTiming.ON_SUMMON,
            fn=_summon,
            condition=_self_source,
            official_effect=(
                "このターン中、自分のプレイヤーに「自分の［加護］を持つマナ全ては、"
                "レスト状態でも付与することができる。」を与える。"
                "他に自分のミニオンがいない場合、自分の移動権を1増やす。"
            ),
            official_timing="召喚時",
            active_areas=(AreaType.FIELD,),
        ),
        EffectSpec(
            timing=EffectTiming.ON_BLESS,
            fn=_transform_on_red_bless,
            condition=_self_source,
            official_effect=(
                "赤の加護である場合、加護しているマナを除外して、"
                "「「双剣」キリト」に変形する。"
            ),
            official_timing="加護時",
            active_areas=(AreaType.FIELD,),
        ),
    ])
    return card
