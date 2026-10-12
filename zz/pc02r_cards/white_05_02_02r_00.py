from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming
from zz.enums import AreaType, CardType, Color
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "white_05_02_02r_00"
_PROTECTION_FLAG_PREFIX = "opponent_effect_target_protection"


def _eligible_white_dragon_minion(target: CardInstance, owner) -> bool:
    return (
        target.owner is owner
        and target.area is AreaType.FIELD
        and target.card.type in (CardType.F_MINION, CardType.B_MINION)
        and target.card.printed_color is Color.WHITE
        and "ドラゴン" in target.card.race_jp
    )


def _turn_marker(source: CardInstance, state: Any) -> str:
    return f"{_PROTECTION_FLAG_PREFIX}:{state.turn}:{source.owner.side.name}"


def _own_turn_started(source: CardInstance, state: Any, ctx: Context) -> bool:
    return ctx.controller is source.owner and state.active is source.owner


def _own_turn_is_active(source: CardInstance, state: Any, _ctx: Context) -> bool:
    return state.active is source.owner


def _apply_protection_to_white_dragons(source: CardInstance, state: Any, _ctx: Context) -> None:
    marker = _turn_marker(source, state)
    for target in source.owner.field:
        if _eligible_white_dragon_minion(target, source.owner):
            target.flags.add(marker)


def _clear_protection_from_white_dragons(source: CardInstance, state: Any, _ctx: Context) -> None:
    marker = _turn_marker(source, state)
    for target in source.owner.field:
        target.flags.discard(marker)


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.effects = list(card.effects) + [
        EffectSpec(
            timing=EffectTiming.TURN_START,
            fn=_apply_protection_to_white_dragons,
            condition=_own_turn_started,
            active_areas=(AreaType.FIELD,),
            official_effect="自分のターン中、自分の白いDragon Minionは相手のカード効果で選択されない",
            official_timing="自分のターン開始時",
        ),
        EffectSpec(
            timing=EffectTiming.ON_SUMMON,
            fn=_apply_protection_to_white_dragons,
            condition=_own_turn_is_active,
            active_areas=(AreaType.FIELD,),
            official_effect="自分のターン中、自分の白いDragon Minionは相手のカード効果で選択されない",
            official_timing="自分のターン中",
        ),
        EffectSpec(
            timing=EffectTiming.ON_MOVE_TO_FIELD,
            fn=_apply_protection_to_white_dragons,
            condition=_own_turn_is_active,
            active_areas=(AreaType.FIELD,),
            official_effect="自分のターン中、自分の白いDragon Minionは相手のカード効果で選択されない",
            official_timing="自分のターン中",
        ),
        EffectSpec(
            timing=EffectTiming.TURN_END,
            fn=_clear_protection_from_white_dragons,
            condition=lambda source, state, ctx: ctx.controller is source.owner and state.active is source.owner,
            active_areas=(AreaType.FIELD,),
            official_effect="相手のターンに入ると保護は終了する",
            official_timing="自分のターン終了時",
        ),
    ]
    return card
