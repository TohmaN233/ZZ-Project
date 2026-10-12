from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming
from zz.enums import AreaType, Keyword
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "yellow_07_02_02r_01"


def _self_transformed(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source


def _self_attacks(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source


def _buff_other_minions(source: CardInstance, state: Any, _ctx: Context) -> None:
    engine = state.engine
    for target in list(source.owner.field):
        if target is not source:
            engine.modify_stat(target, bp_delta=200, dp_delta=1, duration="turn")


def _lock_low_cost_enemy_minion(source: CardInstance, state: Any, _ctx: Context) -> None:
    engine = state.engine
    eligible = [
        candidate
        for candidate in state.players[1 - state.players.index(source.owner)].field
        if sum(candidate.card.cost.values()) <= 6
    ]
    if not eligible:
        return
    selected = engine.select_target(
        source.owner,
        "enemy_minion",
        1,
        1,
        filter_fn=lambda candidate: sum(candidate.card.cost.values()) <= 6,
        source=source,
    )
    if len(selected) != 1:
        raise RuntimeError(f"{CARD_ID} expected one enemy Minion costing at most 6, received {len(selected)}")
    selected[0].flags.add("pc01r:locked_until_owner_turn_end")


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    if Keyword.RUSH not in card.keywords:
        card.keywords = list(card.keywords) + [Keyword.RUSH]
    card.effects = list(card.effects) + [
        EffectSpec(
            timing=EffectTiming.ON_TRANSFORM,
            fn=_buff_other_minions,
            condition=_self_transformed,
            official_effect="変形時、このターン中、他の自分のミニオン全てをBP+200/DP+1する",
            official_timing="変形時",
        ),
        EffectSpec(
            timing=EffectTiming.ON_ATTACK,
            fn=_lock_low_cost_enemy_minion,
            condition=_self_attacks,
            target_kind="enemy_minion",
            min_targets=1,
            max_targets=1,
            params={"max_cost": 6},
            active_areas=(AreaType.FIELD,),
            official_effect="相手のコスト6以下のミニオン1体を次の相手ターン終了時まで攻撃・ブロック・移動不可にする",
            official_timing="アタック時",
        ),
    ]
    return card
