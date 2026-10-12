from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming
from zz.enums import CardType, Color, Keyword
from zz.model import Card
from zz.pc01 import _card_from_row


CARD_ID = "colorless_02_02_02r_01"

_SLIME_BLOCK_TOKEN = Card(
    id="slime_block_token",
    name_jp="スライム・ブロック・トークン",
    name_en="Token Slime Block",
    type=CardType.F_MINION,
    is_token=True,
    cost={Color.COLORLESS: 1},
    bp=300,
    dp=0,
    keywords=[Keyword.CANNOT_BLOCK],
    ability_jp="【常時】このミニオンはブロックできない。",
    ability_en="[Passive] This minion cannot block.",
)


def _this_minion_was_summoned(source, _state, ctx) -> bool:
    return ctx.source is source


def _create_opponent_token(source, state, _ctx) -> None:
    opponent = state.players[1 - state.players.index(source.owner)]
    state.engine.create_tokens(opponent, [_SLIME_BLOCK_TOKEN], source=source)


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.effects = list(card.effects) + [
        EffectSpec(
            timing=EffectTiming.ON_SUMMON,
            fn=_create_opponent_token,
            condition=_this_minion_was_summoned,
            template_id="create_tokens",
            params={"amount": 1, "token_recipient": "opponent"},
            official_effect="相手のフィールドにスライム・ブロック・トークン1体を出す",
            official_timing="召喚時",
        )
    ]
    return card
