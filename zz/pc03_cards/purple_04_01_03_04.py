from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming, build_effect
from zz.enums import AreaType, Color
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "purple_04_01_03_04"


def _own_turn_end(source: CardInstance, state: Any, ctx: Context) -> bool:
    return source.area is AreaType.FIELD and source.owner is ctx.controller and state.active is source.owner


def _mill_top_and_gain_bp(source: CardInstance, state: Any, _ctx: Context) -> None:
    engine = state.engine
    if engine is None:
        raise RuntimeError(f"{CARD_ID} turn-end effect requires an Engine")
    milled = engine.mill_deck(source.owner, 1, source=source)
    if milled and milled[0].card.printed_color is Color.PURPLE:
        engine.modify_stat(source, bp_delta=100, duration="permanent")


def _self_attack(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.effects.extend(
        [
            EffectSpec(
                EffectTiming.TURN_END,
                _mill_top_and_gain_bp,
                condition=_own_turn_end,
                official_effect="自分のデッキを上から1枚破棄する。そのカードが紫のカードである場合、このミニオンにBP+100を付与する。",
                official_timing="自分のターン終了時",
                active_areas=(AreaType.FIELD,),
            ),
            build_effect(
                "return_from_trash_to_hand",
                EffectTiming.ON_ATTACK,
                condition=_self_attack,
                target_kind="trash_minion",
                color=Color.PURPLE,
                official_effect="自分のトラッシュにある、紫のミニオンカード1枚を手札に戻す。",
                official_timing="アタック時",
                active_areas=(AreaType.FIELD,),
            ),
        ]
    )
    return card
