from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming, build_effect
from zz.enums import AreaType, CardType, Color
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "red_02_01_03_03"


def _own_turn_end(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return source.area is AreaType.FIELD and source.owner is ctx.controller and source.owner is _state.active


def _own_token_minion_destroyed(source: CardInstance, _state: Any, ctx: Context) -> bool:
    destroyed = ctx.target
    return (
        source.area is AreaType.FIELD
        and isinstance(destroyed, CardInstance)
        and destroyed.owner is source.owner
        and destroyed.card.type is CardType.F_MINION
        and destroyed.card.is_token
    )


def _gain_bp_and_dp(source: CardInstance, state: Any, _ctx: Context) -> None:
    engine = state.engine
    if engine is None:
        raise RuntimeError(f"{CARD_ID} token destruction effect requires an Engine")
    engine.modify_stat(source, bp_delta=100, dp_delta=1, duration="permanent")


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.effects.extend(
        [
            build_effect(
                "create_tokens",
                EffectTiming.TURN_END,
                condition=_own_turn_end,
                amount=1,
                token_id="s_golem_token",
                name_jp="S・ゴレイム・トークン",
                color=Color.RED,
                cost=1,
                bp=100,
                dp=1,
                race_jp="ゴレイム",
                official_effect="「S・ゴレイム・トークン」1体を出す。",
                official_timing="自分のターン終了時",
                active_areas=(AreaType.FIELD,),
            ),
            EffectSpec(
                EffectTiming.ON_DESTROY,
                _gain_bp_and_dp,
                condition=_own_token_minion_destroyed,
                official_effect="自分のミニオン・トークンが破壊されるたび、このミニオンにBP+100/DP+1を付与する。",
                official_timing="常時",
                active_areas=(AreaType.FIELD,),
            ),
        ]
    )
    return card
