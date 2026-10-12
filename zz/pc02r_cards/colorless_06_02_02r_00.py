from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = 'colorless_06_02_02r_00'


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.effects = list(card.effects) + [
        EffectSpec(
            timing=EffectTiming.ON_SUMMON,
            fn=_white_bat_summon,
            condition=_has_boosted_ally_when_summoned,
            official_effect="自分の加護が付与されているミニオンがいる場合、相手プレイヤーに1ダメージを与え、自分のプレイヤーを1回復する",
            official_timing="召喚時",
            official_condition="自分の加護が付与されているミニオンがいる場合",
        )
    ]
    return card


def _has_boosted_ally_when_summoned(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source and any(minion.blessings for minion in source.owner.field)


def _white_bat_summon(source: CardInstance, state: Any, _ctx: Context) -> None:
    opponent = state.players[1 - state.players.index(source.owner)]
    state.engine._damage_player(opponent, 1, source=source)
    state.engine.heal(source.owner, 1)
