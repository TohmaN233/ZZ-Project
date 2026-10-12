from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming
from zz.pc01 import _card_from_row, _self_source


CARD_ID = 'colorless_010_02_02r_00'


def _attack_player_damage(ci, state, ctx) -> None:
    if ctx.source is not ci:
        return

    opponent = state.players[1 - state.players.index(ci.owner)]
    live_forces = sum(1 for force in opponent.forces if not force.destroyed)
    amount = max(0, 3 - live_forces)
    if amount:
        state.engine._damage_player(opponent, amount, source=ci)


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.effects.append(
        EffectSpec(
            EffectTiming.ON_ATTACK,
            _attack_player_damage,
            condition=_self_source,
        )
    )
    return card
