from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming
from zz.enums import AreaType, CardType
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row

CARD_ID = "white_03_01_03_02"
QUALIFYING_RACES = frozenset({"ハンター", "アルカナ"})


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


def _require_block(source: CardInstance, _state: Any, ctx: Context) -> None:
    attacker = ctx.source
    if not isinstance(attacker, CardInstance):
        raise RuntimeError(f"{CARD_ID} attack trigger lost its attacking Minion")
    attacker.flags.add("battle:must_be_blocked")


def _qualifying_ally_minion_won(source: CardInstance, state: Any, ctx: Context) -> bool:
    winner = ctx.source
    loser = ctx.target
    return (
        source.area is AreaType.FIELD
        and source.owner is ctx.controller
        and state.active is source.owner
        and isinstance(winner, CardInstance)
        and winner.area is AreaType.FIELD
        and winner.owner is source.owner
        and winner.card.type in (CardType.F_MINION, CardType.B_MINION)
        and bool(QUALIFYING_RACES.intersection(winner.card.race_jp.split("|")))
        and isinstance(loser, CardInstance)
        and loser.owner is not source.owner
        and loser.card.type in (CardType.F_MINION, CardType.B_MINION)
    )


def _deal_one_life_damage(source: CardInstance, state: Any, _ctx: Context) -> None:
    engine = state.engine
    if engine is None:
        raise RuntimeError(f"{CARD_ID} battle-win effect requires an Engine")
    opponent = next(player for player in state.players if player is not source.owner)
    engine._damage_player(opponent, 1, source=source)


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.ability_jp = (
        "【自分のターン】自分の種族「ハンター」または「アルカナ」を持つミニオンがアタックするたび、相手は必ずブロックする。\n"
        "【自分のターン】自分の種族「ハンター」または「アルカナ」を持つミニオンがバトルに勝利するたび、相手のプレイヤーに1ダメージを与える。"
    )
    card.effects.extend(
        [
            EffectSpec(
                EffectTiming.ON_ATTACK,
                _require_block,
                condition=_qualifying_ally_attack,
                params={"battle_scoped_forced_block": True, "qualifying_races": sorted(QUALIFYING_RACES)},
                official_effect="自分の種族「ハンター」または「アルカナ」を持つミニオンがアタックするたび、相手は必ずブロックする。",
                official_timing="自分のターン",
                active_areas=(AreaType.FIELD,),
            ),
            EffectSpec(
                EffectTiming.ON_BATTLE_WIN,
                _deal_one_life_damage,
                condition=_qualifying_ally_minion_won,
                official_effect="自分の種族「ハンター」または「アルカナ」を持つミニオンがバトルに勝利するたび、相手のプレイヤーに1ダメージを与える。",
                official_timing="自分のターン",
                active_areas=(AreaType.FIELD,),
            ),
        ]
    )
    return card
