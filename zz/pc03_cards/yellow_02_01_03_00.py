from __future__ import annotations
from typing import Any
from zz.effects import EffectSpec, EffectTiming
from zz.enums import AreaType, CardType
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row

CARD_ID = "yellow_02_01_03_00"
_RACES = ("アヴィアン", "アルカナ")
_TYPES = (CardType.B_MINION, CardType.F_MINION)

def _eligible(source: CardInstance, target: CardInstance) -> bool:
    return target is not source and target.owner is source.owner and target.area is AreaType.FIELD and target.card.type in _TYPES and any(r in target.card.race_jp.split("|") for r in _RACES)

def _has_target(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source and source.area is AreaType.FIELD and any(_eligible(source, c) for c in source.owner.field)

def _buff(source: CardInstance, state: Any, _ctx: Context) -> None:
    engine = state.engine
    if engine is None:
        raise RuntimeError(f"{CARD_ID} summon effect requires an Engine")
    targets = engine.select_target(source.owner, "ally_minion", 1, 1, source=source)
    if len(targets) != 1 or not _eligible(source, targets[0]):
        raise RuntimeError(f"{CARD_ID} selected a target outside its Avian/Arcana filter")
    engine.modify_stat(targets[0], bp_delta=200, duration="permanent")

def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.effects.append(EffectSpec(EffectTiming.ON_SUMMON, _buff, condition=_has_target,
        target_kind="ally_minion", min_targets=1, max_targets=1,
        params={"races_any": _RACES, "exclude_source": True, "card_types": _TYPES},
        official_effect="他の自分の種族「アヴィアン」または「アルカナ」を持つミニオン1体にBP+200を付与する。",
        official_timing="召喚時", active_areas=(AreaType.FIELD,)))
    return card
