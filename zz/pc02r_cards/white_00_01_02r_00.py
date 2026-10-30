from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming
from zz.enums import AreaType
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "white_00_01_02r_00"


def _this_boosted_minion_damaged_on_own_turn(source: CardInstance, state: Any, ctx: Context) -> bool:
    if state.active is not source.owner or not isinstance(ctx.source, CardInstance):
        return False
    if getattr(ctx, "damage_amount", 0) <= 0:
        return False
    return any(
        host is ctx.source and source in host.blessings
        for host in source.owner.field
    )


def _heal_one_force(source: CardInstance, state: Any, _ctx: Context) -> None:
    engine = state.engine
    targets = engine.select_target(source.owner, "ally_force", 1, 1, source=source)
    if targets:
        engine.heal_target(targets[0], 1)


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.effects = list(card.effects) + [
        EffectSpec(
            timing=timing,
            fn=_heal_one_force,
            condition=_this_boosted_minion_damaged_on_own_turn,
            active_areas=(AreaType.BLESSING,),
            params={"granted_by_blessing": True},
            target_kind="ally_force",
            official_effect="自分のターン中、付与先のミニオンがダメージを与えるたび、自分のフォース1つを1回復する",
            official_timing="自分のターン中のダメージ時",
        )
        for timing in (EffectTiming.ON_DAMAGE_PLAYER, EffectTiming.ON_DAMAGE_FORCE)
    ]
    return card
