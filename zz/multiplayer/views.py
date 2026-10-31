from __future__ import annotations

import json
from copy import deepcopy
from typing import Any, Iterable

from zz.enums import AreaType
from zz.multiplayer.actions import PLAYER_IDS
from zz.multiplayer.protocol import MAX_MESSAGE_BYTES, ProtocolError
from zz.web.serialize import serialize_state


PLAYER_SIDE_BY_ID = {"player_1": "P1", "player_2": "P2"}
PRIVATE_AREAS = {"deck", "hand"}
_CARD_AREAS = {area.value for area in AreaType}
# Logs are a reconnectable window, not the diagnostic replay archive. Leave
# room for the board, prompts, animation batch and the largest wire envelope.
_LOG_BYTE_BUDGET = 65_536
_LIVE_LOG_EVENT_LIMIT = 20
_WIRE_ENVELOPE_RESERVE = 4_096
_LOG_EVENT_FIELDS = {
    "type", "eventIndex", "turn", "phase", "step", "activeSide",
    "actorName", "actorSide", "actionKind", "newColor", "direction",
    "blocked", "used", "winnerName", "winnerSide", "reason",
}
_LOG_ENTITY_FIELDS = {
    "cardId", "ownerSide", "area", "nameJp", "nameZh", "nameEn",
    "id", "forceId", "targetKind", "type", "playerName", "playerSide",
    "manaColor",
}
_LOG_EVENT_TYPES = {
    "raw", "action", "attack_target", "block", "base_replacement",
    "force_base_choice", "effect_target", "optional_effect", "reveal", "game_over",
}
_WIRE_ASSET_URL_KEYS = (
    "assetUrl",
    "assetUrlEn",
    "playmatUrl",
    "portraitUrl",
    "thumbnailUrl",
)


def _project_log_entity(value: Any, *, viewer_side: str, actor_side: str, public: bool) -> Any:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("log entity must be an object or null")
    area = value.get("area")
    owner_side = value.get("ownerSide")
    if value.get("cardId") or value.get("targetKind") == "card":
        if owner_side not in PLAYER_SIDE_BY_ID.values() or not isinstance(area, str) or area not in _CARD_AREAS:
            raise ValueError("log card entity requires a valid ownerSide and area")
    if any(item is not None and not isinstance(item, str)
           for key, item in value.items() if key in _LOG_ENTITY_FIELDS):
        raise ValueError("log entity display fields must be strings or null")
    # Selection itself grants no visibility into an opponent's hand. Current
    # deck/top choice contracts inspect only the chooser's own deck. This also
    # protects blind choices that finish resolution in another private zone.
    # Explicit public reveal events are projected independently.
    can_see = (public or area not in PRIVATE_AREAS
               or (viewer_side == owner_side and (area == "hand" or viewer_side == actor_side)))
    if not can_see:
        return {"targetKind": "card", "ownerSide": owner_side, "area": area, "faceDown": True}
    projected = {key: deepcopy(item) for key, item in value.items() if key in _LOG_ENTITY_FIELDS}
    for key in ("card", "force"):
        if key in value:
            projected[key] = _project_log_entity(
                value[key], viewer_side=viewer_side, actor_side=actor_side, public=public,
            )
    return projected


def _project_log_events(events: Iterable[dict[str, Any]], *, viewer_side: str) -> list[dict[str, Any]]:
    projected = []
    for event in events:
        if not isinstance(event, dict) or not isinstance(event.get("type"), str) or event["type"] not in _LOG_EVENT_TYPES:
            raise ValueError("log event has an unsupported type")
        event_index = event.get("eventIndex")
        if isinstance(event_index, bool) or not isinstance(event_index, int) or event_index < 0:
            raise ValueError("log eventIndex must be a non-negative integer")
        if "targets" in event and not isinstance(event["targets"], list):
            raise ValueError("log targets must be an array")
        if "battle" in event and not isinstance(event["battle"], dict):
            raise ValueError("log battle must be an object")
        # Diagnostic raw text, RL action payloads and target labels may include
        # hidden identities. Only the structured display contract crosses wire.
        row = {key: deepcopy(value) for key, value in event.items() if key in _LOG_EVENT_FIELDS}
        if any(value is not None and not isinstance(value, (str, int, bool)) for value in row.values()):
            raise ValueError("log event display fields must be scalar values")
        actor_side = str(event.get("actorSide") or "")
        public = event.get("type") != "effect_target"
        for key in ("card", "attacker", "blocker", "replacementCard", "replaced", "force", "target"):
            if key in event:
                row[key] = _project_log_entity(
                    event[key], viewer_side=viewer_side, actor_side=actor_side, public=public,
                )
        if "targets" in event:
            row["targets"] = [_project_log_entity(target, viewer_side=viewer_side,
                                                  actor_side=actor_side, public=public)
                              for target in event["targets"]]
        if "battle" in event:
            row["battle"] = {key: event["battle"][key] for key in ("attackerBp", "blockerBp")
                             if key in event["battle"]}
        projected.append(row)
    return projected


