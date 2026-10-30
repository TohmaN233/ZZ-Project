from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming
from zz.enums import AreaType
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "green_05_02_02c_00"
_ITEM_BLESS_EFFECT = "ex02c_berkuli_item_bless_until_opponent_turn_end"


def _blessed_this_minion(source: CardInstance, _state: Any, ctx: Context) -> bool:
    mana = ctx.target
    return (
        ctx.source is source
        and source.area is AreaType.FIELD
        and isinstance(mana, CardInstance)
        and mana.area is AreaType.BLESSING
        and mana in source.blessings
    )


def _grant_item_bless_effect(source: CardInstance, state: Any, _ctx: Context) -> None:
    source.flags.add(_ITEM_BLESS_EFFECT)
    opponent = state.players[1 - state.players.index(source.owner)]
    state.engine.schedule_turn_end_effect(
        opponent,
        lambda: source.flags.discard(_ITEM_BLESS_EFFECT),
    )


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


def _opponent_minion_rested(source: CardInstance, _state: Any, ctx: Context) -> bool:
    if _ITEM_BLESS_EFFECT not in source.flags or source.area is not AreaType.FIELD:
        return False
    return any(
        target.area is AreaType.FIELD and target.owner is not source.owner
        for target in _rested_minions(ctx)
    )


def _weaken_rested_opponents(source: CardInstance, state: Any, ctx: Context) -> None:
    for target in _rested_minions(ctx):
        if target.area is AreaType.FIELD and target.owner is not source.owner:
            state.engine.modify_stat(target, bp_delta=-300, duration="turn")


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.effects.extend([
        EffectSpec(
            timing=EffectTiming.ON_BLESS,
            fn=_grant_item_bless_effect,
            condition=_blessed_this_minion,
            official_effect=(
                "次の相手のターン終了時まで、このミニオンに"
                "「相手のミニオンがレストするたび、このターン中、そのミニオンをBP-300する。」"
                "を与える。"
            ),
            official_timing="加護時",
            active_areas=(AreaType.FIELD,),
        ),
        EffectSpec(
            timing=EffectTiming.ON_REST,
            fn=_weaken_rested_opponents,
            condition=_opponent_minion_rested,
            official_effect="相手のミニオンがレストするたび、このターン中、そのミニオンをBP-300する。",
            official_timing="相手のミニオンがレストするたび",
            active_areas=(AreaType.FIELD,),
        ),
    ])
    return card
