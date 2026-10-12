from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming
from zz.enums import AreaType
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "yellow_00_01_02r_00"


def _own_turn_started(source: CardInstance, state: Any, ctx: Context) -> bool:
    return ctx.controller is source.owner and state.active is source.owner


def _blessed_host(source: CardInstance, state: Any) -> CardInstance:
    hosts = [host for player in state.players for host in player.field if source in host.blessings]
    if source.area is not AreaType.BLESSING or len(hosts) != 1:
        raise RuntimeError(f"{CARD_ID} expected exactly one active Bless host")
    return hosts[0]


def _gain_start_of_turn_stats(source: CardInstance, state: Any, _ctx: Context) -> None:
    state.engine.modify_stat(_blessed_host(source, state), bp_delta=100, dp_delta=1, duration="turn")


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.effects = list(card.effects) + [
        EffectSpec(
            timing=EffectTiming.TURN_START,
            fn=_gain_start_of_turn_stats,
            condition=_own_turn_started,
            active_areas=(AreaType.BLESSING,),
            official_effect="このミニオンをBP+100/DP+1する",
            official_timing="自分のターン開始時",
        )
    ]
    return card
