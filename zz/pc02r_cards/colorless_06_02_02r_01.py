from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming
from zz.enums import CardType
from zz.pc01 import _card_from_row


CARD_ID = "colorless_06_02_02r_01"


def _opponent_minion_attacks_owner_life(source, state, ctx) -> bool:
    attacker = ctx.source
    return (
        state.active is not source.owner
        and ctx.target is source.owner
        and getattr(attacker, "owner", None) is not source.owner
        and getattr(getattr(attacker, "card", None), "type", None) is CardType.F_MINION
    )


def _refresh_this_minion(source, state, _ctx) -> None:
    state.engine.refresh_target(source)


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.effects = list(card.effects) + [
        EffectSpec(
            timing=EffectTiming.ON_ATTACK,
            fn=_refresh_this_minion,
            condition=_opponent_minion_attacks_owner_life,
            official_effect="相手のミニオンに自分のライフを攻撃されたとき、このミニオンをアクティブにする",
            official_timing="相手のターン",
        )
    ]
    return card
