from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming
from zz.enums import AreaType, CardType, Color
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "purple_04_01_03_03"
EVOLUTION_FAMILY = "vill"
EVOLUTION_RACE = "デーモン"
EVOLUTION_PAIRS = (
    ("purple_00_00_03_01", "purple_00_00_03_02"),
    ("purple_04_01_03_03", "purple_04_01_03_04"),
)


def _own_hand_demon_summoned(source: CardInstance, state: Any, ctx: Context) -> bool:
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
    if not (movement and movement.get("from") is AreaType.HAND and movement.get("to") is AreaType.FIELD):
        return False
    return engine.can_pc03_evolve(player=source.owner, family_id=EVOLUTION_FAMILY)


def _apply_evolution(source: CardInstance, state: Any, ctx: Context) -> None:
    engine = state.engine
    if engine is None:
        raise RuntimeError(f"{CARD_ID} evolution requires an Engine")
    engine.apply_pc03_evolution(
        source=source,
        context=ctx,
        upgrades=EVOLUTION_PAIRS,
        family_id=EVOLUTION_FAMILY,
    )


def _own_turn_end(source: CardInstance, state: Any, ctx: Context) -> bool:
    return source.area is AreaType.FIELD and source.owner is ctx.controller and state.active is source.owner


def _mill_top_and_gain_bp(source: CardInstance, state: Any, _ctx: Context) -> None:
    engine = state.engine
    if engine is None:
        raise RuntimeError(f"{CARD_ID} turn-end effect requires an Engine")
    milled = engine.mill_deck(source.owner, 1, source=source)
    if milled and milled[0].card.printed_color is Color.PURPLE:
        engine.modify_stat(source, bp_delta=100, duration="permanent")


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.effects.extend(
        [
            EffectSpec(
                EffectTiming.TURN_END,
                _mill_top_and_gain_bp,
                condition=_own_turn_end,
                official_effect="自分のデッキを上から1枚破棄する。そのカードが紫のカードである場合、このミニオンにBP+100を付与する。",
                official_timing="自分のターン終了時",
                active_areas=(AreaType.FIELD,),
            ),
            EffectSpec(
                EffectTiming.ON_SUMMON,
                _apply_evolution,
                condition=_own_hand_demon_summoned,
                params={
                    "pc03_evolution_pairs": EVOLUTION_PAIRS,
                    "pc03_evolution_family": EVOLUTION_FAMILY,
                    "pc03_evolution_race": EVOLUTION_RACE,
                    "pc03_evolution_source_area": AreaType.HAND.name,
                },
                official_effect="手札から「デーモン」が召喚されたとき「「血陣の召喚士」リリアン」と「「リリアンの召喚獣」ヴィル」をLv3にする。",
                official_timing="進化",
                active_areas=(AreaType.FIELD,),
            ),
        ]
    )
    return card
