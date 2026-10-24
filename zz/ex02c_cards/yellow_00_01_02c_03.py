from __future__ import annotations

from typing import Any

from zz.effects import EffectTiming, build_effect
from zz.enums import AreaType, Keyword
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "yellow_00_01_02c_03"


def _sword_cost_four_or_more(mana: CardInstance, target: CardInstance, state: Any) -> bool:
    return (
        "ソード" in target.card.race_jp.split("|")
        and sum(target.card.cost.values()) >= 4
    )


def _attached_to_event_host(source: CardInstance, state: Any, ctx: Context) -> bool:
    host = ctx.source
    return (
        isinstance(host, CardInstance)
        and host.owner is source.owner
        and host.area is AreaType.FIELD
        and source in host.blessings
    )


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    if Keyword.KAGO not in card.keywords:
        card.keywords.append(Keyword.KAGO)
    card.bless_condition = _sword_cost_four_or_more
    card.effects.extend([
        build_effect(
            "return_to_hand",
            timing=EffectTiming.ON_ATTACK,
            condition=_attached_to_event_host,
            target_kind="enemy_minion",
            min_targets=1,
            max_targets=1,
            max_bp=400,
            official_effect="相手のBP400以下のミニオン1体を手札に戻す。",
            official_timing="アタック時",
            active_areas=(AreaType.BLESSING,),
        ),
        build_effect(
            "return_to_hand",
            timing=EffectTiming.ON_BLOCK,
            condition=_attached_to_event_host,
            target_kind="enemy_minion",
            min_targets=1,
            max_targets=1,
            max_bp=400,
            official_effect="相手のBP400以下のミニオン1体を手札に戻す。",
            official_timing="ブロック時",
            active_areas=(AreaType.BLESSING,),
        ),
    ])
    return card
