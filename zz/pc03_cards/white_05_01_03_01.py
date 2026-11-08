from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming
from zz.enums import AreaType, CardType
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row

CARD_ID = "white_05_01_03_01"
QUALIFYING_RACES = frozenset({"アンドロイド", "アルカナ"})


def _qualifying_ally_attack(source: CardInstance, state: Any, ctx: Context) -> bool:
    attacker = ctx.source
    return (
        source.area is AreaType.FIELD
        and source.owner is ctx.controller
        and state.active is source.owner
        and isinstance(attacker, CardInstance)
        and attacker.area is AreaType.FIELD
        and attacker.owner is source.owner
        and attacker.card.type in (CardType.F_MINION, CardType.B_MINION)
        and bool(QUALIFYING_RACES.intersection(attacker.card.race_jp.split("|")))
    )


def _restrict_opponent_magic_for_battle(source: CardInstance, state: Any, ctx: Context) -> None:
    opponent = next(player for player in state.players if player is not source.owner)
    opponent.flags.add("battle:cannot_activate_magic")


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.ability_jp = (
        "［再起］\n【自分のターン】自分の種族「アンドロイド」または「アルカナ」を持つミニオンがアタックするたび、"
        "このバトル中、相手のプレイヤーに「このプレイヤーはマジックカードを使用できない。」を与える。"
    )
    card.effects.append(
        EffectSpec(
            EffectTiming.ON_ATTACK,
            _restrict_opponent_magic_for_battle,
            condition=_qualifying_ally_attack,
            params={"battle_scoped_restriction": "cannot_activate_magic", "qualifying_races": sorted(QUALIFYING_RACES)},
            official_effect="自分の種族「アンドロイド」または「アルカナ」を持つミニオンがアタックするたび、このバトル中、相手のプレイヤーはマジックカードを使用できない。",
            official_timing="自分のターン",
            active_areas=(AreaType.FIELD,),
        )
    )
    return card
