from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming
from zz.engine import FIELD_CAP
from zz.enums import CardType, Keyword
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "purple_07_02_02r_01"


def _this_minion_attacks(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source


def _this_minion_was_transformed(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source


def _destroy_other_dragons_on_transform(source: CardInstance, state: Any, _ctx: Context) -> None:
    engine = state.engine
    for player in state.players:
        for target in list(player.field):
            if target is source or target.card.type not in (CardType.F_MINION, CardType.B_MINION):
                continue
            if "ドラゴン" in target.card.race_jp:
                engine.destroy_target(target, source)


def _low_cost_field_minion(card: CardInstance) -> bool:
    return card.card.type is CardType.F_MINION and sum(card.card.cost.values()) <= 3


def _retrieve_minions_after_attack(source: CardInstance, state: Any, _ctx: Context) -> None:
    engine = state.engine
    opponent = state.players[1 - state.players.index(source.owner)]
    destroyed_force_count = sum(1 for force in opponent.forces if force.destroyed)
    eligible_targets = engine._eligible_targets(
        source.owner,
        "trash_field_minion",
        filter_fn=_low_cost_field_minion,
        source=source,
    )
    eligible_count = len(eligible_targets)
    retrieve_count = min(destroyed_force_count, eligible_count)
    if retrieve_count == 0:
        return
    selected = engine.select_target(
        source.owner,
        "trash_field_minion",
        retrieve_count,
        retrieve_count,
        filter_fn=_low_cost_field_minion,
        source=source,
    )
    if len(selected) != retrieve_count:
        raise RuntimeError(
            f"Rekindled expected {retrieve_count} Trash targets, got {len(selected)}"
        )
    for card in selected:
        replacement_iid = None
        if len(source.owner.field) >= FIELD_CAP:
            replacements = engine.select_target(source.owner, "ally_minion", 1, 1, source=source)
            if len(replacements) != 1:
                raise RuntimeError("Rekindled's attack needs one Field replacement")
            replacement_iid = replacements[0].iid
        engine.summon_from_trash(
            source.owner,
            card,
            replace_field_iid=replacement_iid,
        )


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    if Keyword.RUSH not in card.keywords:
        card.keywords = list(card.keywords) + [Keyword.RUSH]
    card.effects = list(card.effects) + [
        EffectSpec(
            timing=EffectTiming.ON_TRANSFORM,
            fn=_destroy_other_dragons_on_transform,
            condition=_this_minion_was_transformed,
            official_effect="変形時に他のドラゴン族ミニオン全てを破壊する",
            official_timing="変形時",
        ),
        EffectSpec(
            timing=EffectTiming.ON_ATTACK,
            fn=_retrieve_minions_after_attack,
            condition=_this_minion_attacks,
            target_kind="trash_field_minion",
            min_targets=1,
            max_targets=2,
            params={
                "exact_target_count_from_opponent_destroyed_forces": True,
                "max_cost": 3,
                "puts_targets_on_field": True,
            },
            official_effect="自分のトラッシュから相手の破壊済みForce数と同数のコスト3以下のField Minionを出す",
            official_timing="アタック時",
        )
    ]
    return card
