from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming
from zz.enums import AreaType
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "white_03_02_02r_00"
_ELIGIBLE_RACES = ("アンドロイド", "ウイング")


def _this_minion_was_summoned(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source


def _boost_one_android_or_winged_minion(
    source: CardInstance,
    state: Any,
    _ctx: Context,
) -> None:
    engine = state.engine
    targets = engine.select_target(
        source.owner,
        "ally_minion",
        1,
        1,
        filter_fn=lambda target: any(race in target.card.race_jp for race in _ELIGIBLE_RACES),
        source=source,
    )
    if len(targets) != 1:
        raise RuntimeError(f"{CARD_ID} requires exactly one Android or Winged Minion target")
    engine.modify_stat(targets[0], bp_delta=200, duration="permanent")


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.effects = list(card.effects) + [
        EffectSpec(
            timing=EffectTiming.ON_SUMMON,
            fn=_boost_one_android_or_winged_minion,
            condition=_this_minion_was_summoned,
            active_areas=(AreaType.FIELD,),
            target_kind="ally_minion",
            min_targets=1,
            max_targets=1,
            params={"races_any": list(_ELIGIBLE_RACES)},
            official_effect="召喚時、自分のAndroidまたはWinged Minion1体にBP+200する",
            official_timing="召喚時",
        )
    ]
    return card
