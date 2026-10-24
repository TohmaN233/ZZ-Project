from __future__ import annotations

from typing import Any

from zz.effects import EffectTiming, build_effect
from zz.enums import AreaType
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "red_02_02_02c_00"


def _this_minion_was_destroyed(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.target is source or ctx.switch_source is source


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.effects = list(card.effects) + [
        build_effect(
            "stat_modifier",
            EffectTiming.ON_DESTROY,
            condition=_this_minion_was_destroyed,
            target_kind="ally_minion",
            min_targets=1,
            max_targets=1,
            bp_delta=200,
            duration="permanent",
            race="黒の剣士",
            ex02c_switch_races=["黒の剣士"],
            active_areas=(AreaType.FIELD, AreaType.TRASH),
            official_effect="自分の種族「黒の剣士」を持つミニオン1体にBP+200を付与する",
            official_timing="破壊時",
            official_condition="スイッチ：「黒の剣士」",
        )
    ]
    return card
