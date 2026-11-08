from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming, build_effect
from zz.enums import AreaType, CardType, Color, Keyword
from zz.model import Card, CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "red_04_01_03_00"
TOKEN_S_ID = "s_golem_token"
TOKEN_M_ID = "m_golem_token"


def _self_summoned(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source and source.area is AreaType.FIELD


def _self_moved_to_base(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source and source.area is AreaType.BASE


def _has_allied_token(source: CardInstance, state: Any, ctx: Context) -> bool:
    if not _self_moved_to_base(source, state, ctx):
        return False
    return any(
        target.area is AreaType.FIELD
        and target.owner is source.owner
        and target.card.type is CardType.F_MINION
        and target.card.is_token
        for target in source.owner.field
    )


def _m_token_card() -> Card:
    return Card(
        id=TOKEN_M_ID,
        name_jp="M・ゴレイム・トークン",
        name_en="Token Golem M",
        type=CardType.F_MINION,
        cost={Color.RED: 4},
        bp=500,
        dp=1,
        race_jp="ゴレイム",
        keywords=[Keyword.RUSH],
    )


def _destroy_token_and_create_m(source: CardInstance, state: Any, _ctx: Context) -> None:
    engine = state.engine
    if engine is None:
        raise RuntimeError(f"{CARD_ID} retreat effect requires an Engine")
    selected = engine.select_target(
        source.owner,
        "ally_minion",
        1,
        1,
        filter_fn=lambda target: (
            target.area is AreaType.FIELD
            and target.owner is source.owner
            and target.card.type is CardType.F_MINION
            and target.card.is_token
        ),
        source=source,
    )
    if len(selected) != 1:
        raise RuntimeError(f"{CARD_ID} expected exactly one selected allied token Minion, got {len(selected)}")
    token = selected[0]
    engine.destroy_target(token, source)
    if token in token.owner.field:
        return
    engine.create_tokens(source.owner, [_m_token_card()], source=source)


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.effects.extend(
        [
            build_effect(
                "create_tokens",
                EffectTiming.ON_SUMMON,
                condition=_self_summoned,
                amount=1,
                token_id=TOKEN_S_ID,
                name_jp="S・ゴレイム・トークン",
                color=Color.RED,
                cost=1,
                bp=100,
                dp=1,
                race_jp="ゴレイム",
                official_effect="「S・ゴレイム・トークン」1体を出す。",
                official_timing="召喚時",
            ),
            EffectSpec(
                EffectTiming.MOVE_TO_BASE,
                _destroy_token_and_create_m,
                condition=_has_allied_token,
                target_kind="ally_minion",
                min_targets=1,
                max_targets=1,
                params={"requires_token": True},
                official_effect=(
                    "自分のミニオン・トークン1体を破壊する。そうした場合、"
                    "「M・ゴレイム・トークン」1体を出す。"
                ),
                official_timing="後退時",
                active_areas=(AreaType.BASE,),
            ),
        ]
    )
    return card
