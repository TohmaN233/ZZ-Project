import json
from copy import deepcopy

import pytest

from zz.enums import AreaType
from zz.model import Action
from zz.multiplayer.actions import CHOOSE_PROMPT_OPTION, SubmittedAction
from zz.multiplayer.match import AuthoritativeMatch, InitialMatchSpec
from zz.multiplayer.protocol import MAX_MESSAGE_BYTES, PROTOCOL_VERSION, serialize_server_message
from zz.web.serialize import serialize_card


def _match():
    return AuthoritativeMatch(InitialMatchSpec.standard(match_id="battle-log", seed=701))


def _progress(match, count=8):
    for index in range(count):
        owner = match.prompt_owner_id()
        prompt = match.get_view_for(owner)["prompt"]
        options = prompt["options"]
        selected = next((o for o in options if o["id"] == "keep"), None)
        if selected is None:
            selected = next((o for kind in ("end_turn", "skip_mana", "place_colorless_mana")
                             for o in options if o.get("kind") == kind), options[0])
        result = match.submit_action(SubmittedAction(
            match_id=match.match_id, player_id=owner, client_action_id=f"act-{index}",
            expected_revision=match.revision,
            action={"kind": CHOOSE_PROMPT_OPTION, "promptId": prompt["id"],
                    "optionId": selected["id"], "payload": {}},
        ))
        assert result.accepted, result.rejection


def _wire(view):
    return serialize_server_message({"protocolVersion": PROTOCOL_VERSION, "messageId": "snapshot",
                                     "type": "STATE_SNAPSHOT", "payload": {"matchId": "battle-log", "view": view}})


def test_real_two_player_actions_produce_ordered_structured_logs():
    match = _match()
    _progress(match)
    first, second = (match.get_view_for(p) for p in ("player_1", "player_2"))
    assert first["logEvents"], "multiplayer must use the existing GameSession structured log"
    assert first["logEvents"] == second["logEvents"]
    assert [e["eventIndex"] for e in first["logEvents"]] == sorted(e["eventIndex"] for e in first["logEvents"])
    assert {e.get("actorSide") for e in first["logEvents"]} >= {"P1", "P2"}
    assert first["log"] == second["log"] == []
    assert not first["logHistory"]["hasEarlierEvents"]
    assert json.loads(_wire(first))["payload"]["view"]["logEvents"] == first["logEvents"]


def test_two_clients_receive_battle_history_through_real_server_actions():
    from test_multiplayer_in_memory import _clients, _start_match, _prompt_action

    server, first, second = _clients()
    _start_match(first, second)
    for index in range(8):
        owner = first if first.gameplay_view.get("prompt") is not None else second
        owner.submit_action(_prompt_action(owner), client_action_id=f"battle-{index}")
        assert owner.last_action_result["result"]["accepted"]
    assert first.gameplay_view["logEvents"]
    assert first.gameplay_view["logEvents"] == second.gameplay_view["logEvents"]
    match = server.match_for_room(first.room_state["roomCode"])
    assert first.gameplay_view["logEvents"] == match.get_view_for("player_1")["logEvents"]
    assert first.gameplay_view["log"] == second.gameplay_view["log"] == []
    assert first.gameplay_view["revision"] == second.gameplay_view["revision"] == 8


@pytest.mark.parametrize("actor_side,owner_id,opponent_id", [("P1", "player_1", "player_2"), ("P2", "player_2", "player_1")])
@pytest.mark.parametrize("area", ["deck", "hand"])
def test_private_target_log_never_exposes_identity_or_raw_action(actor_side, owner_id, opponent_id, area):
    match = _match()
    actor = next(p for p in match.session.engine.state.players if p.side.name == actor_side)
    secret_card = getattr(actor, area)[0]
    secret = serialize_card(match.session.engine, secret_card, match.session.asset_index)
    # Real effect-target and action producers include more diagnostic data than is public.
    event = {"type": "effect_target", "actorSide": actor_side, "actorName": actor.name,
             "targets": [dict(match.session._effect_target_log_payload(secret_card), targetLabel="private-name")],
             "action": {"payload": {"secret": secret, "reconnectToken": "secret-token"}}}
    match.session._log_event("private-name secret-token", event)
    original = deepcopy(match.session._log_events)
    own = match.get_view_for(owner_id)
    other = match.get_view_for(opponent_id)
    assert own["logEvents"][-1]["targets"][0]["cardId"] == secret["cardId"]
    hidden = other["logEvents"][-1]["targets"][0]
    assert hidden == {"targetKind": "card", "ownerSide": actor_side, "area": area, "faceDown": True}
    for view in (own, other):
        text = json.dumps({"logEvents": view["logEvents"], "log": view["log"]})
        assert "private-name" not in text
        assert "secret-token" not in text
        assert "rawText" not in text and '"action"' not in text
    assert match.session._log_events == original
    own["logEvents"][-1]["targets"][0]["nameJp"] = "mutated"
    assert match.get_view_for(owner_id)["logEvents"][-1]["targets"][0]["nameJp"] != "mutated"


