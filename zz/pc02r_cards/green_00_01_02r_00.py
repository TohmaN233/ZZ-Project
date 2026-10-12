from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming
from zz.enums import AreaType, Keyword
from zz.model import CardInstance, Context, Player
from zz.pc01 import _card_from_row


CARD_ID = "green_00_01_02r_00"


def _blessed_host(source: CardInstance, state: Any) -> CardInstance:
    if source.area is not AreaType.BLESSING:
        raise RuntimeError(f"{CARD_ID} Boost effect ran outside its Bless zone")
    hosts = [
        host
        for player in state.players
        for host in player.field
        if source in host.blessings
    ]
    if len(hosts) != 1:
        raise RuntimeError(f"{CARD_ID} expected one Bless host, found {len(hosts)}")
    return hosts[0]


def _refresh_on_life_damage(source: CardInstance, state: Any, ctx: Context) -> bool:
    host = _blessed_host(source, state)
    return (
        isinstance(ctx.target, Player)
        and ctx.target is host.owner
        and state.active is not host.owner
        and getattr(ctx, "damage_amount", 0) > 0
    )


def _refresh_blessed_minion(source: CardInstance, state: Any, _ctx: Context) -> None:
    _blessed_host(source, state).rested = False


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    if Keyword.KAGO not in card.keywords:
        card.keywords = list(card.keywords) + [Keyword.KAGO]
    card.effects = list(card.effects) + [
        EffectSpec(
            timing=EffectTiming.ON_DAMAGE_PLAYER,
            fn=_refresh_blessed_minion,
            condition=_refresh_on_life_damage,
            active_areas=(AreaType.BLESSING,),
            official_effect="相手のターン中、自分のプレイヤーがダメージを受けたとき加護先をアクティブにする",
            official_timing="相手のターン中のプレイヤー被ダメージ時",
        )
    ]
    return card
