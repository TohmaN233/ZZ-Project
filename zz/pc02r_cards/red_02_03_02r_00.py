from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming
from zz.enums import CardType, Color
from zz.model import Card, CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "red_02_03_02r_00"

_S_GOLEM_TOKEN = Card(
    id="s_golem_token",
    name_jp="S・ゴレイム・トークン",
    name_en="Token Golem S",
    type=CardType.F_MINION,
    is_token=True,
    cost={Color.RED: 1},
    bp=100,
    dp=1,
    race_jp="ゴレイム",
)


def _this_magic_was_cast(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source


def _buff_one_friendly_minion_and_call_a_golem(
    source: CardInstance,
    state: Any,
    _ctx: Context,
) -> None:
    engine = state.engine
    targets = engine.select_target(source.owner, "ally_minion", 1, 1, source=source)
    if not targets:
        return
    target = targets[0]
    engine.modify_stat(target, bp_delta=300, duration="turn")
    if "ゴレイム" in target.card.race_jp:
        engine.create_tokens(source.owner, [_S_GOLEM_TOKEN], source=source)


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.main_timing_ok = False
    card.flash_timing_ok = True
    card.effects = list(card.effects) + [
        EffectSpec(
            timing=EffectTiming.ON_CAST_MAGIC,
            fn=_buff_one_friendly_minion_and_call_a_golem,
            condition=_this_magic_was_cast,
            target_kind="ally_minion",
            min_targets=1,
            max_targets=1,
            official_effect="自分のミニオン1体にこのターンBP+300。対象がゴレイムならS・ゴレイム・トークン1体を出す",
            official_timing="フラッシュ",
        )
    ]
    return card
