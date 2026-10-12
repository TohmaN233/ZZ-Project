from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming
from zz.enums import AreaType
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "green_06_02_02r_01"


def _self_summoned(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source


def _prevent_selected_minion_from_attacking_life(
    source: CardInstance,
    state: Any,
    _ctx: Context,
) -> None:
    targets = state.engine.select_target(source.owner, "enemy_minion", 1, 1, source=source)
    if len(targets) != 1:
        raise RuntimeError(f"{CARD_ID} expected one opposing Minion, received {len(targets)}")
    targets[0].flags.add("pc02r:cannot_attack_life:granted")


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.effects = list(card.effects) + [
        EffectSpec(
            timing=EffectTiming.ON_SUMMON,
            fn=_prevent_selected_minion_from_attacking_life,
            condition=_self_summoned,
            active_areas=(AreaType.FIELD,),
            target_kind="enemy_minion",
            min_targets=1,
            max_targets=1,
            official_effect="相手のミニオン1体にプレイヤーへアタックできない効果を付与する",
            official_timing="召喚時",
        )
    ]
    return card
