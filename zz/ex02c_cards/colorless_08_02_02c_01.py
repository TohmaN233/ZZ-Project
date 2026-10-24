from __future__ import annotations

from itertools import count
from typing import Any

from zz.effects import EffectSpec, EffectTiming
from zz.enums import AreaType, CardType
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "colorless_08_02_02c_01"
_buff_serial = count(1)


def _self_summoned(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source


def _has_race(target: CardInstance, race: str) -> bool:
    return race in target.card.race_jp.split("|")


def _eligible_destroy_targets(source: CardInstance, state: Any) -> list[CardInstance]:
    engine = state.engine
    return engine._eligible_targets(
        source.owner,
        "enemy_minion",
        filter_fn=lambda target: (
            target.card.type in (CardType.F_MINION, CardType.B_MINION)
            and engine.effective_bp(target) <= 400
            and not engine.is_protected_from_card_effect(
                target,
                source=source,
                operation="destroy",
            )
        ),
        source=source,
    )


def _eligible_buff_targets(source: CardInstance, state: Any) -> list[CardInstance]:
    return state.engine._eligible_targets(
        source.owner,
        "ally_minion",
        filter_fn=lambda target: (
            target.card.type in (CardType.F_MINION, CardType.B_MINION)
            and (_has_race(target, "黒の剣士") or _has_race(target, "閃光"))
        ),
        source=source,
    )


def _choice_target_kind(source: CardInstance, state: Any, _ctx: Context) -> str | None:
    if _eligible_destroy_targets(source, state):
        return None
    return "ally_minion" if _eligible_buff_targets(source, state) else None


def _destroy_or_buff(source: CardInstance, state: Any, _ctx: Context) -> None:
    engine = state.engine
    owner = source.owner
    targets = _eligible_destroy_targets(source, state)
    if targets:
        for target in list(targets):
            engine.destroy_target(target, source)
        return
    buff_targets = _eligible_buff_targets(source, state)
    if not buff_targets:
        return
    selected = engine.select_target(
        owner,
        "ally_minion",
        1,
        1,
        filter_fn=lambda target: target in buff_targets,
        source=source,
    )
    if len(selected) != 1:
        raise RuntimeError(f"{CARD_ID} expected one Switch buff target, got {len(selected)}")
    target = selected[0]
    serial = next(_buff_serial)
    marker = f"ex02c:{CARD_ID}:next-own-end:{state.turn}:{source.iid}:{target.iid}:{serial}"
    target.flags.add(marker)
    engine.modify_stat(target, bp_delta=300, dp_delta=1, duration="permanent")

    def expire_buff() -> None:
        if marker not in target.flags:
            return
        target.flags.remove(marker)
        engine.modify_stat(target, bp_delta=-300, dp_delta=-1, duration="permanent")

    engine.schedule_turn_end_effect(owner, expire_buff)


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.effects = list(card.effects) + [
        EffectSpec(
            timing=EffectTiming.ON_SUMMON,
            fn=_destroy_or_buff,
            target_kind_resolver=_choice_target_kind,
            condition=_self_summoned,
            params={
                "races_any": ["黒の剣士", "閃光"],
                "ex02c_switch_races": ["黒の剣士"],
            },
            active_areas=(AreaType.FIELD,),
            official_effect="相手のBP400以下のミニオン全てを破壊する。破壊するミニオンがいない場合、次の自分のターン終了時まで、自分の種族「黒の剣士」または「閃光」を持つミニオン1体をBP+300/DP+1する",
            official_timing="召喚時＆スイッチ",
        )
    ]
    return card
