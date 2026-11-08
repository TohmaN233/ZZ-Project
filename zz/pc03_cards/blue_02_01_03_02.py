from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming
from zz.enums import AreaType, Keyword
from zz.pc01 import _card_from_row


CARD_ID = "blue_02_01_03_02"
EVOLUTION_PAIRS = (('blue_00_00_03_01', 'blue_00_00_03_02'), ('blue_02_01_03_02', 'blue_02_01_03_03'))


def _apply_evolution(source: Any, state: Any, ctx: Any) -> None:
    engine = state.engine
    if engine is None:
        raise RuntimeError("PC03 evolution requires an Engine")
    engine.apply_pc03_evolution(source=source, context=ctx, upgrades=EVOLUTION_PAIRS, family_id="seadra")

def _apply_seawyrm_unblockable_aura(source: Any, state: Any, _ctx: Any) -> None:
    engine = state.engine
    if engine is None:
        raise RuntimeError("Seadra unblockable aura requires an Engine")
    engine.apply_conditioned_keyword_aura(
        source=source,
        keyword=Keyword.UNBLOCKABLE,
        target_race="シーワーム",
        controller_turn_only=True,
        source_must_remain_active=True,
    )


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.effects.extend(
        [
            EffectSpec(
                EffectTiming.CONTINUOUS,
                _apply_seawyrm_unblockable_aura,
                active_areas=(AreaType.FIELD,),
                params={"conditional_keyword_aura": {"keyword": "unblockable", "race": "シーワーム", "controller_turn_only": True}},
                official_effect="自分の種族「シーワーム」を持つミニオン全てはブロックされない",
                official_timing="自分のターン",
            ),

            EffectSpec(
                EffectTiming.ON_SUMMON,
                _apply_evolution,
                active_areas=(AreaType.FIELD,),
                params={"pc03_evolution_pairs": EVOLUTION_PAIRS, "pc03_evolution_family": "seadra", "pc03_evolution_race": "シーワーム", "pc03_evolution_source_area": "HAND"},
                official_effect="手札から「シーワーム」が召喚されたとき「「海竜の召喚士」アクア」と「「アクアの召喚獣」シードラ」をLv3にする。",
                official_timing="進化",
            ),
        ]
    )
    return card
