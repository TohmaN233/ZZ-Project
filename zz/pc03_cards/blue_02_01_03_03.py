from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming
from zz.enums import AreaType, CardType, Keyword
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "blue_02_01_03_03"


def _seawyrm_unblockable_aura(source: CardInstance, target: CardInstance, state: Any) -> list[Keyword]:
    races = {race for race in target.card.race_jp.split("|") if race}
    if (
        source.area is AreaType.FIELD
        and target.area is AreaType.FIELD
        and source.owner is target.owner
        and state.active is source.owner
        and "シーワーム" in races
    ):
        return [Keyword.UNBLOCKABLE]
    return []


def _is_own_minion_damage(source: CardInstance, state: Any, ctx: Context) -> bool:
    damaged_source = ctx.source
    return (
        source.area is AreaType.FIELD
        and state.active is source.owner
        and isinstance(damaged_source, CardInstance)
        and damaged_source.owner is source.owner
        and damaged_source.area is AreaType.FIELD
        and damaged_source.card.type in (CardType.F_MINION, CardType.B_MINION)
    )


def _draw_for_unique_seadra(source: CardInstance, state: Any, _ctx: Context) -> None:
    engine = state.engine
    if engine is None:
        raise RuntimeError(f"{CARD_ID} damage trigger requires an Engine")
    active_seadras = [
        minion
        for minion in source.owner.field
        if minion.area is AreaType.FIELD and minion.card.id == CARD_ID
    ]
    if not active_seadras:
        raise RuntimeError(f"{CARD_ID} damage trigger resolved without a field copy")
    if source.iid != min(item.iid for item in active_seadras):
        return
    engine.draw(source.owner, 1)


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.keyword_aura = _seawyrm_unblockable_aura
    card.effects.extend(
        EffectSpec(
            timing=timing,
            fn=_draw_for_unique_seadra,
            condition=_is_own_minion_damage,
            official_effect="自分のミニオンがダメージを与えるたび、自分はカードを1枚引く。この効果は重複しない。",
            official_timing="自分のターン",
            active_areas=(AreaType.FIELD,),
        )
        for timing in (EffectTiming.ON_DAMAGE_PLAYER, EffectTiming.ON_DAMAGE_FORCE)
    )
    return card
