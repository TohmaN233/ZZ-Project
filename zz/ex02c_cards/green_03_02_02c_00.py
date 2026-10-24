from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming
from zz.enums import AreaType, CardType
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "green_03_02_02c_00"


def _this_minion_was_summoned(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source or getattr(ctx, "switch_source", None) is source


def _place_item_base_minion(source: CardInstance, state: Any, _ctx: Context) -> None:
    engine = state.engine
    selected = engine.select_target(
        source.owner,
        "hand_base_minion",
        0,
        1,
        filter_fn=lambda card: "アイテム" in card.card.race_jp.split("|"),
        source=source,
    )
    if selected:
        engine.put_base_minion_from_hand(source.owner, selected[0], rested=True)


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.ability_jp = (
        "【召喚時】スイッチ：「黒の剣士」"
        "自分の手札にある種族「アイテム」を持つベース・ミニオンカード1枚を、"
        "ベースに置くことができる。（【配置時】効果は発揮しない。）"
    )
    card.effects.append(
        EffectSpec(
            timing=EffectTiming.ON_SUMMON,
            fn=_place_item_base_minion,
            condition=_this_minion_was_summoned,
            target_kind="hand_base_minion",
            min_targets=0,
            max_targets=1,
            optional=True,
            params={
                "race": "アイテム",
                "card_type": CardType.B_MINION,
                "ex02c_switch_races": ["黒の剣士"],
            },
            official_effect=(
                "自分の手札にある種族「アイテム」を持つベース・ミニオンカード1枚を、"
                "ベースに置くことができる。（【配置時】効果は発揮しない。）"
            ),
            official_timing="召喚時＆スイッチ",
            active_areas=(AreaType.FIELD,),
        )
    )
    return card
