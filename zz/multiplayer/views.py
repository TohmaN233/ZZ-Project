from __future__ import annotations

from copy import deepcopy
from typing import Any

from zz.multiplayer.actions import PLAYER_IDS
from zz.web.serialize import serialize_state


PLAYER_SIDE_BY_ID = {"player_1": "P1", "player_2": "P2"}


def player_for_id(session: Any, player_id: str) -> Any:
    side = PLAYER_SIDE_BY_ID.get(player_id)
    if side is None:
        raise ValueError(f"unknown player id {player_id!r}")
    return next(player for player in session.engine.state.players if player.side.name == side)


def player_id_for_side(side: str) -> str:
    for player_id, candidate in PLAYER_SIDE_BY_ID.items():
        if candidate == side:
            return player_id
    raise ValueError(f"unknown player side {side!r}")


def build_player_view(
    session: Any,
    *,
    player_id: str,
    revision: int,
    state_hash: str,
) -> dict[str, Any]:
    if player_id not in PLAYER_IDS:
        raise ValueError(f"unknown player id {player_id!r}")
    player = player_for_id(session, player_id)
    prompt = None
    if session.prompt_controller_side() == player.side.name:
        prompt = deepcopy(session.prompt)
    state = serialize_state(
        session.engine,
        human=player,
        asset_index=session.asset_index,
        prompt=prompt,
        log=list(session._log),
        log_events=[],
        mode="multiplayer",
        game_over=deepcopy(session._game_over),
        reveal_all_hands=False,
        animation_events=[],
    )
    for hidden_card in state["players"]["opponent"]["hand"]:
        hidden_card.pop("iid", None)
    state.update({
        "playerId": player_id,
        "revision": revision,
        "stateHash": state_hash,
        "seats": {"left": "P1", "right": "P2"},
        "pendingAttack": deepcopy(session._pending_attack_payload()),
        "publicReveals": [],
    })
    return state
