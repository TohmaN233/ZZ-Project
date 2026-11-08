from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming
from zz.enums import AreaType, CardType, Color
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "purple_08_01_03_00"


def _self_summoned(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source and source.area is AreaType.FIELD


def _discard_eligible_deck_minions(source: CardInstance, state: Any, _ctx: Context) -> None:
    engine = state.engine
    if engine is None:
        raise RuntimeError(f"{CARD_ID} summon effect requires an Engine")
    engine.discard_deck_matching(
        source.owner,
        source=source,
        predicate=lambda candidate: candidate.card.type is CardType.F_MINION
        and sum(candidate.card.cost.values()) <= 5,
        shuffle=True,
    )


def _own_turn_end(source: CardInstance, state: Any, ctx: Context) -> bool:
    return source.area is AreaType.FIELD and source.owner is ctx.controller and state.active is source.owner


def _damage_for_purple_cards(source: CardInstance, state: Any, _ctx: Context) -> None:
    engine = state.engine
    if engine is None:
        raise RuntimeError(f"{CARD_ID} turn-end effect requires an Engine")
    purple_cards = sum(1 for card in source.owner.trash if card.card.printed_color is Color.PURPLE)
    damage_count = purple_cards // 10
    opponent = state.players[1 - state.players.index(source.owner)]
    for _ in range(damage_count):
        engine._damage_player(opponent, 1, source=source, damage_kind="effect")


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.effects.extend(
        [
            EffectSpec(
                EffectTiming.ON_SUMMON,
                _discard_eligible_deck_minions,
                condition=_self_summoned,
                official_effect="自分のデッキの中からコスト5以下のフィールド・ミニオンカード全てを破棄する。その後、自分のデッキをシャッフルする。",
                official_timing="召喚時",
            ),
            EffectSpec(
                EffectTiming.TURN_END,
                _damage_for_purple_cards,
                condition=_own_turn_end,
                official_effect="自分のトラッシュにある紫のカード10枚毎に、相手のプレイヤーに1ダメージを与える。",
                official_timing="自分のターン終了時",
                active_areas=(AreaType.FIELD,),
            ),
        ]
    )
    return card
