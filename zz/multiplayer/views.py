from __future__ import annotations

from copy import deepcopy
from typing import Any

from zz.multiplayer.actions import PLAYER_IDS
from zz.web.serialize import serialize_state


PLAYER_SIDE_BY_ID = {"player_1": "P1", "player_2": "P2"}
PRIVATE_AREAS = {"deck", "hand"}


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


def _hidden_animation_card(
    card: dict[str, Any],
    *,
    owner_side: str,
    area: str,
    asset_index: Any,
) -> dict[str, Any]:
    return {
        "ownerSide": owner_side,
        "faceDown": True,
        "assetId": "card_back",
        "assetUrl": asset_index.asset_url("card_back"),
        "area": area,
        "rested": bool(card.get("rested", False)),
    }


def _project_animation_events(
    events: tuple[dict[str, Any], ...] | list[dict[str, Any]],
    *,
    viewer_side: str,
    asset_index: Any,
) -> list[dict[str, Any]]:
    projected = deepcopy(list(events))
    for event in projected:
        event_side = str(event.get("side") or "")
        if event_side == viewer_side:
            continue
        if event.get("type") == "draw":
            event["cards"] = [
                _hidden_animation_card(
                    card,
                    owner_side=event_side,
                    area="hand",
                    asset_index=asset_index,
                )
                for card in event.get("cards") or []
            ]
            continue
        if event.get("type") != "zone_move":
            continue
        from_area = str(event.get("fromArea") or "")
        to_area = str(event.get("toArea") or "")
        if from_area not in PRIVATE_AREAS or to_area not in PRIVATE_AREAS:
            continue
        card = event.get("card")
        if isinstance(card, dict):
            event["card"] = _hidden_animation_card(
                card,
                owner_side=event_side,
                area=to_area,
                asset_index=asset_index,
            )
    return projected


def build_player_view(
    session: Any,
    *,
    player_id: str,
    revision: int,
    state_hash: str,
    animation_events: tuple[dict[str, Any], ...] | list[dict[str, Any]] = (),
    public_reveals: tuple[dict[str, Any], ...] | list[dict[str, Any]] = (),
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
        animation_events=_project_animation_events(
            animation_events,
            viewer_side=player.side.name,
            asset_index=session.asset_index,
        ),
    )
    for hidden_card in state["players"]["opponent"]["hand"]:
        hidden_card.pop("iid", None)
    state.update({
        "playerId": player_id,
        "revision": revision,
        "stateHash": state_hash,
        "seats": {"left": "P1", "right": "P2"},
        "pendingAttack": deepcopy(session._pending_attack_payload()),
        "publicReveals": deepcopy(list(public_reveals)),
    })
    return state
