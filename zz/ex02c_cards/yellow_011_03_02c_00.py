from __future__ import annotations

from typing import Any

from zz.effects import EffectTiming, build_effect
from zz.enums import AreaType, Color, CardType
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "yellow_011_03_02c_00"


def _this_magic_was_cast(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source


def _has_absolute_sword_or_flash(source: CardInstance, _state: Any, _ctx: Context) -> bool:
    return any(
        minion.card.type is CardType.F_MINION
        and ({"絶剣", "閃光"} & set(minion.card.race_jp.split("|")))
        for minion in source.owner.field
    )


def _second_effect_is_active(source: CardInstance, state: Any, ctx: Context) -> bool:
    return ctx.source is source and _has_absolute_sword_or_flash(source, state, ctx)


def _zero_free_cost_with_four_opponent_cards(
    source: CardInstance,
    target: CardInstance,
    state: Any,
) -> int:
    if source is not target or target.area is not AreaType.HAND:
        return 0
    opponent = state.players[1 - state.players.index(target.owner)]
    if len(opponent.hand) < 4:
        return 0
    return -target.card.cost.get(Color.COLORLESS, 0)


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.cost_aura = _zero_free_cost_with_four_opponent_cards
    card.effects.extend([
        build_effect(
            "return_to_hand",
            EffectTiming.ON_CAST_MAGIC,
            condition=_this_magic_was_cast,
            target_kind="enemy_minion",
            min_targets=1,
            max_targets=1,
            max_cost=4,
            active_areas=(AreaType.TRASH,),
            official_effect="相手のコスト4以下のミニオン1体を手札に戻す。",
            official_timing="フラッシュ",
        ),
        build_effect(
            "return_to_hand",
            EffectTiming.ON_CAST_MAGIC,
            condition=_second_effect_is_active,
            target_kind="enemy_minion",
            min_targets=1,
            max_targets=1,
            min_cost=8,
            active_areas=(AreaType.TRASH,),
            official_effect="自分の種族「絶剣」または「閃光」を持つミニオンがいる場合、相手のコスト8以上のミニオン1体を手札に戻す。",
            official_timing="フラッシュ",
            official_condition="フィールドに自分の種族「絶剣」または「閃光」を持つミニオンがいる場合",
        ),
    ])
    return card
