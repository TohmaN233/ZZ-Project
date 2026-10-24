from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming, build_effect
from zz.enums import AreaType, CardType
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row
from zz.card_identity import explicitly_equivalent_card_ids


CARD_ID = "yellow_03_03_02c_00"
_RETURN_SPEEDAHOLIC = "turn:ex02c_speedaholic_recovery"


def _self_source(source: CardInstance, state: Any, ctx: Context) -> bool:
    return ctx.source is source


def _activate_minion(source: CardInstance, state: Any, ctx: Context) -> None:
    targets = state.engine.select_target(
        source.owner,
        "ally_minion",
        1,
        1,
        source=source,
    )
    if not targets:
        return
    target = targets[0]
    target.rested = False
    if "ソード" in target.card.race_jp.split("|"):
        source.flags.add(_RETURN_SPEEDAHOLIC)


def _speedaholic_available_at_turn_end(source: CardInstance, state: Any, ctx: Context) -> bool:
    return (
        ctx.controller is source.owner
        and _RETURN_SPEEDAHOLIC in source.flags
        and source.area is AreaType.TRASH
        and any(explicitly_equivalent_card_ids(card.card.id, CARD_ID) for card in source.owner.trash)
    )


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.effects.extend([
        EffectSpec(
            timing=EffectTiming.ON_CAST_MAGIC,
            fn=_activate_minion,
            condition=_self_source,
            target_kind="ally_minion",
            min_targets=1,
            max_targets=1,
            official_effect=(
                "自分のミニオン1体をアクティブにする。"
                "そのミニオンが種族「ソード」を持つ場合、このターン終了時、"
                "自分のトラッシュにある「スピードホリック」1枚を手札に戻す。"
            ),
            official_timing="メイン",
            active_areas=(AreaType.TRASH,),
        ),
        build_effect(
            "return_from_trash_to_hand",
            EffectTiming.TURN_END,
            condition=_speedaholic_available_at_turn_end,
            target_kind="trash_magic_cost_at_most_4",
            min_targets=1,
            max_targets=1,
            active_areas=(AreaType.TRASH,),
            explicitly_equivalent_to=CARD_ID,
            card_type=CardType.MAGIC,
            official_effect="自分のトラッシュにある「スピードホリック」1枚を手札に戻す。",
            official_timing="自分のターン終了時",
        ),
    ])
    return card
