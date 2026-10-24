from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming
from zz.enums import AreaType
from zz.model import CardInstance, Context
from zz.card_identity import explicitly_equivalent_card_ids
from zz.pc01 import _card_from_row


CARD_ID = "colorless_08_02_02c_00"

def _is_sword_golem(card: CardInstance) -> bool:
    return (
        card.card.id == CARD_ID
        or explicitly_equivalent_card_ids(card.card.id, CARD_ID)
    )


def _this_card_was_destroyed(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.target is source and source.area is AreaType.TRASH


def _return_due_marker(state: Any) -> str:
    return f"turn:ex02c_sword_golem_return:{state.turn}:{state.active_idx}"


def _mark_sword_golem_return(source: CardInstance, state: Any, _ctx: Context) -> None:
    source.flags.add(_return_due_marker(state))


def _return_is_due(source: CardInstance, state: Any, ctx: Context) -> bool:
    return (
        ctx.controller is state.active
        and source.area is AreaType.TRASH
        and _return_due_marker(state) in source.flags
    )


def _return_sword_golem_to_hand(source: CardInstance, state: Any, _ctx: Context) -> None:
    marker = _return_due_marker(state)
    eligible = state.engine._eligible_targets(
        source.owner,
        "trash_minion",
        filter_fn=_is_sword_golem,
        source=source,
    )
    source.flags.discard(marker)
    if not eligible:
        return
    selected = state.engine.select_target(
        source.owner,
        "trash_minion",
        1,
        1,
        filter_fn=_is_sword_golem,
        source=source,
    )
    if len(selected) != 1:
        raise RuntimeError(f"{CARD_ID} expected one Sword Golem from Trash, got {len(selected)}")
    state.engine.add_to_hand(source.owner, selected[0], from_area=AreaType.TRASH)


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.effects = list(card.effects) + [
        EffectSpec(
            timing=EffectTiming.ON_DESTROY,
            fn=_mark_sword_golem_return,
            condition=_this_card_was_destroyed,
            active_areas=(AreaType.TRASH,),
            official_effect="このターン終了時、自分のトラッシュにある「ソードゴーレム」1枚を手札に戻す。",
            official_timing="破壊時",
        ),
        EffectSpec(
            timing=EffectTiming.TURN_END,
            fn=_return_sword_golem_to_hand,
            condition=_return_is_due,
            target_kind="trash_minion",
            min_targets=1,
            max_targets=1,
            params={"explicitly_equivalent_to": CARD_ID},
            active_areas=(AreaType.TRASH,),
            official_effect="自分のトラッシュにある「ソードゴーレム」1枚を手札に戻す。",
            official_timing="このターン終了時",
        )
    ]
    return card
