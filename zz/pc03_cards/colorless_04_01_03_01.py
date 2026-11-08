from __future__ import annotations

from typing import Any

from zz.effects import EffectTiming, build_effect
from zz.enums import AreaType
from zz.model import CardInstance
from zz.pc01 import _card_from_row


CARD_ID = "colorless_04_01_03_01"
BLOCKING_RACES = frozenset({"ドラゴン", "ドラゴニュート"})


def _swamp_dragon_block_filter(
    source: CardInstance,
    target: CardInstance,
    action: str,
    state: Any,
) -> bool:
    if (
        source.card.id != CARD_ID
        or source.area is not AreaType.FIELD
        or action != "block"
        or state.active is not source.owner
        or target.owner is source.owner
        or target.area is not AreaType.FIELD
    ):
        return False
    return not BLOCKING_RACES.intersection(target.card.race_jp.split("|"))


def _self_source(source: CardInstance, _state: Any, ctx) -> bool:
    return ctx.source is source


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.blocker_restriction = lambda attacker, blocker, state: _swamp_dragon_block_filter(attacker, blocker, "block", state)
    return card
