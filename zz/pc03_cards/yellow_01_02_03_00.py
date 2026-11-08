from __future__ import annotations
from typing import Any
from zz.effects import EffectSpec, EffectTiming, build_effect
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row

CARD_ID = "yellow_01_02_03_00"

def _opponent_has_five(source: CardInstance, state: Any, _ctx: Context) -> bool:
    return len(state.players[1 - state.players.index(source.owner)].hand) >= 5

def _draw_one(source: CardInstance, state: Any, _ctx: Context) -> None:
    if state.engine is None:
        raise RuntimeError(f"{CARD_ID} draw effect requires an Engine")
    state.engine.draw(source.owner, 1)

def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.ability_jp = "【メイン】／【フラッシュ】このターン中、自分のミニオン1体をBP+300する。相手の手札が5枚以上の場合、さらに、自分はカードを1枚引く。"
    card.ability_en = "[Main] / [Flash] Give one of your Minions +300BP for this turn. If your opponent has five or more cards in hand, draw one card."
    card.main_timing_ok = card.flash_timing_ok = True
    card.effects.extend([
        build_effect("stat_modifier", EffectTiming.ON_CAST_MAGIC, target_kind="ally_minion",
            min_targets=1, max_targets=1, bp_delta=300, duration="turn",
            official_effect="このターン中、自分のミニオン1体をBP+300する。",
            official_timing="メイン／フラッシュ"),
        EffectSpec(EffectTiming.ON_CAST_MAGIC, _draw_one, condition=_opponent_has_five,
            official_effect="相手の手札が5枚以上の場合、さらに、自分はカードを1枚引く。",
            official_timing="メイン／フラッシュ"),
    ])
    return card
