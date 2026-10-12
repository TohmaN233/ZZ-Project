from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming
from zz.enums import AreaType, CardType
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "white_02_03_02r_00"


def _this_magic_was_cast(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source


def _buff_and_protect_selected_minion(source: CardInstance, state: Any, ctx: Context) -> None:
    engine = state.engine
    targets = engine.select_target(source.owner, "ally_minion", 1, 1, source=source)
    if len(targets) != 1 or not isinstance(targets[0], CardInstance):
        raise RuntimeError("Metal Wall requires one allied Minion target")
    target = targets[0]
    if target.owner is not source.owner or target.area is not AreaType.FIELD:
        raise RuntimeError("Metal Wall target is not an allied Field Minion")
    if target.card.type not in (CardType.F_MINION, CardType.B_MINION):
        raise RuntimeError("Metal Wall target is not a Minion")

    engine.modify_stat(target, bp_delta=300, duration="turn")
    target.flags.add(
        f"opponent_effect_target_protection:{state.turn}:{source.owner.side.name}"
    )


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.effects = list(card.effects) + [
        EffectSpec(
            timing=EffectTiming.ON_CAST_MAGIC,
            fn=_buff_and_protect_selected_minion,
            condition=_this_magic_was_cast,
            target_kind="ally_minion",
            min_targets=1,
            max_targets=1,
            official_effect=(
                "自分のミニオン1体にこのターンBP+300を与え、"
                "相手のミニオンとマジックの効果で選ばれなくする"
            ),
            official_timing="フラッシュ",
        )
    ]
    return card