def test_played_and_explicitly_revealed_private_zone_cards_are_public():
    match = _match()
    actor = match.session.engine.state.players[0]
    card = actor.hand[0]
    action = Action("play_card", {"iid": card.iid})
    match.session._log_event("private diagnostics", match.session._action_log_event(actor, action, "private diagnostics"))
    match.session.engine.public_reveals.append((actor, actor.deck[0], "公開"))
    match.session._log_public_reveals()
    logs = match.get_view_for("player_2")["logEvents"]
    assert [event["type"] for event in logs] == ["action", "reveal"]
    assert logs[0]["card"]["cardId"] == card.card.id
    assert logs[1]["card"]["cardId"] == actor.deck[0].card.id
    assert logs[1]["reason"] == "公開"


def test_long_log_window_is_explicit_compact_and_valid_wire_data():
    match = _match()
    actor = match.session.engine.state.players[0]
    card = serialize_card(match.session.engine, actor.hand[0], match.session.asset_index)
    for index in range(105):
        match.session._log_event(f"event-{index}", {"type": "reveal", "actorSide": "P1", "card": card, "reason": "公開"})
    view = match.get_view_for("player_2")
    assert view["logEvents"]
    assert len(view["logEvents"]) == 20
    assert view["logHistory"] == {"canPage": True, "latestEventIndex": 104,
                                  "hasEarlierEvents": True, "firstEventIndex": 85, "lastEventIndex": 104}
    assert "abilityJp" not in view["logEvents"][0]["card"]
    assert len(_wire(view).encode("utf-8")) < MAX_MESSAGE_BYTES


@pytest.mark.parametrize("viewer_id", ["player_1", "player_2"])
def test_foreign_deck_target_is_not_visible_without_a_public_reveal(viewer_id):
    match = _match()
    chooser, owner = match.session.engine.state.players
    secret = owner.deck[0]
    match.session._log_event("private deck choice", {
        "type": "effect_target", "actorSide": chooser.side.name,
        "targets": [match.session._effect_target_log_payload(secret)],
    })
    # A later zone change must not grant visibility into the historical foreign deck.
    owner.deck.remove(secret)
    owner.hand.append(secret)
    secret.area = AreaType.HAND
    target = match.get_view_for(viewer_id)["logEvents"][0]["targets"][0]
    assert target == {"targetKind": "card", "ownerSide": "P2", "area": "deck", "faceDown": True}


def test_both_players_reconnect_to_same_ordered_history_without_private_trace_or_credentials():
    from test_multiplayer_reconnect import TimerFactory, _connected_server, _start_match, _latest, _send

    server, messages = _connected_server(TimerFactory())
    tokens = _start_match(server, messages)
    match = server.match_for_room("ABC123")
    _progress(match, count=6)
    for connection_id, player_id in (("a", "player_1"), ("b", "player_2")):
        before = match.get_view_for(player_id)
        assert before["logEvents"]
        server.disconnect(connection_id)
        replacement = f"new-{connection_id}"
        messages[replacement] = []
        server.connect(replacement, messages[replacement].append)
        _send(server, replacement, "RECONNECT", {
            "roomCode": "ABC123", "playerId": player_id,
            "reconnectToken": tokens[player_id], "lastRevision": 0,
        })
        snapshot = _latest(messages[replacement], "STATE_SNAPSHOT")
        assert snapshot["view"]["logEvents"] == before["logEvents"]
        assert snapshot["view"]["logHistory"] == before["logHistory"]
        assert snapshot["view"]["humanSide"] == before["humanSide"]
        wire = _wire(snapshot["view"])
        assert "rawText" not in wire and "snapshotIndex" not in wire
        assert all(token not in wire for token in tokens.values())
        snapshot["view"]["logEvents"][0]["actorName"] = "changed on disconnected client"
        assert match.get_view_for(player_id)["logEvents"] == before["logEvents"]


