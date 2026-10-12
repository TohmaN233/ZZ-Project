from __future__ import annotations

from copy import copy
from typing import Any

from zz.cards import CARD_REGISTRY
from zz.effects import EffectSpec, EffectTiming
from zz.enums import AreaType, CardType, Color
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "red_07_02_02r_00"
_TRANSFORMED_FORM_ID = "red_07_02_02r_01"


def _this_minion_was_summoned(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source


def _this_minion_received_red_bless(source: CardInstance, state: Any, ctx: Context) -> bool:
    if ctx.source is not source or source.rested:
        return False
    mana = ctx.target
    return (
        isinstance(mana, CardInstance)
        and state.engine._mana_color_of(mana) is Color.RED
    )


def _weaken_one_opponent_on_summon(source: CardInstance, state: Any, _ctx: Context) -> None:
    engine = state.engine
    targets = engine.select_target(source.owner, "enemy_minion", 1, 1, source=source)
    if not targets:
        return
    engine.modify_stat(targets[0], bp_delta=-500, duration="turn")


def _banish_red_bless_and_transform(source: CardInstance, state: Any, ctx: Context) -> None:
    mana = ctx.target
    if not isinstance(mana, CardInstance):
        raise RuntimeError("Flare Zaura's red Bless trigger requires its attached Mana target")
    if mana not in source.blessings or mana.area is not AreaType.BLESSING:
        raise RuntimeError("Flare Zaura's red Bless target is no longer attached")
    if state.engine._mana_color_of(mana) is not Color.RED:
        raise RuntimeError("Flare Zaura's red Bless trigger received non-red Mana")

    try:
        transformed = copy(CARD_REGISTRY[_TRANSFORMED_FORM_ID])
    except KeyError as exc:
        raise RuntimeError(f"Flare Zaura transformed form is not registered: {_TRANSFORMED_FORM_ID}") from exc
    transformed.cost = dict(transformed.cost)
    transformed.keywords = list(transformed.keywords)
    transformed.effects = list(transformed.effects)
    transformed.triggers = list(transformed.triggers)

    engine = state.engine
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
    card.effects = list(card.effects) + [
        EffectSpec(
            timing=EffectTiming.ON_SUMMON,
            fn=_weaken_one_opponent_on_summon,
            condition=_this_minion_was_summoned,
            target_kind="enemy_minion",
            min_targets=1,
            max_targets=1,
            official_effect="相手のミニオン1体にこのターンBP-500を与える",
            official_timing="召喚時",
        ),
        EffectSpec(
            timing=EffectTiming.ON_BLESS,
            fn=_banish_red_bless_and_transform,
            condition=_this_minion_received_red_bless,
            active_areas=(AreaType.FIELD,),
            official_effect="赤の加護マナを除外し、フレイザウラーへ変形する",
            official_timing="加護時",
            official_condition="赤の加護",
        ),
    ]
    return card
