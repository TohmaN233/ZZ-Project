from __future__ import annotations

from copy import copy
from typing import Any

from zz.cards import CARD_REGISTRY
from zz.effects import EffectSpec, EffectTiming
from zz.enums import AreaType, Color
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "purple_04_02_02r_00"

_ANJU_FORMS = {
    Color.RED: "red_04_02_02r_01",
    Color.YELLOW: "yellow_04_02_02r_01",
    Color.GREEN: "green_04_02_02r_01",
    Color.BLUE: "blue_04_02_02r_02",
    Color.WHITE: "white_04_02_02r_00",
    Color.PURPLE: CARD_ID,
}
_ANJU_COLORS_BY_ID = {card_id: color for color, card_id in _ANJU_FORMS.items()}


def _this_minion_attacks(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source


def _this_minion_was_blessed(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source


def _discard_top_card(state: Any, player: Any) -> None:
    if not player.deck:
        return
    engine = state.engine
    card = player.deck.pop(0)
    engine._reset_card_zone_state(card)
    card.area = AreaType.TRASH
    player.trash.append(card)
    engine._record_zone_move(card, AreaType.DECK, AreaType.TRASH)
    engine.triggers.emit(
        EffectTiming.ON_DECK_DISCARD,
        Context(controller=player, source=card),
    )
    engine.triggers.resolve_all()


def _discard_both_decks(source: CardInstance, state: Any, _ctx: Context) -> None:
    _discard_top_card(state, source.owner)
    opponent = state.players[1 - state.players.index(source.owner)]
    _discard_top_card(state, opponent)


def _banish_off_color_bless(source: CardInstance, state: Any, ctx: Context) -> None:
    mana = ctx.target
    if not isinstance(mana, CardInstance):
        raise RuntimeError("Anju's Bless trigger has no Bless mana target")
    engine = state.engine
    mana_color = engine._mana_color_of(mana)
    current_color = _ANJU_COLORS_BY_ID.get(source.card.id)
    if current_color is None:
        raise RuntimeError(f"Anju form has no printed color mapping: {source.card.id}")
    if mana_color in (Color.COLORLESS, current_color):
        return
    if mana.area is not AreaType.BLESSING or mana not in source.blessings:
        raise RuntimeError("Anju's off-color Bless mana is no longer attached")

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


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.ignore_bless_conditions = True
    card.effects = list(card.effects) + [
        EffectSpec(
            timing=EffectTiming.ON_ATTACK,
            fn=_discard_both_decks,
            condition=_this_minion_attacks,
            official_effect="自分と相手のデッキの上から1枚ずつ破棄する",
            official_timing="アタック時",
        ),
        EffectSpec(
            timing=EffectTiming.ON_BLESS,
            fn=_banish_off_color_bless,
            condition=_this_minion_was_blessed,
            official_effect="紫以外の有色の加護マナを除外し、その色に応じて大変身する",
            official_timing="加護時",
        ),
    ]
    return card
