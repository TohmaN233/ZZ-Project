from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "purple_01_02_03_00"


def _discard_selected_player_deck(source: CardInstance, state: Any, _ctx: Context) -> None:
    engine = state.engine
    if engine is None:
        raise RuntimeError(f"{CARD_ID} requires an Engine")
    selected = engine.select_target(source.owner, "any_player", 1, 1, source=source)
    if len(selected) != 1:
        raise RuntimeError(f"{CARD_ID} expected one selected Player, got {len(selected)}")
    player = selected[0]
    if player not in state.players:
        raise RuntimeError(f"{CARD_ID} selected a target outside the game: {player!r}")
    engine.mill_deck(player, 2, source=source)


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.effects.append(
        EffectSpec(
            EffectTiming.ON_CAST_MAGIC,
            _discard_selected_player_deck,
            target_kind="any_player",
            min_targets=1,
            max_targets=1,
            official_effect="プレイヤー1人を選択する。そのプレイヤーのデッキを上から2枚破棄する。",
            official_timing="メイン",
        )
    )
    return card
