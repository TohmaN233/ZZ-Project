from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "colorless_03_02_02r_01"
LOYAL_CANINE_KAISER_ID = "colorless_05_02_02r_00"


def _has_ally_loyal_canine_kaiser(source: CardInstance) -> bool:
    return any(
        card.card.id == LOYAL_CANINE_KAISER_ID
        for card in source.owner.field
    )


def _this_minion_attacks_with_kaiser(source: CardInstance, state: Any, ctx: Context) -> bool:
    return (
        ctx.source is source
        and state.active is source.owner
        and _has_ally_loyal_canine_kaiser(source)
    )


def _draw_one_card(source: CardInstance, state: Any, _ctx: Context) -> None:
    state.engine.draw(source.owner, 1)


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.effects = list(card.effects) + [
        EffectSpec(
            timing=EffectTiming.ON_ATTACK,
            fn=_draw_one_card,
            condition=_this_minion_attacks_with_kaiser,
            official_effect="自分のフィールドに「ロイヤルドッグ」がいる場合、カードを1枚引く",
            official_timing="アタック時",
            official_condition="自分のフィールドに「ロイヤルドッグ」がいる",
        )
    ]
    return card

