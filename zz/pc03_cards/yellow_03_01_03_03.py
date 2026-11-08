from __future__ import annotations
from typing import Any
from zz.effects import EffectSpec, EffectTiming, build_effect
from zz.enums import AreaType, CardType, Color
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row

CARD_ID = "yellow_03_01_03_03"
CHIMERA_VORTEX_CARD_ID = "yellow_02_03_01_00"

def _self_transformed(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source and source.area is AreaType.FIELD

def _transform_rewards(source: CardInstance, state: Any, _ctx: Context) -> None:
    engine = state.engine
    if engine is None:
        raise RuntimeError(f"{CARD_ID} transformation effect requires an Engine")
    if source.area is not AreaType.FIELD or source.card.id != CARD_ID:
        raise RuntimeError(f"{CARD_ID} transformation effect resolved before the transformed face was installed")
    engine.add_card_from_outside_to_hand(source.owner, CHIMERA_VORTEX_CARD_ID)

def _opponent_minion_returned(source: CardInstance, state: Any, ctx: Context) -> bool:
    engine = state.engine
    returned = ctx.target
    if engine is None:
        raise RuntimeError(f"{CARD_ID} return trigger requires an Engine")
    if source.area is not AreaType.FIELD or not isinstance(returned, CardInstance) or returned.owner is source.owner or returned.card.type not in (CardType.B_MINION, CardType.F_MINION):
        return False
    move = next((event for event in reversed(engine.zone_move_events) if event.get("card") is returned), None)
    return bool(move and move.get("from") is AreaType.FIELD and move.get("to") in (AreaType.HAND, AreaType.DECK))

def _refresh(source: CardInstance, state: Any, _ctx: Context) -> None:
    if state.engine is None:
        raise RuntimeError(f"{CARD_ID} return trigger requires an Engine")
    state.engine.refresh_target(source)

def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    deck_timing = getattr(EffectTiming, "ON_RETURN_TO_DECK", None)
    if deck_timing is None:
        raise RuntimeError(f"{CARD_ID} requires shared EffectTiming.ON_RETURN_TO_DECK for field-to-deck events")
    card = _card_from_row(row, infer_effects=False)
    card.effects.extend([
        EffectSpec(EffectTiming.ON_TRANSFORM, _transform_rewards, condition=_self_transformed,
            official_effect="「キマイラの旋風」1枚を手札に加える。黄マナ1つをレスト状態でベースに置く。",
            official_timing="変形時", active_areas=(AreaType.FIELD,)),
        EffectSpec(EffectTiming.ON_RETURN_TO_HAND, _refresh, condition=_opponent_minion_returned,
            official_effect="相手のフィールドにいるミニオンが手札またはデッキに戻るたび、このミニオンをアクティブにする。",
            official_timing="常時", active_areas=(AreaType.FIELD,)),
        EffectSpec(deck_timing, _refresh, condition=_opponent_minion_returned,
            official_effect="相手のフィールドにいるミニオンが手札またはデッキに戻るたび、このミニオンをアクティブにする。",
            official_timing="常時", active_areas=(AreaType.FIELD,)),
    ])
    card.effects.append(build_effect(
        "place_colorless_mana", EffectTiming.ON_TRANSFORM,
        condition=_self_transformed, rested=True, mana_color=Color.YELLOW,
        official_effect="黄マナ1つをレスト状態でベースに置く。",
        official_timing="変形時", active_areas=(AreaType.FIELD,),
    ))
    return card
