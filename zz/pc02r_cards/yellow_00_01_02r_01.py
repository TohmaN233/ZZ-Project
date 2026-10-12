from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming
from zz.enums import AreaType, Keyword
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "yellow_00_01_02r_01"


def _self_placed(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source


def _grant_permanent_bp(source: CardInstance, state: Any, _ctx: Context) -> None:
    engine = state.engine
    targets = engine.select_target(source.owner, "ally_minion", 1, 1, source=source)
    if not targets:
        return
    if len(targets) != 1:
        raise RuntimeError(f"{CARD_ID} expected one selected Minion, received {len(targets)}")
    engine.modify_stat(targets[0], bp_delta=200, duration="permanent")


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    if Keyword.KAGO not in card.keywords:
        card.keywords = list(card.keywords) + [Keyword.KAGO]
    card.effects = list(card.effects) + [
        EffectSpec(
            timing=EffectTiming.ON_PLACE_BASE,
            fn=_grant_permanent_bp,
            condition=_self_placed,
            target_kind="ally_minion",
            min_targets=1,
            max_targets=1,
            active_areas=(AreaType.BASE,),
            official_effect="自分のミニオン1体にBP+200を付与する",
            official_timing="配置時",
        )
    ]
    return card
