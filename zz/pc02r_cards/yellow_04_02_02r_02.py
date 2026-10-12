from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming
from zz.enums import AreaType, CardType, Color
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "yellow_04_02_02r_02"


def _self_summoned(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source


def _return_yellow_dragon_and_gain_original_stats(
    source: CardInstance,
    state: Any,
    _ctx: Context,
) -> None:
    engine = state.engine
    selected = engine.select_target(
        source.owner,
        "ally_minion",
        1,
        1,
        filter_fn=lambda target: (
            target.card.type is CardType.F_MINION
            and target.card.printed_color is Color.YELLOW
            and "ドラゴン" in target.card.race_jp
        ),
        source=source,
    )
    if not selected:
        return
    if len(selected) != 1:
        raise RuntimeError(f"{CARD_ID} expected one Yellow Dragon, received {len(selected)}")
    returned = selected[0]
    original_bp = returned.card.bp
    original_dp = returned.card.dp
    engine.return_to_hand(returned, source=source)
    engine.modify_stat(source, bp_delta=original_bp, dp_delta=original_dp, duration="permanent")


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.effects = list(card.effects) + [
        EffectSpec(
            timing=EffectTiming.ON_SUMMON,
            fn=_return_yellow_dragon_and_gain_original_stats,
            condition=_self_summoned,
            target_kind="ally_minion",
            min_targets=1,
            max_targets=1,
            params={"color": Color.YELLOW, "card_type": CardType.F_MINION, "race": "ドラゴン"},
            active_areas=(AreaType.FIELD,),
            official_effect="自分の黄のドラゴン族ミニオン1体を手札に戻し、そうした場合その本来のBPとDPをこのミニオンに付与する",
            official_timing="召喚時",
        )
    ]
    return card
