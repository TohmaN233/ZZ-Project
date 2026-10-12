from __future__ import annotations

from typing import Any

from zz.effects import EffectSpec, EffectTiming
from zz.enums import AreaType, CardType, Color
from zz.model import CardInstance, Context
from zz.pc01 import _card_from_row


CARD_ID = "yellow_04_02_02r_00"
_BLOCK_FLAG_PREFIX = "pc02r:dragon_blockers_only:"
_TRACK_FLAG_PREFIX = "turn:pc02r_karapace_target:"


def _self_summoned(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.source is source


def _grant_dragon_only_blocking(source: CardInstance, state: Any, _ctx: Context) -> None:
    engine = state.engine
    eligible = [
        target
        for target in source.owner.field
        if target.card.type is CardType.F_MINION
        and target.card.printed_color is Color.YELLOW
    ]
    if not eligible:
        return
    selected = engine.select_target(
        source.owner,
        "ally_minion",
        1,
        1,
        filter_fn=lambda target: (
            target.card.type is CardType.F_MINION
            and target.card.printed_color is Color.YELLOW
        ),
        source=source,
    )
    if len(selected) != 1:
        raise RuntimeError(f"{CARD_ID} expected one Yellow Field Minion, received {len(selected)}")
    target = selected[0]
    block_flag = f"{_BLOCK_FLAG_PREFIX}{source.iid}"
    target.flags.add(block_flag)
    source.flags.add(f"{_TRACK_FLAG_PREFIX}{target.iid}:{source.iid}")


def _own_turn_ended_with_grant(source: CardInstance, _state: Any, ctx: Context) -> bool:
    return ctx.controller is source.owner and any(
        flag.startswith(_TRACK_FLAG_PREFIX) for flag in source.flags
    )


def _clear_turn_grants(source: CardInstance, state: Any, _ctx: Context) -> None:
    tracks = [flag for flag in source.flags if flag.startswith(_TRACK_FLAG_PREFIX)]
    for track in tracks:
        parts = track.split(":")
        if len(parts) != 4:
            raise RuntimeError(f"malformed {CARD_ID} turn-grant marker: {track!r}")
        target_iid = int(parts[2])
        source_iid = int(parts[3])
        if source_iid != source.iid:
            raise RuntimeError(f"{CARD_ID} grant marker belongs to source iid={source_iid}")
        block_flag = f"{_BLOCK_FLAG_PREFIX}{source.iid}"
        for player in state.players:
            for zone in (player.field, player.base, player.hand, player.trash, player.deck, player.removed):
                for target in zone:
                    if target.iid == target_iid:
                        target.flags.discard(block_flag)
        source.flags.discard(track)


def build_card(row: dict[str, Any]):
    if str(row.get("image_id") or "").strip() != CARD_ID:
        raise ValueError(f"{CARD_ID} cannot build row {row.get('image_id')!r}")
    card = _card_from_row(row, infer_effects=False)
    card.effects = list(card.effects) + [
        EffectSpec(
            timing=EffectTiming.ON_SUMMON,
            fn=_grant_dragon_only_blocking,
            condition=_self_summoned,
            target_kind="ally_minion",
            min_targets=1,
            max_targets=1,
            params={"color": Color.YELLOW, "card_type": CardType.F_MINION},
            official_effect="このターン中、自分の黄のミニオン1体は種族「ドラゴン」または「ドラゴニュート」を持たないミニオンにブロックされない",
            official_timing="召喚時",
        ),
        EffectSpec(
            timing=EffectTiming.TURN_END,
            fn=_clear_turn_grants,
            condition=_own_turn_ended_with_grant,
            official_effect="この効果の期限を終了する",
            official_timing="自分のターン終了時",
        ),
    ]
    return card
