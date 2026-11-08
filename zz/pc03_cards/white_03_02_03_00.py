from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming
from zz.enums import AreaType
from zz.model import CardInstance, Context, ForceInstance
from zz.pc01 import _card_from_row

CARD_ID = "white_03_02_03_00"


def _self_cast(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source


def _restore_one_force_and_draw(source: CardInstance, state: Any, _ctx: Context) -> None:
    engine = state.engine
    if engine is None:
        raise RuntimeError(f"{CARD_ID} cast effect requires an Engine")
    selected = engine.select_target(
        source.owner,
        "ally_force",
        1,
        1,
        filter_fn=lambda force: isinstance(force, ForceInstance) and not force.destroyed,
        source=source,
    )
    if len(selected) != 1 or not isinstance(selected[0], ForceInstance):
        raise RuntimeError(f"{CARD_ID} expected exactly one live owned Force")
    engine.heal_target(selected[0], 2)
    engine.draw(source.owner, 1)


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.ability_jp = "【メイン】\n【フラッシュ】自分のフォース1つを2回復する。自分はカードを1枚引く。"
    card.ability_en = "[Main]/[Flash] Restore 2 points to one of your Forces. Draw one card."
    card.main_timing_ok = True
    card.flash_timing_ok = True
    card.effects.append(
        EffectSpec(
            EffectTiming.ON_CAST_MAGIC,
            _restore_one_force_and_draw,
            condition=_self_cast,
            target_kind="ally_force",
            min_targets=1,
            max_targets=1,
            params={"heal": 2, "draw": 1, "controller_only": True},
            official_effect="自分のフォース1つを2回復する。自分はカードを1枚引く。",
            official_timing="メイン/フラッシュ",
            active_areas=(AreaType.RESOLVING,),
        )
    )
    return card
