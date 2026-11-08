from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming
from zz.enums import AreaType, CardType, Color
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "green_05_01_03_02"


def _self_source(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source


def _banish_enemy_neutral_minion(source: CardInstance, state: Any, _ctx: Context) -> None:
    engine = state.engine
    if engine is None:
        raise RuntimeError(f"{CARD_ID} summon effect requires an Engine")
    targets = engine.select_target(source.owner, "enemy_minion", 1, 1, source=source)
    for target in targets:
        engine.banish_target(target, source=source, effect_controller=source.owner)


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.effects.append(
        EffectSpec(
            EffectTiming.ON_SUMMON,
            _banish_enemy_neutral_minion,
            condition=_self_source,
            target_kind="enemy_minion",
            params={"color": Color.COLORLESS, "card_type": CardType.F_MINION},
            official_effect="相手の無色のミニオン1体を除外する。",
            official_timing="召喚時",
            active_areas=(AreaType.FIELD,),
        )
    )
    return card
