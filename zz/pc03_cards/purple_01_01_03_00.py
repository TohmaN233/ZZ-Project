from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming, build_effect
from zz.enums import AreaType, CardType, Color
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "purple_01_01_03_00"
EVOKER_RACE = "エヴォーカー"


def _self_summoned_with_qualifying_evoker_mana(
    source: CardInstance,
    state: Any,
    ctx: Context,
) -> bool:
    if ctx.source is not source:
        return False
    if source.area is not AreaType.FIELD:
        raise RuntimeError(f"{CARD_ID} summon effect resolved outside Field: {source.area!r}")
    engine = state.engine
    if engine is None:
        raise RuntimeError(f"{CARD_ID} summon effect requires an Engine")
    return any(
        mana.area is AreaType.BASE
        and mana.card.type in (CardType.B_MINION, CardType.F_MINION)
        and EVOKER_RACE in mana.card.race_jp.split("|")
        and engine._mana_color_of(mana) in (Color.PURPLE, Color.COLORLESS)
        for mana in source.owner.base
    )


def _discard_three_from_deck(source: CardInstance, state: Any, _ctx: Context) -> None:
    engine = state.engine
    if engine is None:
        raise RuntimeError(f"{CARD_ID} summon effect requires an Engine")
    engine.mill_deck(source.owner, 3, source=source)


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.effects.extend([
        EffectSpec(
            EffectTiming.ON_SUMMON,
            _discard_three_from_deck,
            condition=_self_summoned_with_qualifying_evoker_mana,
            official_effect="自分のデッキを上から3枚破棄する。",
            official_timing="召喚時",
            official_condition="自分の種族「エヴォーカー」を持つ、紫または無色のマナがある場合",
        ),
        build_effect(
            "move_to_base_rested",
            EffectTiming.MOVE_TO_BASE,
            official_effect="このミニオンはベースに移動するとき、レスト状態で移動する。",
            official_timing="常時",
        ),
    ])
    return card
