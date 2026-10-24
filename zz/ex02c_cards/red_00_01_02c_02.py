from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming
from zz.enums import AreaType, Keyword
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "red_00_01_02c_02"


def _sword_cost_four_or_more(mana: CardInstance, target: CardInstance, _state: Any) -> bool:
    return (
        "ソード" in target.card.race_jp.split("|")
        and sum(target.card.cost.values()) >= 4
    )


def _boost_host(source: CardInstance) -> CardInstance | None:
    return next(
        (host for host in source.owner.field if source in host.blessings),
        None,
    )


def _host_is_attacking(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return (
        source.area is AreaType.BLESSING
        and _boost_host(source) is ctx.source
    )


def _destroy_weak_opponent(source: CardInstance, state: Any, _ctx: Context) -> None:
    engine = state.engine
    targets = engine.select_target(
        source.owner,
        "enemy_minion",
        1,
        1,
        filter_fn=lambda target: engine.effective_bp(target) <= 400,
        source=source,
    )
    for target in targets:
        engine.destroy_target(target, source=source)


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    if Keyword.KAGO not in card.keywords:
        card.keywords.append(Keyword.KAGO)
    card.bless_condition = _sword_cost_four_or_more
    card.effects = list(card.effects) + [
        EffectSpec(
            timing=EffectTiming.ON_ATTACK,
            fn=_destroy_weak_opponent,
            condition=_host_is_attacking,
            target_kind="enemy_minion",
            min_targets=1,
            max_targets=1,
            params={"max_bp": 400},
            active_areas=(AreaType.BLESSING,),
            official_effect="相手のBP400以下のミニオン1体を破壊する",
            official_timing="アタック時",
            official_condition="ソード族・コスト4以上への付与能力",
        )
    ]
    return card