def test_log_byte_budget_keeps_latest_suffix_and_marks_omitted_history():
    match = _match()
    for index in range(80):
        match.session._log_event("diagnostics", {"type": "reveal", "actorSide": "P1", "reason": "公開" * 2000})
    view = match.get_view_for("player_1")
    assert 0 < len(view["logEvents"]) < 80
    assert view["logEvents"][-1]["eventIndex"] == 79
    assert view["logHistory"]["hasEarlierEvents"] is True
    assert view["logHistory"]["firstEventIndex"] == view["logEvents"][0]["eventIndex"]
    assert len(_wire(view).encode("utf-8")) < MAX_MESSAGE_BYTES


def test_log_window_shrinks_to_fit_a_large_animation_snapshot():
    match = _match()
    for index in range(80):
        match.session._log_event("diagnostics", {"type": "reveal", "actorSide": "P1", "reason": "公開" * 2000})
    normal_count = len(match.get_view_for("player_1")["logEvents"])
    match._animation_events = ({"type": "wire-budget", "notes": ["x" * 4000] * 55},)
    view = match.get_view_for("player_1")
    assert 0 < len(view["logEvents"]) < normal_count
    assert view["logEvents"][-1]["eventIndex"] == 79
    assert view["logHistory"]["hasEarlierEvents"] is True
    assert len(_wire(view).encode("utf-8")) < MAX_MESSAGE_BYTES


@pytest.mark.parametrize("chooser_side,owner_index", [("P1", 1), ("P2", 0)])
def test_selecting_an_opponents_hand_card_does_not_grant_its_identity(chooser_side, owner_index):
    match = _match()
    owner = match.session.engine.state.players[owner_index]
    secret = owner.hand[0]
    match.session._log_event("blind hand choice", {
        "type": "effect_target", "actorSide": chooser_side,
        "targets": [match.session._effect_target_log_payload(secret)],
    })
    owner_id = "player_1" if owner_index == 0 else "player_2"
    chooser_id = "player_1" if chooser_side == "P1" else "player_2"
    assert match.get_view_for(owner_id)["logEvents"][-1]["targets"][0]["cardId"] == secret.card.id
    assert match.get_view_for(chooser_id)["logEvents"][-1]["targets"][0] == {
        "targetKind": "card", "ownerSide": owner.side.name, "area": "hand", "faceDown": True,
    }
    match.session.engine.public_reveals.append((owner, secret, "公開"))
    match.session._log_public_reveals()
    logs = match.get_view_for(chooser_id)["logEvents"]
    assert logs[-1]["type"] == "reveal"
    assert logs[-1]["card"]["cardId"] == secret.card.id
    assert logs[-2]["targets"][0]["faceDown"] is True


def test_configured_64k_gateway_fits_reconnected_history_without_touching_core_view():
    from test_multiplayer_reconnect import TimerFactory, _connected_server, _start_match, _message
    from zz.multiplayer.compatibility import hello_compatibility_payload
    from zz.multiplayer.websocket_server import WebSocketMultiplayerGateway, WebSocketServerConfig

    core, messages = _connected_server(TimerFactory())
    tokens = _start_match(core, messages)
    match = core.match_for_room("ABC123")
    for index in range(105):
        match.session._log_event("diagnostics", {"type": "reveal", "actorSide": "P1", "reason": "公開" * 2000})
    original = match.get_view_for("player_1")
    without_history = deepcopy(original)
    without_history["logEvents"] = []
    envelope = {"protocolVersion": PROTOCOL_VERSION, "messageId": "snapshot",
                "type": "STATE_SNAPSHOT", "payload": {"matchId": match.match_id, "view": without_history}}
    # The board fits this supported deployment configuration; only new logs need a smaller window.
    serialize_server_message(envelope, max_bytes=65_536)
    assert len(_wire(original).encode("utf-8")) > 65_536
    core.disconnect("a")

    class ReconnectSocket:
        def __init__(self):
            self.sent = []

        def recv(self, *, timeout):
            return json.dumps(_message("hello", "HELLO", hello_compatibility_payload()))

        def __iter__(self):
            yield json.dumps(_message("reconnect", "RECONNECT", {
                "roomCode": "ABC123", "playerId": "player_1", "reconnectToken": tokens["player_1"],
            }))

        def send(self, encoded):
            self.sent.append(encoded)

    socket = ReconnectSocket()
    gateway = WebSocketMultiplayerGateway(core, config=WebSocketServerConfig(max_message_bytes=65_536),
                                        connection_id_factory=lambda: "configured-gateway-reconnect")
    gateway.handle_connection(socket)
    snapshots = [json.loads(raw) for raw in socket.sent if json.loads(raw)["type"] == "STATE_SNAPSHOT"]
    assert snapshots, socket.sent
    actual = snapshots[-1]["payload"]["view"]
    assert 0 < len(actual["logEvents"]) < len(original["logEvents"])
    assert actual["logEvents"][-1]["eventIndex"] == original["logEvents"][-1]["eventIndex"]
    assert actual["logHistory"]["hasEarlierEvents"] is True
    assert actual["logHistory"]["firstEventIndex"] == actual["logEvents"][0]["eventIndex"]
    assert actual["logHistory"]["lastEventIndex"] == actual["logEvents"][-1]["eventIndex"]
    assert all(len(raw.encode("utf-8")) <= 65_536 for raw in socket.sent)
    assert match.get_view_for("player_1") == original


