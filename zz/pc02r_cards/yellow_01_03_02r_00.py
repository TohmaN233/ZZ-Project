from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming
from zz.enums import AreaType
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "yellow_01_03_02r_00"
_BATTLE_BOOST_PREFIX = "battle:pc02r_build_up:"


def _self_cast(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source


def _select_and_boost_minion(source: CardInstance, state: Any, _ctx: Context) -> None:
    engine = state.engine
    targets = engine.select_target(source.owner, "ally_minion", 1, 1, source=source)
    if len(targets) != 1:
        raise RuntimeError(f"{CARD_ID} expected one allied Minion, received {len(targets)}")
    target = targets[0]
    battle_flag = f"{_BATTLE_BOOST_PREFIX}{source.iid}"
    if battle_flag in target.flags:
        raise RuntimeError(f"{CARD_ID} already marked Minion iid={target.iid} for this battle")
    target.flags.add(battle_flag)
    engine.modify_stat(target, bp_delta=200, duration="battle")


def _selected_minion_won(source: CardInstance, _state: Any, ctx: Context) -> bool:
    winner = ctx.source
    return (
        isinstance(winner, CardInstance)
        and winner.owner is source.owner
        and f"{_BATTLE_BOOST_PREFIX}{source.iid}" in winner.flags
    )


def _return_after_battle_win(source: CardInstance, state: Any, ctx: Context) -> None:
    winner = ctx.source
    if not isinstance(winner, CardInstance):
        raise RuntimeError(f"{CARD_ID} battle-win trigger has no winning Minion")
    winner.flags.discard(f"{_BATTLE_BOOST_PREFIX}{source.iid}")
    eligible = [
        card
        for card in source.owner.trash
        if card.card.id == CARD_ID and card.area is AreaType.TRASH
    ]
    if not eligible:
        raise RuntimeError(f"{CARD_ID} battle-win trigger has no matching card in its owner's Trash")
    targets = state.engine.select_target(
        source.owner,
        "trash_magic_cost_at_most_4",
        1,
        1,
        filter_fn=lambda card: card.card.id == CARD_ID and card.area is AreaType.TRASH,
        source=source,
    )
    if len(targets) != 1:
        raise RuntimeError(f"{CARD_ID} expected one selected card from Trash, received {len(targets)}")
    state.engine.add_to_hand(source.owner, targets[0], from_area=AreaType.TRASH)


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.main_timing_ok = False
    card.flash_timing_ok = True
    card.effects = list(card.effects) + [
        EffectSpec(
            timing=EffectTiming.ON_CAST_MAGIC,
            fn=_select_and_boost_minion,
            condition=_self_cast,
            target_kind="ally_minion",
            min_targets=1,
            max_targets=1,
            official_effect="このバトル中、自分のミニオン1体をBP+200する",
            official_timing="フラッシュ",
        ),
        EffectSpec(
            timing=EffectTiming.ON_BATTLE_WIN,
            fn=_return_after_battle_win,
            condition=_selected_minion_won,
            target_kind="trash_magic_cost_at_most_4",
            min_targets=1,
            max_targets=1,
            active_areas=(AreaType.TRASH,),
            params={"card_id": CARD_ID},
            official_effect="そのミニオンがバトルに勝利した場合、トラッシュのビルドアップ1枚を手札に戻す",
            official_timing="バトル勝利時",
        ),
    ]
    return card
