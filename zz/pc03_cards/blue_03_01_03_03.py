from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming
from zz.enums import AreaType
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "blue_03_01_03_03"


def _self_destroyed(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return (
        source.area is AreaType.TRASH
        and ctx.target is source
        and ctx.effect_carrier is source
    )


def _move_minion_mana_to_field(source: CardInstance, state: Any, _ctx: Context) -> None:
    engine = state.engine
    if engine is None:
        raise RuntimeError(f"{CARD_ID} destruction effect requires an Engine")
    targets = engine.select_target(
        source.owner,
        "ally_minion_base",
        0,
        1,
        source=source,
    )
    if targets:
        engine.move_base_minion_to_field(source.owner, targets[0], rested=False)


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.effects.append(
        EffectSpec(
            EffectTiming.ON_DESTROY,
            _move_minion_mana_to_field,
            condition=_self_destroyed,
            target_kind="ally_minion_base",
            min_targets=0,
            max_targets=1,
            optional=True,
            params={"rested": False},
            official_effect="自分のミニオンカードであるマナ1つを、フィールドにアクティブ状態で移動させることができる。",
            official_timing="破壊時",
            active_areas=(AreaType.FIELD,),
        )
    )
    return card
