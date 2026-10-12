from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming, build_effect
from zz.enums import Color
from zz.model import Context
from zz.pc01 import _card_from_row
from zz.pc02 import _destroy_colorless_mana


CARD_ID = "red_02_02_02r_01"

_S_GOLEM_CREATION = build_effect(
    "create_tokens",
    EffectTiming.ON_SUMMON,
    amount=1,
    token_id="s_golem_token",
    name_jp="S・ゴレイム・トークン",
    color=Color.RED,
    cost=1,
    bp=100,
    dp=1,
    race_jp="ゴレイム",
)


def _self_summoned(source, state, ctx: Context) -> bool:
    return ctx.source is source


def _ruler_golem_summon(source, state, ctx: Context) -> None:
    if _destroy_colorless_mana(source, state):
        _S_GOLEM_CREATION.fn(source, state, ctx)


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.effects.append(
        EffectSpec(
            timing=EffectTiming.ON_SUMMON,
            fn=_ruler_golem_summon,
            condition=_self_summoned,
            target_kind="ally_colorless_mana_token",
            min_targets=0,
            max_targets=1,
            optional=True,
            template_id="create_tokens",
            params={"amount": 1},
            official_effect="無色の非ミニオンマナを破壊しS・ゴレイム・トークンを出す",
            official_timing="召喚時",
        )
    )
    return card