@pytest.mark.parametrize("event", [
    {"type": "not-a-supported-log-type"},
    {"type": "effect_target", "targets": "not-an-array"},
    {"type": "effect_target", "targets": ["not-an-object"]},
    {"type": "effect_target", "targets": [{"targetKind": "card", "cardId": "private-with-no-visibility"}]},
])
def test_malformed_log_projection_fails_explicitly(event):
    match = _match()
    match.session._log_event("diagnostics", event)
    with pytest.raises(ValueError, match="log"):
        match.get_view_for("player_1")


def test_all_history_pages_recover_every_event_and_can_fill_a_middle_gap():
    from zz.multiplayer.views import build_player_log_page

    match = _match()
    for index in range(205):
        match.session._log_event("diagnostics", {"type": "optional_effect", "actorSide": "P1", "used": True})
    view = match.get_view_for("player_1")
    assert view["logHistory"]["canPage"] is True
    assert view["logHistory"]["latestEventIndex"] == 204
    cursor = view["logHistory"]["latestEventIndex"] + 1
    recovered = {}
    while cursor:
        page = build_player_log_page(match.session, match_id=match.match_id, player_id="player_1",
                                     before_event_index=cursor)
        assert page["beforeEventIndex"] == cursor
        assert page["events"]
        assert page["lastEventIndex"] < cursor
        recovered.update({row["eventIndex"]: row for row in page["events"]})
        cursor = page["firstEventIndex"]
        assert page["hasEarlierEvents"] == (cursor > 0)
    assert sorted(recovered) == list(range(205))
    middle = build_player_log_page(match.session, match_id=match.match_id, player_id="player_1",
                                  before_event_index=125)
    assert [event["eventIndex"] for event in middle["events"]] == list(range(45, 125))
    empty = build_player_log_page(match.session, match_id=match.match_id, player_id="player_1",
                                 before_event_index=0)
    assert empty["events"] == [] and empty["hasEarlierEvents"] is False


@pytest.mark.parametrize("player_id,hidden", [("player_1", False), ("player_2", True)])
def test_archived_history_pages_reuse_private_projection_and_never_mutate_trace(player_id, hidden):
    from zz.multiplayer.views import build_player_log_page

    match = _match()
    owner = match.session.engine.state.players[0]
    for index in range(100):
        match.session._log_event("secret-token", {"type": "effect_target", "actorSide": "P1",
                                                  "targets": [match.session._effect_target_log_payload(owner.hand[0])]})
    trace = deepcopy(match.session._codeman_trace_events)
    page = build_player_log_page(match.session, match_id=match.match_id, player_id=player_id, before_event_index=20)
    target = page["events"][0]["targets"][0]
    assert bool(target.get("faceDown")) is hidden
    assert ("cardId" not in target) is hidden
    assert "secret-token" not in json.dumps(page)
    assert "rawText" not in json.dumps(page)
    target["nameJp"] = "local-only"
    assert match.session._codeman_trace_events == trace


def test_history_page_that_cannot_fit_one_event_reports_a_concrete_error():
    from zz.multiplayer.protocol import ProtocolError
    from zz.multiplayer.views import build_player_log_page, fit_player_log_page

    match = _match()
    match.session._log_event("diagnostics", {"type": "reveal", "actorSide": "P1", "reason": "公開" * 2000})
    page = build_player_log_page(match.session, match_id=match.match_id, player_id="player_1", before_event_index=1)
    with pytest.raises(ProtocolError) as caught:
        fit_player_log_page(page, max_message_bytes=1024, envelope_bytes=128)
    assert caught.value.code == "LOG_EVENT_TOO_LARGE"


