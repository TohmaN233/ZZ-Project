from __future__ import annotations

from copy import copy
from typing import Any

from zz.cards import CARD_REGISTRY
from zz.effects import EffectSpec, EffectTiming
from zz.enums import AreaType, Color
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "colorless_04_02_02r_01"

_ANJU_FORMS = {
    Color.RED: "red_04_02_02r_01",
    Color.YELLOW: "yellow_04_02_02r_01",
    Color.GREEN: "green_04_02_02r_01",
    Color.BLUE: "blue_04_02_02r_02",
    Color.WHITE: "white_04_02_02r_00",
    Color.PURPLE: "purple_04_02_02r_00",
}


def _this_minion_was_summoned(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source


def _this_minion_was_blessed(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source


def _draw_one_card(source: CardInstance, state: Any, _ctx: Context) -> None:
    state.engine.draw(source.owner, 1)


def _metamorphose_from_colored_bless(source: CardInstance, state: Any, ctx: Context) -> None:
    mana = ctx.target
    if not isinstance(mana, CardInstance):
        raise RuntimeError("Anju's Bless trigger has no Bless mana target")
    if mana.area is not AreaType.BLESSING or mana not in source.blessings:
        raise RuntimeError("Anju's Bless target is not attached to this instance")

    engine = state.engine
    mana_color = engine._mana_color_of(mana)
    if mana_color is Color.COLORLESS:
        return

    form_id = _ANJU_FORMS.get(mana_color)
    if form_id is None:
        raise RuntimeError(f"Anju has no form for Bless mana color {mana_color!r}")
    try:
        transformed = copy(CARD_REGISTRY[form_id])
    except KeyError as exc:
        raise RuntimeError(f"Anju form is not registered: {form_id}") from exc

    transformed.cost = dict(transformed.cost)
    transformed.keywords = list(transformed.keywords)
    transformed.effects = list(transformed.effects)
    transformed.triggers = list(transformed.triggers)
    transformed.ignore_bless_conditions = True

    # The printed rule returns this colored mana to Base rested instead of
    # banishing it. Bless detached one Base card, leaving its slot available.
    engine._finish_blessing_return(source, mana)
    engine.transform_card(source, transformed, target=mana)


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.ignore_bless_conditions = True
    card.effects = list(card.effects) + [
        EffectSpec(
            timing=EffectTiming.ON_SUMMON,
            fn=_draw_one_card,
            condition=_this_minion_was_summoned,
            official_effect="カードを1枚引く",
            official_timing="召喚時",
        ),
        EffectSpec(
            timing=EffectTiming.ON_BLESS,
            fn=_metamorphose_from_colored_bless,
            condition=_this_minion_was_blessed,
            official_effect="有色の加護マナをレスト状態でベースに移動し、その色に応じて大変身する",
            official_timing="加護時",
        ),
    ]
    return card
