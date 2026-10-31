import base64
import json

from zz.enums import AreaType
from zz.multiplayer.compatibility import hello_compatibility_payload
from zz.multiplayer.protocol import MAX_MESSAGE_BYTES, PROTOCOL_VERSION, serialize_server_message
from zz.multiplayer.websocket_server import WebSocketMultiplayerGateway


def test_reconnect_delivers_a_large_real_snapshot_in_bounded_fragments():
    from test_multiplayer_reconnect import TimerFactory, _connected_server, _message, _start_match

    core, messages = _connected_server(TimerFactory())
    tokens = _start_match(core, messages)
    match = core.match_for_room("ABC123")
    card = match.session.engine.state.players[0].hand[0]
    match.session._animation_events.clear()
    for _ in range(400):
        match.session._queue_zone_move_animation_event(card, AreaType.HAND, AreaType.TRASH)
    match._animation_events = tuple(match.session._animation_events)
    match.session._animation_events.clear()
    expected = match.get_view_for("player_1")
    envelope = {
        "protocolVersion": PROTOCOL_VERSION,
        "messageId": "oversized-snapshot",
        "type": "STATE_SNAPSHOT",
        "payload": {"matchId": match.match_id, "view": expected},
    }
    assert len(serialize_server_message(envelope, max_bytes=2_000_000).encode("utf-8")) > MAX_MESSAGE_BYTES
    assert expected["logEvents"] == []
    core.disconnect("a")

    class ReconnectSocket:
        def __init__(self):
            self.sent = []
            self.request = type("Request", (), {"headers": {"X-ZZ-Client-Features": "replay-fragments-v1"}})()

        def recv(self, *, timeout):
            return json.dumps(_message("hello", "HELLO", hello_compatibility_payload()))

        def __iter__(self):
            yield json.dumps(_message("capabilities", "ENABLE_MESSAGE_FRAGMENTS", {}))
            yield json.dumps(_message("reconnect", "RECONNECT", {
                "roomCode": "ABC123", "playerId": "player_1", "reconnectToken": tokens["player_1"],
            }))

        def send(self, encoded):
            self.sent.append(encoded)

    socket = ReconnectSocket()
    gateway = WebSocketMultiplayerGateway(core, connection_id_factory=lambda: "large-reconnect")
    gateway.handle_connection(socket)
    messages = [json.loads(raw) for raw in socket.sent]
    assert all(len(raw.encode("utf-8")) <= MAX_MESSAGE_BYTES for raw in socket.sent)
    fragments = [message["payload"] for message in messages if message["type"] == "MESSAGE_FRAGMENT"]
    assert fragments, messages
    assert [part["index"] for part in fragments] == list(range(len(fragments)))
    assert all(part["count"] == len(fragments) for part in fragments)
    restored = json.loads(b"".join(base64.b64decode(part["data"], validate=True) for part in fragments))
    assert restored["type"] == "STATE_SNAPSHOT"
    assert restored["payload"]["view"] == expected


def test_replay_frames_restore_past_revisions_with_viewer_private_information_only():
    from test_multiplayer_reconnect import TimerFactory, _connected_server, _latest, _send, _start_match

    core, messages = _connected_server(TimerFactory())
    _start_match(core, messages)
    match = core.match_for_room("ABC123")
    initial = match.get_view_for("player_1")
    for index in range(3):
        owner = match.prompt_owner_id()
        prompt = match.get_view_for(owner)["prompt"]
        option = next((row for row in prompt["options"] if row["id"] == "keep"), prompt["options"][0])
        _send(core, "a" if owner == "player_1" else "b", "SUBMIT_ACTION", {
            "matchId": match.match_id, "playerId": owner, "clientActionId": f"replay-{index}",
            "expectedRevision": match.revision, "action": {"kind": "CHOOSE_PROMPT_OPTION",
                "promptId": prompt["id"], "optionId": option["id"], "payload": {}},
        })
    assert match.revision == 3
    _send(core, "a", "REQUEST_REPLAY_FRAME", {"matchId": match.match_id, "revision": 0})
    restored = _latest(messages["a"], "REPLAY_FRAME")["view"]
    assert restored["revision"] == 0
    assert restored["stateHash"] == initial["stateHash"]
    assert restored["players"]["human"]["hand"] == initial["players"]["human"]["hand"]
    assert all(card.get("faceDown") and "cardId" not in card and "iid" not in card
               for card in restored["players"]["opponent"]["hand"])
    assert restored["logEvents"] == []
    _send(core, "b", "REQUEST_REPLAY_FRAME", {"matchId": match.match_id, "revision": 0})
    opposite = _latest(messages["b"], "REPLAY_FRAME")["view"]
    assert opposite["humanSide"] == "P2"
    assert all(card.get("faceDown") and "cardId" not in card
               for card in opposite["players"]["opponent"]["hand"])
    _send(core, "b", "REQUEST_REPLAY_FRAME", {"matchId": match.match_id, "revision": 0, "playerId": "player_1"})
    assert _latest(messages["b"], "ERROR")["code"] == "INVALID_MESSAGE"


def test_legacy_client_gets_a_clear_size_error_without_unnegotiated_fragments():
    from test_multiplayer_reconnect import TimerFactory, _connected_server, _message, _start_match

    core, messages = _connected_server(TimerFactory())
    observed = []
    core._event_sink = lambda event, **fields: observed.append((event, fields))
    tokens = _start_match(core, messages)
    match = core.match_for_room("ABC123")
    card = match.session.engine.state.players[0].hand[0]
    match.session._animation_events.clear()
    for _ in range(400):
        match.session._queue_zone_move_animation_event(card, AreaType.HAND, AreaType.TRASH)
    match._animation_events = tuple(match.session._animation_events)
    match.session._animation_events.clear()
    core.disconnect("a")

    class LegacySocket:
        def __init__(self):
            self.sent = []

        def recv(self, *, timeout):
            return json.dumps(_message("hello", "HELLO", hello_compatibility_payload()))

        def __iter__(self):
            yield json.dumps(_message("reconnect", "RECONNECT", {
                "roomCode": "ABC123", "playerId": "player_1", "reconnectToken": tokens["player_1"],
            }))

        def send(self, encoded):
            self.sent.append(json.loads(encoded))

    socket = LegacySocket()
    WebSocketMultiplayerGateway(core, connection_id_factory=lambda: "legacy-reconnect").handle_connection(socket)
    welcome = next(row["payload"] for row in socket.sent if row["type"] == "WELCOME")
    assert set(welcome) == {"connectionId", "compatibility", "recoveryPersistenceAck"}
    assert not any(row["type"] == "MESSAGE_FRAGMENT" for row in socket.sent)
    error = next(row["payload"] for row in socket.sent if row["type"] == "ERROR")
    assert error["code"] == "MESSAGE_TOO_LARGE"
    metrics = next(fields for event, fields in observed if event == "outbound_message_too_large")
    assert metrics["messageBytes"] > metrics["messageLimit"] == MAX_MESSAGE_BYTES
    assert metrics["animationBytes"] > MAX_MESSAGE_BYTES
    assert metrics["logBytes"] == 2  # Empty JSON array; no historical log was transmitted.
    assert set(metrics) <= {"level", "connectionId", "messageType", "messageBytes", "messageLimit", "viewBytes",
                            "logBytes", "animationBytes", "boardBytes", "promptBytes"}
    assert tokens["player_1"] not in json.dumps(metrics)
