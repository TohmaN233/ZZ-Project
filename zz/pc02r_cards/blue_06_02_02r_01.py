from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming
from zz.enums import CardType, Color
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "blue_06_02_02r_01"


def _own_costly_magic_used(source: CardInstance, _state: Any, ctx: Context) -> bool:
    used = ctx.source
    return (
        isinstance(used, CardInstance)
        and used.owner is source.owner
        and used.card.type is CardType.MAGIC
        and sum(used.card.cost.values()) >= 4
    )


def _damage_opposing_forces(source: CardInstance, state: Any, _ctx: Context) -> None:
    engine = state.engine
    opponent = state.players[1 - state.players.index(source.owner)]
    for force in list(opponent.forces):
        if not force.destroyed:
            engine._damage_force(force, 1, source=source)


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.effects = list(card.effects) + [
        EffectSpec(
            timing=EffectTiming.ON_CARD_USED,
            fn=_damage_opposing_forces,
            condition=_own_costly_magic_used,
            official_effect="本来のコスト4以上のマジックを使用するたび、相手のフォース全てに1ダメージ",
            official_timing="常時",
        )
    ]
    return card
