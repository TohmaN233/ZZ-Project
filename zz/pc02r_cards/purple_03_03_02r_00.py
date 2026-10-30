from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming
from zz.model import Context
from zz.pc01 import _card_from_row


CARD_ID = "purple_03_03_02r_00"


def _drain_ritual(source, state, ctx: Context) -> None:
    engine = state.engine
    targets = engine.select_target(source.owner, "enemy_force", 1, 1, source=source)
    if not targets and engine._eligible_targets(source.owner, "enemy_force", source=source):
        raise RuntimeError("Ritual of Draining requires one opposing Force target")
    if len(targets) > 1:
        raise RuntimeError("Ritual of Draining received multiple Force targets")
    if targets:
        engine._damage_force(targets[0], 1, source=source)
    engine.heal(source.owner, 1)


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.effects.append(
        EffectSpec(
            timing=EffectTiming.ON_CAST_MAGIC,
            fn=_drain_ritual,
            target_kind="enemy_force",
            min_targets=1,
            max_targets=1,
            official_effect="相手のフォース1つに1ダメージを与え、自分のプレイヤーを1回復する",
            official_timing="メイン",
        )
    )
    return card
