from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "green_01_03_02r_00"


def _this_magic_was_cast(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source


def _heal_by_opponent_field_size(source: CardInstance, state: Any, _ctx: Context) -> None:
    opponent = state.players[1 - state.players.index(source.owner)]
    state.engine.heal(source.owner, 3 if len(opponent.field) >= 4 else 1)


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.effects = list(card.effects) + [
        EffectSpec(
            timing=EffectTiming.ON_CAST_MAGIC,
            fn=_heal_by_opponent_field_size,
            condition=_this_magic_was_cast,
            official_effect="自分のライフを1回復する。相手のミニオンが4体以上なら、代わりに3回復する",
            official_timing="マジック使用時",
        )
    ]
    return card
