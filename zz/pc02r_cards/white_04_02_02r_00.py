from __future__ import annotations

from copy import copy
from typing import Any

from zz.cards import CARD_REGISTRY
from zz.effects import EffectSpec, EffectTiming
from zz.enums import AreaType, Color
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "white_04_02_02r_00"

_ANJU_FORMS = {
    Color.RED: "red_04_02_02r_01",
    Color.YELLOW: "yellow_04_02_02r_01",
    Color.GREEN: "green_04_02_02r_01",
    Color.BLUE: "blue_04_02_02r_02",
    Color.WHITE: CARD_ID,
    Color.PURPLE: "purple_04_02_02r_00",
}
_ANJU_COLORS_BY_ID = {card_id: color for color, card_id in _ANJU_FORMS.items()}


def _this_minion_was_blessed(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source


def _this_minion_won_a_minion_battle(source: CardInstance, _state: Any, ctx: Context) -> bool:
    target = ctx.target
    return (
        ctx.source is source
        and isinstance(target, CardInstance)
        and target.owner is not source.owner
    )


def _banish_off_color_bless(source: CardInstance, state: Any, ctx: Context) -> None:
    mana = ctx.target
    if not isinstance(mana, CardInstance):
        raise RuntimeError("Anju's Bless trigger has no Bless mana target")
    if mana.area is not AreaType.BLESSING or mana not in source.blessings:
        raise RuntimeError("Anju's Bless target is not attached to this instance")

    engine = state.engine
    mana_color = engine._mana_color_of(mana)
    current_color = _ANJU_COLORS_BY_ID.get(source.card.id)
    if current_color is None:
        raise RuntimeError(f"Anju form has no printed color mapping: {source.card.id}")
    if mana_color in (Color.COLORLESS, current_color):
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

    source.blessings.remove(mana)
    engine._reset_card_zone_state(mana)
    mana.area = AreaType.REMOVED
    mana.owner.removed.append(mana)
    engine._record_zone_move(mana, AreaType.BLESSING, AreaType.REMOVED)
    engine.transform_card(source, transformed, target=mana)


def _banish_battle_loser(source: CardInstance, state: Any, ctx: Context) -> None:
    target = ctx.target
    if not isinstance(target, CardInstance):
        raise RuntimeError("Anju's battle-win effect requires a Minion target")
    if target.owner is source.owner or target.area is not AreaType.FIELD:
        raise RuntimeError("Anju's battle-win target is not an opposing Field Minion")

    state.engine.banish_target(target, source=source)


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.ignore_bless_conditions = True
    card.effects = list(card.effects) + [
        EffectSpec(
            timing=EffectTiming.ON_BLESS,
            fn=_banish_off_color_bless,
            condition=_this_minion_was_blessed,
            official_effect="白以外の有色の加護マナを除外し、その色に応じて大変身する",
            official_timing="加護時",
        ),
        EffectSpec(
            timing=EffectTiming.ON_BATTLE_WIN,
            fn=_banish_battle_loser,
            condition=_this_minion_won_a_minion_battle,
            official_effect="ミニオンとのバトルに勝利するたび、相手のミニオンをゲームから除外する",
            official_timing="常時",
        ),
    ]
    return card
