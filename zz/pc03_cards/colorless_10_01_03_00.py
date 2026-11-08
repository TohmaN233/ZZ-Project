from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming
from zz.enums import AreaType, CardType, Color
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = 'colorless_10_01_03_00'


def _self_summoned(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source


def _destroy_non_minion_colorless_mana(source: CardInstance, state: Any, _ctx: Context) -> None:
    engine = state.engine
    if engine is None:
        raise RuntimeError(f"{CARD_ID} summon effect requires an Engine")
    targets = [
        mana
        for player in state.players
        for mana in list(player.base)
        if mana.card.type not in (CardType.F_MINION, CardType.B_MINION)
        and engine._mana_color_of(mana) is Color.COLORLESS
    ]
    for mana in targets:
        engine.destroy_target(mana, source=source)


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.effects.append(
        EffectSpec(
            EffectTiming.ON_SUMMON,
            _destroy_non_minion_colorless_mana,
            condition=_self_summoned,
            official_effect="お互いのミニオンカードでない無色マナ全てを破壊する。",
            official_timing="召喚時",
            active_areas=(AreaType.FIELD,),
        )
    )
    return card
