from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming
from zz.enums import AreaType, CardType
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "purple_05_01_03_01"


def _self_destroyed(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.target is source and source.area is AreaType.TRASH


def _opponent_chooses_own_minion_to_destroy(source: CardInstance, state: Any, _ctx: Context) -> None:
    engine = state.engine
    if engine is None:
        raise RuntimeError(f"{CARD_ID} destruction effect requires an Engine")
    opponent = state.players[1 - state.players.index(source.owner)]
    targets = engine.select_target(
        opponent,
        "ally_minion",
        1,
        1,
        filter_fn=lambda target: target.card.type in (CardType.F_MINION, CardType.B_MINION),
        source=source,
    )
    if targets:
        engine.destroy_target(targets[0], source=source)


def _self_returned_from_own_trash(source: CardInstance, state: Any, ctx: Context) -> bool:
    engine = state.engine
    if engine is None:
        raise RuntimeError(f"{CARD_ID} return effect requires an Engine")
    if ctx.target is not source or source.area is not AreaType.HAND:
        return False
    movement = next(
        (event for event in reversed(engine.zone_move_events) if event.get("card") is source),
        None,
    )
    return bool(
        movement
        and movement.get("from") is AreaType.TRASH
        and movement.get("to") is AreaType.HAND
    )


def _put_self_on_field(source: CardInstance, state: Any, _ctx: Context) -> None:
    engine = state.engine
    if engine is None:
        raise RuntimeError(f"{CARD_ID} return effect requires an Engine")
    player = source.owner
    from zz.engine import FIELD_CAP

    replace_field_iid = None
    if len(player.field) >= FIELD_CAP:
        replacements = engine.select_target(player, "ally_minion", 1, 1, source=source)
        if not replacements:
            raise RuntimeError(f"{CARD_ID} requires a field replacement at capacity")
        replace_field_iid = replacements[0].iid
    engine.put_field_minion_from_hand(
        player,
        source,
        rested=False,
        replace_field_iid=replace_field_iid,
    )


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.effects.extend(
        [
            EffectSpec(
                EffectTiming.ON_DESTROY,
                _opponent_chooses_own_minion_to_destroy,
                condition=_self_destroyed,
                target_kind="ally_minion",
                min_targets=1,
                max_targets=1,
                params={"target_chooser": "opponent"},
                official_effect="相手のミニオン1体を、相手が選んで破壊する。",
                official_timing="破壊時",
            ),
            EffectSpec(
                EffectTiming.ON_RETURN_TO_HAND,
                _put_self_on_field,
                condition=_self_returned_from_own_trash,
                active_areas=(AreaType.HAND,),
                params={"source_enters_field": True},
                official_effect="自分のトラッシュからこのカードを手札に戻す場合、このミニオンを出す。",
                official_timing="トラッシュから手札に戻る時",
            ),
        ]
    )
    return card
