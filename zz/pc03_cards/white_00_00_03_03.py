from __future__ import annotations
from typing import Any
from zz.effects import EffectSpec, EffectTiming
from zz.enums import AreaType
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row

CARD_ID = "white_00_00_03_03"
SUMMON_BEAST_CARD_ID = "white_07_01_03_00"
ABILITY_JP = '《ベース》\n【配置時】\n「「サラの召喚獣」メタリック・スティード Lv1」1枚を手札に加える。\n《ベース》\nこのマナは移動できない。'
ABILITY_EN = '<Base> [When Placed]\nAdd one Chrome Charger - Of Serah Lv.1 to your hand.\n<Base>\nThis minion cannot move.'

def _self_is_placed(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source and source.area is AreaType.BASE

def _add_summon_beast_from_outside(source: CardInstance, state: Any, _ctx: Context) -> None:
    engine = state.engine
    if engine is None:
        raise RuntimeError(f"{CARD_ID} Base placement requires an Engine")
    if source.area is not AreaType.BASE:
        raise RuntimeError(f"{CARD_ID} placement effect resolved outside Base: {source.area!r}")
    source.flags.add("cannot_move")
    engine.add_card_from_outside_to_hand(source.owner, SUMMON_BEAST_CARD_ID)

def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.ability_jp = ABILITY_JP
    card.ability_en = ABILITY_EN
    card.effects.append(EffectSpec(EffectTiming.ON_PLACE_BASE, _add_summon_beast_from_outside,
        condition=_self_is_placed,
        official_effect='「「サラの召喚獣」メタリック・スティード Lv1」1枚を手札に加える。',
        official_timing="配置時", active_areas=(AreaType.BASE,)))
    return card
