from __future__ import annotations

from copy import copy
from typing import Any

from zz.cards import CARD_REGISTRY
from zz.effects import EffectSpec, EffectTiming
from zz.enums import AreaType, Color
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "red_04_02_02r_01"

_ANJU_FORMS = {
    Color.RED: CARD_ID,
    Color.YELLOW: "yellow_04_02_02r_01",
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


def _this_anju_was_blocked_on_its_turn(source, state, ctx: Context) -> bool:
    return ctx.target is source and state.active is source.owner


def _deal_one_life_damage(source, state, ctx: Context) -> None:
    opponent = state.players[1 - state.players.index(source.owner)]
    state.engine._damage_player(opponent, 1, source=source, damage_kind="effect")


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.ignore_bless_conditions = True
    card.effects.extend(
        [
            EffectSpec(
                timing=EffectTiming.ON_BLESS,
                fn=_metamorphose_from_bless,
                condition=_self_blessed,
                active_areas=(AreaType.FIELD,),
                official_effect="赤以外の有色の加護なら、そのマナを除外して加護色のアンジュに大変身する",
                official_timing="加護時",
            ),
            EffectSpec(
                timing=EffectTiming.ON_BLOCK,
                fn=_deal_one_life_damage,
                condition=_this_anju_was_blocked_on_its_turn,
                active_areas=(AreaType.FIELD,),
                official_effect="自分のターンにこのミニオンの攻撃がブロックされた時、相手プレイヤーに1ダメージを与える",
                official_timing="自分のターン",
            ),
        ]
    )
    return card
