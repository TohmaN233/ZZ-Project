from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming
from zz.enums import AreaType, CardType
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "purple_06_01_03_00"


def _self_destroyed(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.target is source and source.area is AreaType.TRASH


def _copy_opponent_trash_minion(source: CardInstance, state: Any, _ctx: Context) -> None:
    engine = state.engine
    if engine is None:
        raise RuntimeError(f"{CARD_ID} destruction effect requires an Engine")
    targets = engine.select_target(
        source.owner,
        "enemy_trash_field_minion",
        1,
        1,
        filter_fn=lambda target: target.card.type is CardType.F_MINION and target.card.id != CARD_ID,
        source=source,
    )
    if targets:
        engine.create_field_minions(source.owner, [targets[0].card], source=source)


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.effects.append(
        EffectSpec(
            EffectTiming.ON_DESTROY,
            _copy_opponent_trash_minion,
            condition=_self_destroyed,
            target_kind="enemy_trash_field_minion",
            min_targets=1,
            max_targets=1,
            params={"card_type": CardType.F_MINION, "exclude_card_id": CARD_ID, "puts_targets_on_field": True},
            official_effect="相手のトラッシュにある、「「タナトスの屍司祭」プリースト」以外のフィールド・ミニオンカード1枚と同じミニオン1体を、自分のフィールドに出す。",
            official_timing="破壊時",
        )
    )
    return card
