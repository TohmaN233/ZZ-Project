from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming, _target_filter
from zz.enums import AreaType, CardType, Keyword
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "purple_00_01_02r_01"
_TARGET_FILTER_PARAMS = {"min_cost": 7, "max_cost": 7, "card_type": CardType.F_MINION}


def _self_placed(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source


def _return_cost_seven_minion(source: CardInstance, state: Any, _ctx: Context) -> None:
    engine = state.engine
    matcher = _target_filter(engine, **_TARGET_FILTER_PARAMS)
    eligible = [card for card in source.owner.trash if matcher(card)]
    if not eligible:
        return
    targets = engine.select_target(
        source.owner,
        "trash_field_minion",
        1,
        1,
        filter_fn=matcher,
        source=source,
    )
    if len(targets) != 1:
        raise RuntimeError(f"{CARD_ID} expected one cost-7 Field Minion, got {len(targets)}")
    engine.add_to_hand(source.owner, targets[0], from_area=AreaType.TRASH)


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    if Keyword.KAGO not in card.keywords:
        card.keywords = list(card.keywords) + [Keyword.KAGO]
    card.effects = list(card.effects) + [
        EffectSpec(
            timing=EffectTiming.ON_PLACE_BASE,
            fn=_return_cost_seven_minion,
            condition=_self_placed,
            target_kind="trash_field_minion",
            min_targets=1,
            max_targets=1,
            params=dict(_TARGET_FILTER_PARAMS),
            active_areas=(AreaType.BASE,),
            official_effect="自分のトラッシュにあるコスト7のフィールド・ミニオン1枚を手札に戻す",
            official_timing="配置時",
        )
    ]
    return card
