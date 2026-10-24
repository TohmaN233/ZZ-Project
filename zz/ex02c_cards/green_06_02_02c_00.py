from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming
from zz.enums import AreaType, Keyword
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "green_06_02_02c_00"


def _own_turn_life_condition(source: CardInstance, state: Any) -> bool:
    return state.active is source.owner and source.owner.life >= 7


def _alice_stat_aura(source: CardInstance, target: CardInstance, state: Any) -> tuple[int, int]:
    if source is target and source.area is AreaType.FIELD and _own_turn_life_condition(source, state):
        return 0, 1
    return 0, 0


def _alice_keyword_aura(source: CardInstance, target: CardInstance, state: Any) -> list[Keyword]:
    if source is target and source.area is AreaType.FIELD and _own_turn_life_condition(source, state):
        return [Keyword.RUSH, Keyword.REAWAKEN]
    return []


def _rested_minions(ctx: Context) -> list[CardInstance]:
    value = ctx.target
    if isinstance(value, CardInstance):
        targets = [value]
    elif isinstance(value, (list, tuple)):
        targets = list(value)
    else:
        raise RuntimeError(f"{CARD_ID} rest event requires Field Minions, received {type(value).__name__}")
    for target in targets:
        if not isinstance(target, CardInstance):
            raise RuntimeError(f"{CARD_ID} rest event contains non-card target {type(target).__name__}")
    return targets


def _opponent_minion_rested(source: CardInstance, state: Any, ctx: Context) -> bool:
    return (
        source.area is AreaType.FIELD
        and state.active is source.owner
        and any(
            target.area is AreaType.FIELD and target.owner is not source.owner
            for target in _rested_minions(ctx)
        )
    )


def _heal_for_rest_batch(source: CardInstance, state: Any, _ctx: Context) -> None:
    state.engine.heal_target(source.owner, 1)


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.ability_jp = (
        "【自分のターン】\n"
        "自分のプレイヤーのライフが7以上である場合、このミニオンは[襲撃]と[再起]を持ち、DP+1する。\n"
        "【自分のターン】\n"
        "『神聖術』相手のミニオンが1体以上レストするたび、自分のプレイヤーを1回復する。"
    )
    card.stat_aura = _alice_stat_aura
    card.keyword_aura = _alice_keyword_aura
    card.effects.append(
        EffectSpec(
            timing=EffectTiming.ON_REST,
            fn=_heal_for_rest_batch,
            condition=_opponent_minion_rested,
            official_effect="『神聖術』相手のミニオンが1体以上レストするたび、自分のプレイヤーを1回復する。",
            official_timing="自分のターン",
            active_areas=(AreaType.FIELD,),
        )
    )
    return card
