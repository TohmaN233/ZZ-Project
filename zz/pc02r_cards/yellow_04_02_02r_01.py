from __future__ import annotations

from copy import copy
from typing import Any

from zz.cards import CARD_REGISTRY
from zz.effects import EffectSpec, EffectTiming
from zz.enums import AreaType, Color
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "yellow_04_02_02r_01"

_ANJU_FORMS = {
    Color.RED: "red_04_02_02r_01",
    Color.YELLOW: CARD_ID,
    Color.GREEN: "green_04_02_02r_01",
    Color.BLUE: "blue_04_02_02r_02",
    Color.WHITE: "white_04_02_02r_00",
    Color.PURPLE: "purple_04_02_02r_00",
}


def _card_color(card) -> Color:
    if card.printed_color is not None:
        return card.printed_color
    if card.mana_color is not None:
        return card.mana_color
    return next((color for color in card.cost if color is not Color.COLORLESS), Color.COLORLESS)


def _mana_color(mana: CardInstance) -> Color:
    if mana.mana_color_override is not None:
        return mana.mana_color_override
    return _card_color(mana.card)


def _self_blessed(source, state, ctx: Context) -> bool:
    return ctx.source is source


def _metamorphose_from_bless(source, state, ctx: Context) -> None:
    mana = ctx.target
    if not isinstance(mana, CardInstance):
        raise RuntimeError("Anju's Bless trigger requires its attached Mana target")
    if mana not in source.blessings or mana.area is not AreaType.BLESSING:
        raise RuntimeError("Anju's Bless target is not attached to this instance")

    color = _mana_color(mana)
    current_color = _card_color(source.card)
    form_id = _ANJU_FORMS.get(color)
    if color is current_color or form_id is None:
        return
    try:
        transformed = copy(CARD_REGISTRY[form_id])
    except KeyError as exc:
        raise RuntimeError(f"Anju form is not registered: {form_id}") from exc

    transformed.cost = dict(transformed.cost)
    transformed.keywords = list(transformed.keywords)
    transformed.effects = list(transformed.effects)
    transformed.triggers = list(transformed.triggers)
    transformed.ignore_bless_conditions = True

    engine = state.engine
    source.blessings.remove(mana)
    engine._reset_card_zone_state(mana)
    mana.area = AreaType.REMOVED
    mana.owner.removed.append(mana)
    engine._record_zone_move(mana, AreaType.BLESSING, AreaType.REMOVED)
    engine.transform_card(source, transformed, target=mana)


def _thunder_aura(source, target, state) -> tuple[int, int]:
    if source is not target or source.area is not AreaType.FIELD:
        return 0, 0
    if any(
        summoned.owner is source.owner and summoned is not source
        for summoned in state.summoned_this_turn
    ):
        return 200, 1
    return 0, 0


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.ignore_bless_conditions = True
    previous_aura = card.aura

    def combined_aura(source, target, state) -> tuple[int, int]:
        bp_delta, dp_delta = previous_aura(source, target, state) if previous_aura else (0, 0)
        thunder_bp, thunder_dp = _thunder_aura(source, target, state)
        return bp_delta + thunder_bp, dp_delta + thunder_dp

    card.aura = combined_aura
    card.effects.append(
        EffectSpec(
            timing=EffectTiming.ON_BLESS,
            fn=_metamorphose_from_bless,
            condition=_self_blessed,
            active_areas=(AreaType.FIELD,),
            official_effect="黄以外の有色の加護なら、そのマナを除外して加護色のアンジュに大変身する",
            official_timing="加護時",
        )
    )
    return card