def test_empty_snapshot_window_preserves_latest_history_cursor():
    from zz.multiplayer.views import fit_player_view_log_history

    match = _match()
    match.session._log_event("diagnostics", {"type": "optional_effect", "actorSide": "P1", "used": True})
    view = match.get_view_for("player_1")
    fit_player_view_log_history(view, max_message_bytes=1)
    assert view["logEvents"] == []
    assert view["logHistory"]["canPage"] is True
    assert view["logHistory"]["latestEventIndex"] == 0
    assert view["logHistory"]["hasEarlierEvents"] is True


def test_server_pages_finished_safe_history_rejects_forged_match_and_releases_archive():
    from test_multiplayer_reconnect import TimerFactory, _connected_server, _start_match, _latest, _send

    core, messages = _connected_server(TimerFactory())
    match_ids = iter(("match-1", "match-2"))
    core._match_id_factory = lambda: next(match_ids)
    _start_match(core, messages)
    match = core.match_for_room("ABC123")
    owner = match.session.engine.state.players[0]
    for index in range(100):
        match.session._log_event("secret-private-text", {"type": "effect_target", "actorSide": "P1",
                                                         "targets": [match.session._effect_target_log_payload(owner.hand[0])]})
    _send(core, "a", "SUBMIT_ACTION", {"matchId": "match-1", "playerId": "player_1", "clientActionId": "end-log-test",
                                      "expectedRevision": match.revision, "action": {"kind": "SURRENDER"}})
    assert core.match_for_room("ABC123") is None
    for connection, hidden in (("a", False), ("b", True)):
        _send(core, connection, "REQUEST_LOG_HISTORY", {"matchId": "match-1", "beforeEventIndex": 20})
        page = _latest(messages[connection], "LOG_HISTORY")
        assert bool(page["events"][0]["targets"][0].get("faceDown")) is hidden
        assert len(page["events"]) == 20
    serialized = json.dumps(core._finished_match_logs)
    assert "secret-private-text" not in serialized and "rawText" not in serialized
    assert "snapshotIndex" not in serialized and "reconnectToken" not in serialized
    _send(core, "a", "REQUEST_LOG_HISTORY", {"matchId": "forged-match", "beforeEventIndex": 20})
    assert _latest(messages["a"], "ERROR")["code"] == "MATCH_NOT_FOUND"
    _send(core, "b", "REQUEST_LOG_HISTORY", {"matchId": "match-1", "beforeEventIndex": 20, "playerId": "player_1"})
    assert _latest(messages["b"], "ERROR")["code"] == "INVALID_MESSAGE"
    _send(core, "a", "SET_READY", {"ready": True})
    _send(core, "b", "SET_READY", {"ready": True})
    _send(core, "a", "SELECT_OPENING_CHOICE", {"choice": "rock"})
    _send(core, "b", "SELECT_OPENING_CHOICE", {"choice": "scissors"})
    assert core._finished_match_logs == {}
    _send(core, "a", "REQUEST_LOG_HISTORY", {"matchId": "match-1", "beforeEventIndex": 20})
    assert _latest(messages["a"], "ERROR")["code"] == "MATCH_NOT_FOUND"
    current = core.match_for_room("ABC123")
    _send(core, "a", "SUBMIT_ACTION", {"matchId": "match-2", "playerId": "player_1", "clientActionId": "end-log-test-2",
                                      "expectedRevision": current.revision, "action": {"kind": "SURRENDER"}})
    assert core._finished_match_logs
    core.close_room("ABC123")
    assert core._finished_match_logs == {}


def test_post_resolution_foreign_hand_to_deck_stays_hidden_from_chooser():
    match = _match()
    chooser, owner = match.session.engine.state.players
    secret = owner.hand[0]
    match.session.engine.return_hand_card_to_deck_bottom(owner, secret, source=chooser.hand[0])
    match.session._log_event("target selected", {"type": "effect_target", "actorSide": chooser.side.name,
                                               "targets": [match.session._effect_target_log_payload(secret)]})
    assert match.get_view_for("player_1")["logEvents"][0]["targets"][0] == {
        "targetKind": "card", "ownerSide": "P2", "area": "deck", "faceDown": True,
    }


