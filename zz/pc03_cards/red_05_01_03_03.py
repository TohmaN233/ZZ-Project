from __future__ import annotations

from typing import Any

from zz.effects import build_effect, EffectTiming
from zz.enums import AreaType, CardType, Color, Keyword
from zz.model import CardInstance
from zz.pc01 import _card_from_row


CARD_ID = "red_05_01_03_03"
DWARF_RACE = "ドワーフ"


def _dwarf_charge_aura(source: CardInstance, target: CardInstance, state: Any) -> list[Keyword]:
    if (
        source.area is AreaType.FIELD
        and target.area is AreaType.FIELD
        and source.owner is target.owner
        and state.active is source.owner
        and target.card.type is CardType.F_MINION
        and DWARF_RACE in target.card.race_jp.split("|")
    ):
        return [Keyword.RUSH]
    return []


def _self_attacked(source: CardInstance, state: Any, ctx: Any) -> bool:
    return ctx.source is source and source.area is AreaType.FIELD and state.active is source.owner


def _cannot_block_red_minion_with_weaker_bp(attacker: CardInstance, blocker: CardInstance, state: Any) -> bool:
    if (
        state.active is not attacker.owner
        or attacker.card.type not in (CardType.F_MINION, CardType.B_MINION)
        or blocker.card.type not in (CardType.F_MINION, CardType.B_MINION)
    ):
        return False
    source_active = any(
        source.area is AreaType.FIELD
        and source.owner is attacker.owner
        and source.card.id == CARD_ID
        for source in attacker.owner.field
    )
    if not source_active:
        return False
    engine = state.engine
    if engine is None:
        raise RuntimeError(f"{CARD_ID} blocker restriction requires an Engine")
    return engine._card_color(attacker.card) is Color.RED and engine.effective_bp(blocker) < blocker.card.bp


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.keyword_aura = _dwarf_charge_aura
    card.blocker_aura = _cannot_block_red_minion_with_weaker_bp
    card.effects.append(
        build_effect(
            "stat_modifier",
            EffectTiming.ON_ATTACK,
            condition=_self_attacked,
            target_kind="enemy_minion",
            min_targets=2,
            max_targets=2,
            bp_delta=-200,
            duration="permanent",
            official_effect="相手のミニオン2体にBP-200を付与する。",
            official_timing="アタック時",
        )
    )
    return card