def _json_bytes(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8"))


def _validate_log_wire_budget(max_message_bytes: int, envelope_bytes: int) -> None:
    if isinstance(max_message_bytes, bool) or not isinstance(max_message_bytes, int) or max_message_bytes <= 0:
        raise ValueError("log wire budget must be a positive integer")
    if isinstance(envelope_bytes, bool) or not isinstance(envelope_bytes, int) or envelope_bytes < 0:
        raise ValueError("log envelope size must be a non-negative integer")


def _validate_log_indexes(events: Any) -> None:
    if not isinstance(events, list):
        raise ValueError("logEvents must be an array")
    previous_index = -1
    for event in events:
        index = event.get("eventIndex") if isinstance(event, dict) else None
        if isinstance(index, bool) or not isinstance(index, int) or index <= previous_index:
            raise ValueError("log eventIndex values must be increasing non-negative integers")
        previous_index = index


def fit_player_view_log_history(
    state: dict[str, Any], *, max_message_bytes: int = MAX_MESSAGE_BYTES,
    envelope_bytes: int = _WIRE_ENVELOPE_RESERVE,
) -> None:
    """Fit only the log suffix; callers must still validate/serialize the frame."""
    _validate_log_wire_budget(max_message_bytes, envelope_bytes)
    events = state["logEvents"]
    _validate_log_indexes(events)
    previous_history = state.get("logHistory")
    if previous_history is not None and (
        not isinstance(previous_history, dict) or not isinstance(previous_history.get("hasEarlierEvents"), bool)
    ):
        raise ValueError("logHistory must contain boolean hasEarlierEvents")
    had_earlier_events = previous_history is not None and previous_history["hasEarlierEvents"]

    def history() -> dict[str, Any]:
        return {
            **({key: previous_history[key] for key in ("canPage", "latestEventIndex") if key in previous_history}
               if previous_history is not None else {}),
            "hasEarlierEvents": had_earlier_events or bool(events and events[0]["eventIndex"] > 0)
                                or len(events) < original_count,
            "firstEventIndex": events[0]["eventIndex"] if events else None,
            "lastEventIndex": events[-1]["eventIndex"] if events else None,
        }

    original_count = len(events)
    state["logEvents"] = events
    state["logHistory"] = history()
    while events and (_json_bytes(events) > _LOG_BYTE_BUDGET
                      or _json_bytes(state) + envelope_bytes > max_message_bytes):
        del events[0]
        state["logHistory"] = history()


def fit_player_log_page(
    page: dict[str, Any], *, max_message_bytes: int = MAX_MESSAGE_BYTES,
    envelope_bytes: int = _WIRE_ENVELOPE_RESERVE,
) -> None:
    """Fit an archive page without ever returning a non-progressing empty page."""
    _validate_log_wire_budget(max_message_bytes, envelope_bytes)
    events = page["events"]
    _validate_log_indexes(events)
    last_index = events[-1]["eventIndex"] if events else None

    def update_window() -> None:
        page.update({
            "hasEarlierEvents": bool(events and events[0]["eventIndex"] > 0),
            "firstEventIndex": events[0]["eventIndex"] if events else None,
            "lastEventIndex": events[-1]["eventIndex"] if events else None,
        })

    update_window()
    while events and (_json_bytes(events) > _LOG_BYTE_BUDGET
                      or _json_bytes(page) + envelope_bytes > max_message_bytes):
        del events[0]
        update_window()
    if last_index is not None and not events:
        raise ProtocolError(
            "LOG_EVENT_TOO_LARGE", f"log event {last_index} cannot fit the configured message budget",
        )


def build_player_log_archive(session: Any, *, player_id: str) -> list[dict[str, Any]]:
    player = player_for_id(session, player_id)
    return _project_log_events(session._codeman_trace_events, viewer_side=player.side.name)


def build_projected_log_page(
    archive: list[dict[str, Any]], *, match_id: str, before_event_index: int,
) -> dict[str, Any]:
    if (isinstance(before_event_index, bool) or not isinstance(before_event_index, int)
            or not 0 <= before_event_index <= len(archive)):
        raise ValueError("log history cursor must be between zero and the latest eventIndex plus one")
    return _build_log_page(deepcopy(archive[max(0, before_event_index - 80):before_event_index]),
                           match_id=match_id, before_event_index=before_event_index)


def build_player_log_page(
    session: Any, *, match_id: str, player_id: str, before_event_index: int,
) -> dict[str, Any]:
    player = player_for_id(session, player_id)
    archive = session._codeman_trace_events
    if (isinstance(before_event_index, bool) or not isinstance(before_event_index, int)
            or not 0 <= before_event_index <= len(archive)):
        raise ValueError("log history cursor must be between zero and the latest eventIndex plus one")
    events = _project_log_events(archive[max(0, before_event_index - 80):before_event_index],
                                viewer_side=player.side.name)
    return _build_log_page(events, match_id=match_id, before_event_index=before_event_index)


def _build_log_page(events: list[dict[str, Any]], *, match_id: str, before_event_index: int) -> dict[str, Any]:
    page = {
        "matchId": match_id,
        "beforeEventIndex": before_event_index,
        "events": events,
        "hasEarlierEvents": bool(events and events[0]["eventIndex"] > 0),
        "firstEventIndex": events[0]["eventIndex"] if events else None,
        "lastEventIndex": events[-1]["eventIndex"] if events else None,
    }
    fit_player_log_page(page)
    return page


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


def _strip_wire_asset_urls(value: Any) -> Any:
    if isinstance(value, dict):
        for key in _WIRE_ASSET_URL_KEYS:
            value.pop(key, None)
        for item in value.values():
            _strip_wire_asset_urls(item)
        return value
    if isinstance(value, list):
        for item in value:
            _strip_wire_asset_urls(item)
    return value


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
    prompt = deepcopy(session.prompt_for_side(player.side.name))
    state = serialize_state(
        session.engine,
        human=player,
        asset_index=session.asset_index,
        prompt=prompt,
        log=[],
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
    _strip_wire_asset_urls(state)
    state["logEvents"] = _project_log_events(session._log_events[-_LIVE_LOG_EVENT_LIMIT:], viewer_side=player.side.name)
    state["logHistory"] = {
        "canPage": True,
        "latestEventIndex": session._codeman_trace_events[-1]["eventIndex"] if session._codeman_trace_events else None,
        "hasEarlierEvents": False,
    }
    fit_player_view_log_history(state)
    return state
