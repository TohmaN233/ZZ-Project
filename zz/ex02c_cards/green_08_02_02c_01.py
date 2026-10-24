from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming
from zz.enums import AreaType
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "green_08_02_02c_01"


def _self_transformed(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source


def _activate_sword_mana(source: CardInstance, state: Any, _ctx: Context) -> None:
    engine = state.engine
    for mana in list(source.owner.base):
        if "ソード" in mana.card.race_jp.split("|"):
            engine.refresh_target(mana)


def _destroyed_or_switch_trigger(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.target is source or getattr(ctx, "switch_source", None) is source


def _prevent_opponent_minion_refresh(source: CardInstance, state: Any, _ctx: Context) -> None:
    engine = state.engine
    opponent = state.players[1 - state.players.index(source.owner)]
    for minion in list(opponent.field):
        engine.prevent_next_refresh(minion)


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.deck_buildable = False
    card.effects.extend([
        EffectSpec(
            timing=EffectTiming.ON_TRANSFORM,
            fn=_activate_sword_mana,
            condition=_self_transformed,
            official_effect="自分の種族「ソード」を持つマナ全てをアクティブにする。",
            official_timing="変形時",
            active_areas=(AreaType.FIELD,),
        ),
        EffectSpec(
            timing=EffectTiming.ON_DESTROY,
            fn=_prevent_opponent_minion_refresh,
            condition=_destroyed_or_switch_trigger,
            target_kind="enemy_minion",
            min_targets=1,
            max_targets=5,
            params={
                "all_targets": True,
                "ex02c_switch_races": ["黒の剣士"],
            },
            official_effect=(
                "相手のミニオン全ては、次の相手のスタンバイフェイズ終了時まで、"
                "アクティブにならない。"
            ),
            official_timing="破壊時＆スイッチ",
            official_condition="スイッチ：「黒の剣士」",
            active_areas=(AreaType.FIELD, AreaType.TRASH),
        ),
    ])
    return card
