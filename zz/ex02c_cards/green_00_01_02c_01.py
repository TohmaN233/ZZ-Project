from __future__ import annotations

from typing import Any

from zz.effects import EffectTiming, build_effect
from zz.enums import AreaType, Keyword
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "green_00_01_02c_01"


def _cost_four_or_more(mana: CardInstance, target: CardInstance, _state: Any) -> bool:
    return sum(target.card.cost.values()) >= 4


def _host_is_attacking(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return (
        source.area is AreaType.BLESSING
        and any(source in host.blessings and host is ctx.source for host in source.owner.field)
    )


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    if Keyword.KAGO not in card.keywords:
        card.keywords.append(Keyword.KAGO)
    card.bless_condition = _cost_four_or_more
    card.effects.append(
        build_effect(
            "stat_modifier",
            EffectTiming.ON_ATTACK,
            condition=_host_is_attacking,
            target_kind="enemy_minion",
            min_targets=1,
            max_targets=1,
            bp_delta=-400,
            duration="turn",
            only_rested=True,
            active_areas=(AreaType.BLESSING,),
            official_effect="このターン中、相手のレスト状態であるミニオン1体をBP-400する。",
            official_timing="アタック時",
        )
    )
    return card
