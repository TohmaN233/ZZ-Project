from __future__ import annotations
from typing import Any
from zz.effects import EffectSpec, EffectTiming
from zz.enums import AreaType, CardType, Color
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row

CARD_ID = "yellow_02_01_03_01"

def _has_yellow_target(source: CardInstance, state: Any, ctx: Context) -> bool:
    if ctx.source is not source or source.area is not AreaType.BASE:
        return False
    engine = state.engine
    if engine is None:
        raise RuntimeError(f"{CARD_ID} retreat effect requires an Engine")
    return any(c.card.type in (CardType.F_MINION, CardType.B_MINION) and engine._card_color(c.card) is Color.YELLOW for c in source.owner.field)

def _buff(source: CardInstance, state: Any, _ctx: Context) -> None:
    engine = state.engine
    if engine is None:
        raise RuntimeError(f"{CARD_ID} retreat effect requires an Engine")
    targets = engine.select_target(source.owner, "ally_minion", 1, 1, source=source)
    if len(targets) != 1 or engine._card_color(targets[0].card) is not Color.YELLOW:
        raise RuntimeError(f"{CARD_ID} selected a target outside its Yellow Minion filter")
    engine.modify_stat(targets[0], bp_delta=300, duration="turn")

def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.effects.append(EffectSpec(EffectTiming.MOVE_TO_BASE, _buff, condition=_has_yellow_target,
        target_kind="ally_minion", min_targets=1, max_targets=1, params={"color": Color.YELLOW},
        official_effect="このターン中、自分の黄のミニオン1体をBP+300する。",
        official_timing="後退時", active_areas=(AreaType.BASE,)))
    return card
