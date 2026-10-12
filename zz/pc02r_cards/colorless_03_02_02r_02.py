from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming
from zz.enums import AreaType
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "colorless_03_02_02r_02"


def _this_minion_was_destroyed(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.target is source


def _grant_next_life_damage_shield_and_banish(
    source: CardInstance,
    state: Any,
    _ctx: Context,
) -> None:
    engine = state.engine
    prevent_next = getattr(engine, "prevent_next_player_life_damage", None)
    if not callable(prevent_next):
        raise RuntimeError(
            f"{CARD_ID} requires Engine.prevent_next_player_life_damage(player)"
        )
    prevent_next(source.owner)
    if source.area is not AreaType.TRASH or source not in source.owner.trash:
        raise RuntimeError(f"{CARD_ID} must be in its owner's Trash after destruction")
    owner = source.owner
    owner.trash.remove(source)
    engine._reset_card_zone_state(source)
    source.area = AreaType.REMOVED
    owner.removed.append(source)
    engine._record_zone_move(source, AreaType.TRASH, AreaType.REMOVED)


def _cannot_be_selected_while_in_trash(
    target: CardInstance,
    _source: CardInstance | None = None,
    _state: Any = None,
) -> bool:
    return target.area is not AreaType.TRASH


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    # Engine._can_effect_select must consult this predicate for this CardInstance.
    card.effect_targetable = _cannot_be_selected_while_in_trash
    card.effects = list(card.effects) + [
        EffectSpec(
            timing=EffectTiming.ON_DESTROY,
            fn=_grant_next_life_damage_shield_and_banish,
            condition=_this_minion_was_destroyed,
            official_effect="自分のプレイヤーが次に受けるLifeへのダメージを0にし、このミニオンを除外する",
            official_timing="破壊時",
        )
    ]
    return card

