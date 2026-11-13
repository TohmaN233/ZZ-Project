from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming
from zz.enums import AreaType, AttackTargetKind, CardType, Color
from zz.model import CardInstance, Context, Player
from zz.pc01 import _card_from_row


CARD_ID = "red_01_01_03_00"
EVOKER_RACE = "エヴォーカー"


def _has_red_or_neutral_evoker_mana(source: CardInstance) -> bool:
    return any(
        mana.card.type is CardType.B_MINION
        and EVOKER_RACE in mana.card.race_jp.split("|")
        and (mana.mana_color_override or mana.card.mana_color) in {Color.RED, Color.COLORLESS}
        for mana in source.owner.base
    )


def _player_attack_with_evoker_mana(source: CardInstance, state: Any, ctx: Context) -> bool:
    return (
        ctx.source is source
        and source.area is AreaType.FIELD
        and source.owner is ctx.controller
        and state.active is source.owner
        and isinstance(ctx.target, Player)
        and ctx.target is not source.owner
        and _has_red_or_neutral_evoker_mana(source)
    )


def _grant_battle_dp(source: CardInstance, state: Any, _ctx: Context) -> None:
    engine = state.engine
    if engine is None:
        raise RuntimeError(f"{CARD_ID} attack effect requires an Engine")
    engine.modify_stat(source, dp_delta=1, duration="battle")


def _self_moved_to_base(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source and source.area is AreaType.BASE


def _rest_when_moved_to_base(source: CardInstance, state: Any, _ctx: Context) -> None:
    engine = state.engine
    if engine is None:
        raise RuntimeError(f"{CARD_ID} movement effect requires an Engine")
    engine.rest_target(source)


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.effects.extend(
        [
            EffectSpec(
                EffectTiming.ON_ATTACK,
                _grant_battle_dp,
                condition=_player_attack_with_evoker_mana,
                official_effect="自分の種族「エヴォーカー」を持つ赤または無色のマナがある場合、このミニオンがプレイヤーにアタックしたとき、このバトル中DP+1する。",
                official_timing="アタック時",
                active_areas=(AreaType.FIELD,),
            ),
            EffectSpec(
                EffectTiming.MOVE_TO_BASE,
                _rest_when_moved_to_base,
                condition=_self_moved_to_base,
                official_effect="このミニオンはベースに移動するとき、レスト状態で移動する。",
                official_timing="後退時",
                active_areas=(AreaType.BASE,),
            ),
        ]
    )
    return card
