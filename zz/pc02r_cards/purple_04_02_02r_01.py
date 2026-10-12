from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming
from zz.engine import FIELD_CAP
from zz.enums import AreaType, Color, Keyword
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "purple_04_02_02r_01"


def _dragon_is_in_own_field(source: CardInstance, state: Any, _ctx: Context) -> bool:
    return (
        state.active is source.owner
        and any(
            candidate.card.id.startswith("purple_")
            and "ドラゴン" in candidate.card.race_jp
            for candidate in source.owner.field
        )
    )


def _enter_field_from_trash(source: CardInstance, state: Any, _ctx: Context) -> None:
    return_marker = f"turn:{CARD_ID}:trash_return_used"
    if return_marker in source.owner.flags:
        return
    engine = state.engine
    replacement_iid = None
    if len(source.owner.field) >= FIELD_CAP:
        replacements = engine.select_target(source.owner, "ally_minion", 1, 1, source=source)
        if len(replacements) != 1:
            raise RuntimeError("Dorothy's Trash trigger needs one Field replacement")
        replacement_iid = replacements[0].iid
    source.owner.flags.add(return_marker)
    engine.summon_from_trash(source.owner, source, replace_field_iid=replacement_iid)


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    if Keyword.CANNOT_BLOCK not in card.keywords:
        card.keywords = list(card.keywords) + [Keyword.CANNOT_BLOCK]
    card.effects = list(card.effects) + [
        EffectSpec(
            timing=EffectTiming.TURN_END,
            fn=_enter_field_from_trash,
            condition=_dragon_is_in_own_field,
            active_areas=(AreaType.TRASH,),
            official_effect="自分の紫のドラゴンがいる場合、このカードをトラッシュからフィールドに出す",
            official_timing="自分のターン終了時",
        )
    ]
    return card
