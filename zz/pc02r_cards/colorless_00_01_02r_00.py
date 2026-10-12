from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming
from zz.enums import AreaType, CardType, Color, Keyword
from zz.model import Card
from zz.pc01 import _card_from_row


CARD_ID = "colorless_00_01_02r_00"

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


def _this_base_was_placed(source, _state, ctx) -> bool:
    return ctx.source is source


def _create_slime_block(source, state, _ctx) -> None:
    state.engine.create_tokens(source.owner, [_SLIME_BLOCK_TOKEN], source=source)


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    # This Base Minion's printed Boost is its permission to attach as mana.
    # The Japanese OCR omitted the Boost heading, so _card_from_row cannot
    # derive KAGO from the source text by itself.
    if Keyword.KAGO not in card.keywords:
        card.keywords = list(card.keywords) + [Keyword.KAGO]
    # These are the printed Boost stats. The Base Minion itself has no Field
    # aura: its BP/DP are applied only while attached as Blessing mana.
    card.bp = 200
    card.dp = 1
    card.effects = list(card.effects) + [
        EffectSpec(
            timing=EffectTiming.ON_PLACE_BASE,
            fn=_create_slime_block,
            condition=_this_base_was_placed,
            template_id="create_tokens",
            params={"amount": 1},
            active_areas=(AreaType.BASE,),
            official_effect="配置時、「スライム・ブロック・トークン」1体を自分のフィールドに出す",
            official_timing="配置時",
        )
    ]
    return card
