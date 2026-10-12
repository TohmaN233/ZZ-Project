from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming
from zz.enums import AreaType, CardType
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = 'colorless_07_02_02r_01'


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.effects = list(card.effects) + [
        EffectSpec(
            timing=EffectTiming.ON_SUMMON,
            fn=_copy_until_minion_counts_match,
            condition=_this_minion_was_summoned,
            official_effect="相手のミニオンの数と同じになるまで「炎狼」ヴォルトのコピーを自分のフィールドに出す",
            official_timing="召喚時",
        )
    ]
    return card


def _this_minion_was_summoned(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source


def _field_minion_count(player: Any) -> int:
    return sum(
        1
        for minion in player.field
        if minion.card.type in (CardType.F_MINION, CardType.B_MINION)
    )


def _copy_until_minion_counts_match(source: CardInstance, state: Any, _ctx: Context) -> None:
    owner = source.owner
    opponent = state.players[1 - state.players.index(owner)]
    engine = state.engine
    while _field_minion_count(owner) < _field_minion_count(opponent):
        engine._make_field_space(owner, None)
        copy = CardInstance(
            card=source.card,
            owner=owner,
            iid=state.allocate_iid(),
            area=AreaType.FIELD,
            summoning_sickness=True,
        )
        owner.field.append(copy)
        engine._emit_enter_field(owner, copy)
