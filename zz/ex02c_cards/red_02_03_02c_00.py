from __future__ import annotations

from typing import Any

from zz.effects import EffectTiming, build_effect
from zz.enums import AreaType
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "red_02_03_02c_00"


def _zero_cost_if_black_swordsman_or_flash_is_present(
    source: CardInstance,
    target: CardInstance,
    state: Any,
):
    if source is not target or source.area is not AreaType.HAND:
        return 0
    if any(
        {"黒の剣士", "閃光"}.intersection(ci.card.race_jp.split("|"))
        for ci in source.owner.field
    ):
        # An empty mapping is an explicit full-cost override. Engine support is
        # required because the current integer cost_aura only lowers free cost.
        return {}
    return 0


def _this_magic_was_cast(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.cost_aura = _zero_cost_if_black_swordsman_or_flash_is_present
    card.effects = list(card.effects) + [
        build_effect(
            "stat_modifier",
            EffectTiming.ON_CAST_MAGIC,
            condition=_this_magic_was_cast,
            target_kind="ally_minion",
            min_targets=1,
            max_targets=1,
            bp_delta=300,
            duration="turn",
            active_areas=(AreaType.TRASH,),
            official_effect="このターン中、自分のミニオン1体をBP+300する",
            official_timing="メイン/フラッシュ",
        )
    ]
    return card
