from __future__ import annotations

from copy import copy
from typing import Any

from zz.cards import CARD_REGISTRY
from zz.effects import EffectSpec, EffectTiming
from zz.enums import AreaType
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "purple_03_02_02r_01"
_MUD_PIT_ID = "purple_01_03_01_00"


def _self_summoned(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source


def _add_mud_pit_from_outside(source: CardInstance, state: Any, _ctx: Context) -> None:
    try:
        mud_pit = copy(CARD_REGISTRY[_MUD_PIT_ID])
    except KeyError as exc:
        raise RuntimeError(f"{CARD_ID} Mud Pit card is not registered: {_MUD_PIT_ID}") from exc
    created = CardInstance(card=mud_pit, owner=source.owner, area=AreaType.DECK)
    added = state.engine.add_to_hand(
        source.owner,
        created,
        from_area=AreaType.DECK,
        record_event=False,
    )
    if added and created not in source.owner.hand:
        raise RuntimeError(f"{CARD_ID} created Mud Pit was not added to hand")
    if not added and created not in source.owner.trash:
        raise RuntimeError(f"{CARD_ID} failed to add Mud Pit from outside the game")


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.effects = list(card.effects) + [
        EffectSpec(
            timing=EffectTiming.ON_SUMMON,
            fn=_add_mud_pit_from_outside,
            condition=_self_summoned,
            official_effect="ゲーム外からマッドピッド1枚を手札に加える",
            official_timing="召喚時",
        )
    ]
    return card
