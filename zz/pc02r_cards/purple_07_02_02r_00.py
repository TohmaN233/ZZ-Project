from __future__ import annotations

from copy import copy
from typing import Any

from zz.cards import CARD_REGISTRY
from zz.effects import EffectSpec, EffectTiming
from zz.enums import AreaType, Color
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "purple_07_02_02r_00"
_TRANSFORMED_FORM_ID = "purple_07_02_02r_01"


def _self_summoned(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source


def _self_blessed(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source


def _damage_one_opposing_force(source: CardInstance, state: Any, _ctx: Context) -> None:
    engine = state.engine
    opponent = state.players[1 - state.players.index(source.owner)]
    if not any(not force.destroyed for force in opponent.forces):
        return
    targets = engine.select_target(source.owner, "enemy_force", 1, 1, source=source)
    if len(targets) != 1:
        raise RuntimeError(f"{CARD_ID} expected one opposing Force, got {len(targets)}")
    engine._damage_force(targets[0], 2, source=source)


def _transform_with_purple_bless(source: CardInstance, state: Any, ctx: Context) -> None:
    mana = ctx.target
    if not isinstance(mana, CardInstance):
        raise RuntimeError(f"{CARD_ID} Boost trigger has no Mana target")
    engine = state.engine
    if engine._mana_color_of(mana) is not Color.PURPLE:
        return
    if mana.area is not AreaType.BLESSING or mana not in source.blessings:
        raise RuntimeError(f"{CARD_ID} Purple Boost mana is no longer attached")
    try:
        transformed = copy(CARD_REGISTRY[_TRANSFORMED_FORM_ID])
    except KeyError as exc:
        raise RuntimeError(
            f"{CARD_ID} transformed face is not registered: {_TRANSFORMED_FORM_ID}"
        ) from exc
    transformed.cost = dict(transformed.cost)
    transformed.keywords = list(transformed.keywords)
    transformed.effects = list(transformed.effects)
    transformed.triggers = list(transformed.triggers)

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
    card.can_bless_while_rested = False
    card.effects = list(card.effects) + [
        EffectSpec(
            timing=EffectTiming.ON_SUMMON,
            fn=_damage_one_opposing_force,
            condition=_self_summoned,
            target_kind="enemy_force",
            min_targets=1,
            max_targets=1,
            official_effect="相手のフォース1つに2ダメージを与える",
            official_timing="召喚時",
        ),
        EffectSpec(
            timing=EffectTiming.ON_BLESS,
            fn=_transform_with_purple_bless,
            condition=_self_blessed,
            official_effect="紫の加護マナを除外し、常闇狼鬼アンフェールに変形する",
            official_timing="加護時",
        ),
    ]
    return card
