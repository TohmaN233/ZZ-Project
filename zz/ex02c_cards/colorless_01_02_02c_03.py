from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming
from zz.enums import AreaType, CardType
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "colorless_01_02_02c_03"
_LOOKUP_RACES = {"黒の剣士", "閃光"}


def _self_source(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source


def _inspect_top_card(source: CardInstance, state: Any, _ctx: Context) -> None:
    owner = source.owner
    if not owner.deck:
        return
    selected = state.engine.select_target(owner, "top1_card", 1, 1, source=source)
    if len(selected) != 1:
        raise RuntimeError(f"{CARD_ID} expected the inspected top card, got {len(selected)} selections")
    candidate = selected[0]
    if candidate not in owner.deck:
        raise RuntimeError(f"{CARD_ID} inspected card {candidate.iid} left its owner's Deck")
    matches = (
        candidate.card.type is CardType.F_MINION
        and bool(_LOOKUP_RACES.intersection(candidate.card.race_jp.split("|")))
    )
    if matches:
        owner.deck.remove(candidate)
        state.engine.reveal_card(owner, candidate, "deck_search")
        state.engine.add_to_hand(owner, candidate, from_area=AreaType.DECK)
    else:
        owner.deck.remove(candidate)
        owner.deck.append(candidate)


def _rest_after_base_move(source: CardInstance, state: Any, ctx: Context) -> None:
    if ctx.source is source and source.area is AreaType.BASE:
        state.engine.rest_target(source)


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.ability_jp = (
        "【召喚時】\n"
        "自分のデッキを上から1枚見て、種族「黒の剣士」または「閃光」を持つ"
        "フィールド・ミニオンカードの場合、公開して手札に加える。"
        "それ以外の場合、デッキの下に戻す。\n"
        "【常時】\n"
        "このミニオンはベースに移動するとき、レスト状態で移動する。"
    )
    card.effects.extend(
        [
            EffectSpec(
                timing=EffectTiming.ON_SUMMON,
                fn=_inspect_top_card,
                condition=_self_source,
                target_kind="top1_card",
                min_targets=1,
                max_targets=1,
                official_effect=(
                    "自分のデッキを上から1枚見て、種族「黒の剣士」または「閃光」を持つ"
                    "フィールド・ミニオンカードの場合、公開して手札に加える。"
                    "それ以外の場合、デッキの下に戻す。"
                ),
                official_timing="召喚時",
                active_areas=(AreaType.FIELD,),
            ),
            EffectSpec(
                timing=EffectTiming.MOVE_TO_BASE,
                fn=_rest_after_base_move,
                condition=_self_source,
                official_effect="このミニオンはベースに移動するとき、レスト状態で移動する。",
                official_timing="常時",
                active_areas=(AreaType.BASE,),
            ),
        ]
    )
    return card
