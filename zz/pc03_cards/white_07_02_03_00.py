from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming
from zz.enums import AreaType, CardType, Color
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row

CARD_ID = "white_07_02_03_00"
ABILITY_JP = (
    "自分の種族「アルカナ」を持つ白のミニオンがいる場合、"
    "自分の手札にあるこのカードのフリーコストは2減らされる。\n"
    "【メイン】/【フラッシュ】\n"
    "相手のコスト5以上のミニオン1体を除外する。"
    "相手のデッキの中からそのミニオンと同じコストのカード全てを除外する。"
)
ABILITY_EN = (
    "If you have a minion belonging to the Arcana class on your field, "
    "reduce the basic cost of this card in your hand by 2.\n"
    "[Main]/[Flash]\n"
    "Banish one of your opponent's minions with a cost of 5 or higher. "
    "Banish all cards in your opponent's deck with the same cost as that minion."
)


def _reduce_free_cost_for_white_arcana(
    source: CardInstance, target: CardInstance, _state: Any
) -> int:
    if (
        source is not target
        or source.area is not AreaType.HAND
        or target.owner is not source.owner
        or target.card.type is not CardType.MAGIC
    ):
        return 0
    if any(
        minion.card.type is CardType.F_MINION
        and minion.card.printed_color is Color.WHITE
        and "アルカナ" in minion.card.race_jp.split("|")
        for minion in source.owner.field
    ):
        return -2
    return 0


def _banish_selected_and_same_cost_deck(
    source: CardInstance, state: Any, _ctx: Context
) -> None:
    engine = state.engine
    if engine is None:
        raise RuntimeError(f"{CARD_ID} banish effect requires an Engine")
    selected = engine.select_target(
        source.owner,
        "enemy_minion",
        1,
        1,
        filter_fn=lambda target: sum(target.card.cost.values()) >= 5,
        source=source,
    )
    if not selected:
        return
    if len(selected) != 1:
        raise RuntimeError(f"{CARD_ID} must resolve with exactly one legal Minion")
    target = selected[0]
    selected_cost = sum(target.card.cost.values())
    if selected_cost < 5:
        raise RuntimeError(f"{CARD_ID} selected a Minion below the printed cost limit")
    if not engine.banish_target(
        target, source=source, effect_controller=source.owner
    ):
        raise RuntimeError(f"{CARD_ID} selected Minion could not be banished")
    opponent = state.players[1 - state.players.index(source.owner)]
    same_cost_cards = [
        card for card in list(opponent.deck)
        if sum(card.card.cost.values()) == selected_cost
    ]
    engine.banish_from_deck(
        opponent,
        same_cost_cards,
        source=source,
        effect_controller=source.owner,
    )


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.ability_jp = ABILITY_JP
    card.ability_en = ABILITY_EN
    card.cost_aura = _reduce_free_cost_for_white_arcana
    card.effects.append(
        EffectSpec(
            EffectTiming.ON_CAST_MAGIC,
            _banish_selected_and_same_cost_deck,
            target_kind="enemy_minion",
            min_targets=1,
            max_targets=1,
            params={"min_cost": 5},
            official_effect=(
                "相手のコスト5以上のミニオン1体を除外する。"
                "相手のデッキの中からそのミニオンと同じコストのカード全てを除外する。"
            ),
            official_timing="メイン/フラッシュ",
        )
    )
    return card
