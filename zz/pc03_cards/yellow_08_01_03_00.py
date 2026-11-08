from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming
from zz.enums import AreaType, CardType, Color
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "yellow_08_01_03_00"
CHIMERA_RACE = "キマイラ"


def _other_own_chimera_entered(source: CardInstance, _state: Any, ctx: Context) -> bool:
    entered = ctx.source
    return (
        source.area is AreaType.FIELD
        and isinstance(entered, CardInstance)
        and entered is not source
        and entered.owner is source.owner
        and entered.area is AreaType.FIELD
        and entered.card.type in (CardType.F_MINION, CardType.B_MINION)
        and CHIMERA_RACE in entered.card.race_jp.split("|")
    )


def _apply_chimera_entry_penalty(source: CardInstance, state: Any, _ctx: Context) -> None:
    engine = state.engine
    if engine is None:
        raise RuntimeError(f"{CARD_ID} entry effect requires an Engine")
    for target in engine.select_target(source.owner, "enemy_minion", 1, 1, source=source):
        engine.modify_stat(target, bp_delta=-300, duration="permanent")


def _own_turn_end(source: CardInstance, state: Any, ctx: Context) -> bool:
    return source.area is AreaType.FIELD and ctx.controller is source.owner and state.active is source.owner


def _reactivate_yellow_mana_and_draw(source: CardInstance, state: Any, _ctx: Context) -> None:
    engine = state.engine
    if engine is None:
        raise RuntimeError(f"{CARD_ID} turn-end effect requires an Engine")
    for mana in source.owner.base:
        if engine._mana_color_of(mana) is Color.YELLOW:
            engine.refresh_target(mana)
    engine.draw(source.owner, 1)


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.effects.extend(
        [
            EffectSpec(
                EffectTiming.ON_ENTER_FIELD,
                _apply_chimera_entry_penalty,
                condition=_other_own_chimera_entered,
                target_kind="enemy_minion",
                min_targets=1,
                max_targets=1,
                official_effect=(
                    "他の自分の種族「キマイラ」を持つミニオンがフィールドに出るたび、"
                    "相手のミニオン1体にBP-300を付与する。"
                ),
                official_timing="常時",
                active_areas=(AreaType.FIELD,),
            ),
            EffectSpec(
                EffectTiming.TURN_END,
                _reactivate_yellow_mana_and_draw,
                condition=_own_turn_end,
                official_effect="自分の黄マナ全てをアクティブにする。自分はカードを1枚引く。",
                official_timing="自分のターン終了時",
                active_areas=(AreaType.FIELD,),
            ),
        ]
    )
    return card
