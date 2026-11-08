from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming, build_effect
from zz.enums import AreaType, CardType
from zz.model import CardInstance, Context, Player
from zz.pc01 import _card_from_row


CARD_ID = "yellow_06_01_03_03"


def _self_summoned(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source and source.area is AreaType.FIELD


def _self_attacked(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source and source.area is AreaType.FIELD


def _avian_attacks_player(source: CardInstance, state: Any, ctx: Context) -> bool:
    attacker = ctx.source
    return (
        source.area is AreaType.FIELD
        and state.active is source.owner
        and ctx.controller is source.owner
        and isinstance(attacker, CardInstance)
        and attacker.owner is source.owner
        and attacker.area is AreaType.FIELD
        and attacker.card.type is CardType.F_MINION
        and "アヴィアン" in attacker.card.race_jp.split("|")
        and isinstance(ctx.target, Player)
        and ctx.target is not source.owner
    )


def _refresh_self(source: CardInstance, state: Any, _ctx: Context) -> None:
    engine = state.engine
    if engine is None:
        raise RuntimeError(f"{CARD_ID} refresh effect requires an Engine")
    engine.refresh_target(source)


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.effects.extend(
        [
            EffectSpec(
                EffectTiming.CONTINUOUS,
                lambda source, state, ctx: None,
                params={"pc03_return_to_deck_replacement": True},
                official_effect="相手のミニオンが自分の効果で手札に戻るとき、代わりに相手のデッキの下に戻す。",
                official_timing="常時",
                active_areas=(AreaType.FIELD,),
            ),
            build_effect(
                "return_to_hand",
                EffectTiming.ON_ATTACK,
                target_kind="enemy_minion",
                max_bp=400,
                official_effect="相手のBP400以下のミニオン1体を手札に戻す。",
                official_timing="アタック時",
            ),
            EffectSpec(
                EffectTiming.ON_ATTACK,
                _refresh_self,
                condition=_avian_attacks_player,
                official_effect="自分のターン中、自分の「アヴィアン」が相手プレイヤーにアタックしたとき、このミニオンをアクティブにする。",
                official_timing="常時",
                active_areas=(AreaType.FIELD,),
            ),
        ]
    )
    return card
