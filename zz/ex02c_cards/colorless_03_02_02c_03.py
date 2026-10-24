from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming
from zz.enums import AreaType, CardType
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "colorless_03_02_02c_03"


def _self_source(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source


def _draw_one(source: CardInstance, state: Any, _ctx: Context) -> None:
    state.engine.draw(source.owner, 1)


def _return_selected_hand_card_to_bottom(
    source: CardInstance,
    state: Any,
    _ctx: Context,
) -> None:
    selected = state.engine.select_target(
        source.owner,
        "hand_card",
        1,
        1,
        source=source,
    )
    if not selected:
        return
    state.engine.return_hand_card_to_deck_bottom(source.owner, selected[0], source=source)


def _has_black_swordsman_on_owner_field(source: CardInstance, _state: Any, _ctx: Context) -> bool:
    return any(
        target.card.type is CardType.F_MINION
        and "黒の剣士" in target.card.race_jp.split("|")
        for target in source.owner.field
    )


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    effect = EffectSpec(
        timing=EffectTiming.ON_SUMMON,
        fn=_return_selected_hand_card_to_bottom,
        condition=_self_source,
        target_kind="hand_card",
        min_targets=1,
        max_targets=1,
        pre_target_fn=_draw_one,
        params={"ex02c_switch_races": ["黒の剣士"]},
        official_effect="自分はカードを1枚引く。その後、自分の手札1枚をデッキの下に戻す。",
        official_timing="召喚時＆スイッチ",
        active_areas=(AreaType.FIELD,),
    )
    card.effects.append(effect)
    card.effects.append(
        EffectSpec(
            timing=EffectTiming.CONTINUOUS,
            fn=lambda _source, _state, _ctx: None,
            condition=_self_source,
            params={"requires_owner_field_race_to_attack": "黒の剣士"},
            official_effect=(
                "自分の種族「黒の剣士」を持つミニオンがいない場合、"
                "このミニオンはアタックできない。"
            ),
            official_timing="自分のターン",
            active_areas=(AreaType.FIELD,),
        )
    )
    return card
