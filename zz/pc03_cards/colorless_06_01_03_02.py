from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming
from zz.enums import AreaType, CardType, Color
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "colorless_06_01_03_02"
_PENDING_COLOR_PREFIX = "pending_mana_color:"


def _self_source_with_neutral_mana(source: CardInstance, state: Any, ctx: Context) -> bool:
    if ctx.source is not source or source.area is not AreaType.FIELD:
        return False
    engine = state.engine
    if engine is None:
        raise RuntimeError(f"{CARD_ID} condition requires an Engine")
    return any(
        mana.card.type is CardType.MANA_TOKEN
        and engine._mana_color_of(mana) is Color.COLORLESS
        for mana in source.owner.base
    )


def _change_all_own_neutral_non_minion_mana(
    source: CardInstance,
    state: Any,
    _ctx: Context,
) -> None:
    engine = state.engine
    if engine is None:
        raise RuntimeError(f"{CARD_ID} color change requires an Engine")
    pending = [
        flag[len(_PENDING_COLOR_PREFIX):]
        for flag in source.flags
        if flag.startswith(_PENDING_COLOR_PREFIX)
    ]
    if len(pending) != 1:
        raise RuntimeError(f"{CARD_ID} expected one pending mana color, found {pending!r}")
    try:
        color = Color[pending[0]]
    except KeyError as exc:
        raise RuntimeError(f"{CARD_ID} received invalid pending mana color {pending[0]!r}") from exc
    pending_flags = [
        flag for flag in source.flags if flag.startswith(_PENDING_COLOR_PREFIX)
    ]
    source.flags.difference_update(pending_flags)
    for mana in source.owner.base:
        if (
            mana.card.type is CardType.MANA_TOKEN
            and engine._mana_color_of(mana) is Color.COLORLESS
        ):
            mana.mana_color_override = color


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.effects.append(
        EffectSpec(
            EffectTiming.ON_SUMMON,
            _change_all_own_neutral_non_minion_mana,
            condition=_self_source_with_neutral_mana,
            params={"choose_mana_color": True},
            official_effect="ミニオンカードでない無色マナがある場合、色を1つ選択する。自分のミニオンカードでない無色マナ全てを、選択した色に変更する。",
            official_timing="召喚時",
            active_areas=(AreaType.FIELD,),
        )
    )
    return card