@pytest.mark.parametrize("page", [
    {"matchId": "m", "beforeEventIndex": 3, "events": [{"eventIndex": 2}, {"eventIndex": 1}],
     "hasEarlierEvents": True, "firstEventIndex": 2, "lastEventIndex": 1},
    {"matchId": "m", "beforeEventIndex": 3, "events": [{"eventIndex": 3}],
     "hasEarlierEvents": True, "firstEventIndex": 3, "lastEventIndex": 3},
    {"matchId": "m", "beforeEventIndex": 3, "events": [],
     "hasEarlierEvents": True, "firstEventIndex": None, "lastEventIndex": None},
    {"matchId": "m", "beforeEventIndex": 3, "events": [],
     "hasEarlierEvents": False, "firstEventIndex": None, "lastEventIndex": None},
    {"matchId": "m", "beforeEventIndex": 3, "events": [{"eventIndex": 1}],
     "hasEarlierEvents": True, "firstEventIndex": 1, "lastEventIndex": 1},
])
def test_wire_rejects_malformed_or_non_progressing_history_pages(page):
    from zz.multiplayer.protocol import ProtocolError

    with pytest.raises(ProtocolError):
        serialize_server_message({"protocolVersion": PROTOCOL_VERSION, "messageId": "page",
                                  "type": "LOG_HISTORY", "payload": page})


def test_history_page_metadata_is_included_in_exact_byte_budget():
    from zz.multiplayer.protocol import ProtocolError
    from zz.multiplayer.views import fit_player_log_page

    page = {"matchId": "m", "beforeEventIndex": 11, "events": [{"eventIndex": 9}, {"eventIndex": 10}],
            "hasEarlierEvents": True, "firstEventIndex": 9, "lastEventIndex": 10}
    only_last = dict(page, events=[{"eventIndex": 10}], firstEventIndex=10)
    limit = len(json.dumps(only_last, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) - 1
    with pytest.raises(ProtocolError) as caught:
        fit_player_log_page(page, max_message_bytes=limit, envelope_bytes=0)
    assert caught.value.code == "LOG_EVENT_TOO_LARGE"


@pytest.mark.parametrize("leave_mode", ["explicit", "expiry"])
def test_finished_history_is_unavailable_to_a_replacement_guest_after_original_guest_leaves(leave_mode):
    from test_multiplayer_reconnect import TimerFactory, _connected_server, _start_match, _latest, _send

    timers = TimerFactory()
    core, messages = _connected_server(timers)
    _start_match(core, messages)
    match = core.match_for_room("ABC123")
    _send(core, "a", "SUBMIT_ACTION", {"matchId": "match-1", "playerId": "player_1", "clientActionId": "end-seat-test",
                                      "expectedRevision": match.revision, "action": {"kind": "SURRENDER"}})
    assert core._finished_match_logs
    assert core._finished_match_frames
    # The original host can still page while both original seats remain reserved.
    _send(core, "a", "REQUEST_LOG_HISTORY", {"matchId": "match-1", "beforeEventIndex": 1})
    assert _latest(messages["a"], "LOG_HISTORY")["events"]
    _send(core, "a", "REQUEST_REPLAY_FRAME", {"matchId": "match-1", "revision": 0})
    assert _latest(messages["a"], "REPLAY_FRAME")["view"]["humanSide"] == "P1"
    messages["replacement"] = []
    core.connect("replacement", messages["replacement"].append)
    if leave_mode == "explicit":
        _send(core, "b", "LEAVE_ROOM")
    else:
        core.disconnect("b")
        timers.timers[-1].fire()
    assert core._finished_match_logs == {}
    assert core._finished_match_frames == {}
    _send(core, "replacement", "JOIN_ROOM", {"roomCode": "ABC123", "displayName": "New guest"})
    assert _latest(messages["replacement"], "ERROR")
    _send(core, "replacement", "REQUEST_LOG_HISTORY", {"matchId": "match-1", "beforeEventIndex": 1})
    assert _latest(messages["replacement"], "ERROR")["code"] == "PLAYER_NOT_IN_ROOM"
    assert not any(message["type"] == "LOG_HISTORY" for message in messages["replacement"])
    _send(core, "replacement", "REQUEST_REPLAY_FRAME", {"matchId": "match-1", "revision": 0})
    assert _latest(messages["replacement"], "ERROR")["code"] == "PLAYER_NOT_IN_ROOM"
    assert not any(message["type"] == "REPLAY_FRAME" for message in messages["replacement"])
    _send(core, "a", "REQUEST_LOG_HISTORY", {"matchId": "match-1", "beforeEventIndex": 1})
    assert _latest(messages["a"], "ERROR")["code"] == "PLAYER_NOT_IN_ROOM"
