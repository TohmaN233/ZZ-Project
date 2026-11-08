from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming
from zz.enums import AreaType, CardType
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "yellow_03_01_03_05"
FAMILY_ID = "tsarukoa"
EVOLUTION_RACE = "キマイラ"
EVOLUTION_PAIRS = (
    ("yellow_00_00_03_01", "yellow_00_00_03_02"),
    ("yellow_03_01_03_05", "yellow_03_01_03_00"),
)


def _self_turn_end(source: CardInstance, state: Any, ctx: Context) -> bool:
    return (
        ctx.controller is source.owner
        and state.active is source.owner
        and source.area is AreaType.FIELD
    )


def _inspect_top_chimera(source: CardInstance, state: Any, _ctx: Context) -> None:
    engine = state.engine
    if engine is None:
        raise RuntimeError(f"{CARD_ID} top-deck effect requires an Engine")
    owner = source.owner
    if not owner.deck:
        return
    selected = engine.select_target(owner, "top1_card", 1, 1, source=source)
    if len(selected) != 1:
        raise RuntimeError(f"{CARD_ID} expected one inspected top card, got {len(selected)}")
    candidate = selected[0]
    if candidate not in owner.deck or owner.deck[0] is not candidate:
        raise RuntimeError(f"{CARD_ID} inspected card {candidate.iid} is no longer on top of its owner's Deck")
    if candidate.card.type is CardType.F_MINION and EVOLUTION_RACE in candidate.card.race_jp.split("|"):
        owner.deck.remove(candidate)
        engine.reveal_card(owner, candidate, "deck_search")
        engine.add_to_hand(owner, candidate, from_area=AreaType.DECK)
    else:
        owner.deck.remove(candidate)
        owner.deck.append(candidate)


def _apply_evolution(source: CardInstance, state: Any, ctx: Context) -> None:
    engine = state.engine
    if engine is None:
        raise RuntimeError(f"{CARD_ID} evolution requires an Engine")
    engine.apply_pc03_evolution(
        source=source,
        context=ctx,
        upgrades=EVOLUTION_PAIRS,
        family_id=FAMILY_ID,
    )


def _own_hand_chimera_summoned(source: CardInstance, state: Any, ctx: Context) -> bool:
    summoned = ctx.source
    engine = state.engine
    if engine is None:
        raise RuntimeError(f"{CARD_ID} evolution condition requires an Engine")
    if (
        source.area is not AreaType.FIELD
        or source.owner is not ctx.controller
        or state.active is not source.owner
        or not isinstance(summoned, CardInstance)
        or summoned.owner is not source.owner
        or summoned.area is not AreaType.FIELD
        or summoned.card.type is not CardType.F_MINION
        or EVOLUTION_RACE not in summoned.card.race_jp.split("|")
    ):
        return False
    movement = next(
        (event for event in reversed(engine.zone_move_events) if event.get("card") is summoned),
        None,
    )
    return bool(
        movement
        and movement.get("from") is AreaType.HAND
        and movement.get("to") is AreaType.FIELD
        and engine.can_pc03_evolve(player=source.owner, family_id=FAMILY_ID)
    )


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.ability_jp = (
        "【自分のターン終了時】自分のデッキを上から1枚見て、種族「キマイラ」を持つ"
        "フィールド・ミニオンカードの場合、公開して手札に加える。それ以外の場合、デッキの下に戻す。\n"
        "【進化】手札から「キマイラ」が召喚されたとき、「羽蛇の召喚士」キラリと"
        "「キラリの召喚獣」ツァルコアをLv3にする。"
    )
    card.ability_en = (
        "[At the end of your turn] Look at the top card of your deck. If it is a Field Minion "
        "with the Chimera race, reveal it and add it to your hand. Otherwise, put it on the bottom "
        "of your deck.\n[Evolve] When you summon a Chimera from your hand, evolve Kirari and "
        "Tsarukoa to Lv.3."
    )
    card.effects.extend(
        [
            EffectSpec(
                EffectTiming.TURN_END,
                _inspect_top_chimera,
                condition=_self_turn_end,
                target_kind="top1_card",
                min_targets=1,
                max_targets=1,
                official_effect=(
                    "自分のデッキを上から1枚見て、種族「キマイラ」を持つフィールド・ミニオンカードの場合、"
                    "公開して手札に加える。それ以外の場合、デッキの下に戻す。"
                ),
                official_timing="自分のターン終了時",
                active_areas=(AreaType.FIELD,),
            ),
            EffectSpec(
                EffectTiming.ON_SUMMON,
                _apply_evolution,
                condition=_own_hand_chimera_summoned,
                params={
                    "pc03_evolution_pairs": EVOLUTION_PAIRS,
                    "pc03_evolution_family": FAMILY_ID,
                    "pc03_evolution_race": EVOLUTION_RACE,
                    "pc03_evolution_source_area": AreaType.HAND.name,
                },
                official_effect=(
                    "手札から「キマイラ」が召喚されたとき「「羽蛇の召喚士」キラリ」と"
                    "「「キラリの召喚獣」ツァルコア」をLv3にする。"
                ),
                official_timing="進化",
                active_areas=(AreaType.FIELD,),
            ),
        ]
    )
    return card
