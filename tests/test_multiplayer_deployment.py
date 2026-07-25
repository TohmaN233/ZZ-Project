from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request

import pytest
from websockets.exceptions import InvalidStatus
from websockets.sync.client import connect as websocket_connect

from zz.multiplayer.deployment import (
    DeploymentConfig,
    DeploymentConfigError,
    build_deployment_runtime,
    create_health_server,
)
from zz.multiplayer.deployment_server import main
from zz.multiplayer.protocol import (
    PROTOCOL_VERSION,
    parse_server_message,
    serialize_client_hello,
)
from zz.multiplayer.rooms import RoomError
from zz.multiplayer.service import MultiplayerServer
from zz.multiplayer.websocket_server import (
    WebSocketMultiplayerGateway,
    WebSocketServerConfig,
)


def _valid_env() -> dict[str, str]:
    return {
        "PORT": "32145",
        "PUBLIC_ORIGIN": "https://multiplayer.example.com",
        "PROTOCOL_VERSION": str(PROTOCOL_VERSION),
        "MAX_ROOMS": "256",
        "ROOM_IDLE_TIMEOUT_MS": "300000",
        "RECONNECT_GRACE_MS": "90000",
        "MAX_MESSAGE_BYTES": "65536",
        "HEARTBEAT_INTERVAL_MS": "20000",
        "HEARTBEAT_TIMEOUT_MS": "21000",
        "RATE_LIMIT_MESSAGES_PER_SECOND": "20",
        "RATE_LIMIT_BURST": "40",
        "LOG_LEVEL": "INFO",
    }


def _message(message_id: str, message_type: str, payload: dict | None = None) -> dict:
    return {
        "protocolVersion": PROTOCOL_VERSION,
        "messageId": message_id,
        "type": message_type,
        "payload": payload or {},
    }


def test_deployment_config_is_strict_and_has_explicit_bind_defaults() -> None:
    config = DeploymentConfig.from_environ(_valid_env())

    assert config.bind_host == "127.0.0.1"
    assert config.health_port == 32146
    assert config.summary() == {
        "BIND_HOST": "127.0.0.1",
        "PORT": 32145,
        "HEALTH_PORT": 32146,
        "PUBLIC_ORIGIN": "https://multiplayer.example.com",
        "PROTOCOL_VERSION": PROTOCOL_VERSION,
        "MAX_ROOMS": 256,
        "ROOM_IDLE_TIMEOUT_MS": 300000,
        "RECONNECT_GRACE_MS": 90000,
        "MAX_MESSAGE_BYTES": 65536,
        "HEARTBEAT_INTERVAL_MS": 20000,
        "HEARTBEAT_TIMEOUT_MS": 21000,
        "RATE_LIMIT_MESSAGES_PER_SECOND": 20,
        "RATE_LIMIT_BURST": 40,
        "LOG_LEVEL": "INFO",
    }


@pytest.mark.parametrize(
    ("name", "value", "message"),
    [
        ("PORT", "0", "PORT must be a positive integer"),
        ("BIND_HOST", "0.0.0.0", "must be 127.0.0.1"),
        ("PUBLIC_ORIGIN", "http://multiplayer.example.com", "HTTPS origin"),
        ("PUBLIC_ORIGIN", "https://multiplayer.example.com/path", "HTTPS origin"),
        ("PROTOCOL_VERSION", str(PROTOCOL_VERSION + 1), "compiled protocol version"),
        ("MAX_ROOMS", "3.5", "MAX_ROOMS must be a positive integer"),
        ("MAX_ROOMS", "10001", "MAX_ROOMS must be at most"),
        ("ROOM_IDLE_TIMEOUT_MS", "89999", "greater than or equal"),
        ("MAX_MESSAGE_BYTES", "1048577", "MAX_MESSAGE_BYTES must be at most"),
        ("RATE_LIMIT_MESSAGES_PER_SECOND", "1001", "must be at most"),
        ("RATE_LIMIT_BURST", "19", "greater than or equal"),
        ("LOG_LEVEL", "verbose", "LOG_LEVEL must be one of"),
    ],
)
def test_deployment_config_rejects_invalid_values(
    name: str,
    value: str,
    message: str,
) -> None:
    environ = _valid_env()
    environ[name] = value
    with pytest.raises(DeploymentConfigError, match=message):
        DeploymentConfig.from_environ(environ)


def test_deployment_config_reports_all_missing_required_values() -> None:
    with pytest.raises(DeploymentConfigError, match="PORT, PUBLIC_ORIGIN"):
        DeploymentConfig.from_environ({})


def test_check_config_prints_summary_without_building_or_binding(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fail_build(_config):
        raise AssertionError("--check-config must not build runtime servers")

    monkeypatch.setattr(
        "zz.multiplayer.deployment_server.build_deployment_runtime", fail_build
    )
    assert main(["--check-config"], environ=_valid_env()) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["PUBLIC_ORIGIN"] == "https://multiplayer.example.com"
    assert output["PROTOCOL_VERSION"] == PROTOCOL_VERSION


class _FakeTimer:
    def __init__(self, delay: float, callback) -> None:
        self.delay = delay
        self.callback = callback
        self.started = False
        self.cancelled = False

    def start(self) -> None:
        self.started = True

    def cancel(self) -> None:
        self.cancelled = True

    def fire(self) -> None:
        if not self.cancelled:
            self.callback()


class _TimerFactory:
    def __init__(self) -> None:
        self.timers: list[_FakeTimer] = []

    def __call__(self, delay: float, callback) -> _FakeTimer:
        timer = _FakeTimer(delay, callback)
        self.timers.append(timer)
        return timer


def test_server_enforces_room_capacity_and_reuses_closed_capacity() -> None:
    room_ids = iter(("room-1", "room-2"))
    room_codes = iter(("ROOM01", "ROOM02"))
    messages = {"a": [], "b": []}
    server = MultiplayerServer(
        max_rooms=1,
        room_id_factory=lambda: next(room_ids),
        room_code_factory=lambda: next(room_codes),
    )
    server.connect("a", messages["a"].append)
    server.connect("b", messages["b"].append)
    server.receive("a", _message("create-a", "CREATE_ROOM"))
    server.receive("b", _message("create-b-full", "CREATE_ROOM"))
    assert messages["b"][-1]["payload"]["code"] == "SERVER_CAPACITY"

    server.close_room("ROOM01")
    server.receive("b", _message("create-b", "CREATE_ROOM"))
    assert server.room_for_code("ROOM02").room_code == "ROOM02"


def test_waiting_room_uses_one_idle_timer_and_never_overlaps_reconnect() -> None:
    idle_timers = _TimerFactory()
    reconnect_timers = _TimerFactory()
    messages: dict[str, list[dict]] = {"a": [], "b": [], "new-a": []}
    server = MultiplayerServer(
        room_id_factory=lambda: "room-1",
        room_code_factory=lambda: "ROOM01",
        room_idle_timeout_seconds=30,
        room_idle_timer_factory=idle_timers,
        reconnect_grace_seconds=10,
        reconnect_timer_factory=reconnect_timers,
    )
    for connection_id in messages:
        server.connect(connection_id, messages[connection_id].append)

    server.receive("a", _message("create", "CREATE_ROOM"))
    token = messages["a"][-1]["payload"]["reconnectToken"]
    assert len(idle_timers.timers) == 1
    assert idle_timers.timers[0].started is True

    server.receive("a", _message("sync", "REQUEST_SYNC"))
    assert idle_timers.timers[0].cancelled is True
    assert len(idle_timers.timers) == 2

    server.disconnect("a")
    assert idle_timers.timers[1].cancelled is True
    assert len(reconnect_timers.timers) == 1
    assert not any(not timer.cancelled for timer in idle_timers.timers)

    server.receive("new-a", _message("reconnect", "RECONNECT", {
        "roomCode": "ROOM01",
        "playerId": "player_1",
        "reconnectToken": token,
    }))
    assert reconnect_timers.timers[0].cancelled is True
    assert len(idle_timers.timers) == 3
    assert idle_timers.timers[2].cancelled is False

    server.receive("b", _message("join", "JOIN_ROOM", {"roomCode": "ROOM01"}))
    assert idle_timers.timers[2].cancelled is True
    server.close_room("ROOM01")
    assert not any(not timer.cancelled for timer in idle_timers.timers)
    assert not any(not timer.cancelled for timer in reconnect_timers.timers)


def test_idle_timer_closes_waiting_room_while_default_server_starts_none() -> None:
    timers = _TimerFactory()
    messages: list[dict] = []
    server = MultiplayerServer(
        room_id_factory=lambda: "room-idle",
        room_code_factory=lambda: "IDLE01",
        room_idle_timeout_seconds=5,
        room_idle_timer_factory=timers,
    )
    server.connect("a", messages.append)
    server.receive("a", _message("create", "CREATE_ROOM"))
    timers.timers[0].fire()
    with pytest.raises(RoomError, match="room code does not exist"):
        server.room_for_code("IDLE01")
    assert messages[-1]["type"] == "ROOM_CLOSED"

    default_server = MultiplayerServer(
        room_id_factory=lambda: "room-default",
        room_code_factory=lambda: "DFLT01",
    )
    default_server.connect("default", lambda _message: None)
    default_server.receive("default", _message("create-default", "CREATE_ROOM"))
    assert default_server._room_idle_timers == {}


def test_healthz_returns_exact_privacy_safe_json() -> None:
    server = create_health_server("127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    port = server.server_address[1]
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz") as response:
            assert response.status == 200
            assert response.headers["Content-Type"] == "application/json"
            assert response.read() == (
                b'{"status":"ok","protocolVersion":'
                + str(PROTOCOL_VERSION).encode("ascii")
                + b"}"
            )
        with pytest.raises(urllib.error.HTTPError) as missing:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz?rooms=true")
        assert missing.value.code == 404
        assert missing.value.read() == b""
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
        assert not thread.is_alive()


def _hello(socket) -> dict:
    socket.send(serialize_client_hello(_message("hello", "HELLO")))
    return parse_server_message(socket.recv())


def test_websocket_origin_allows_public_origin_and_originless_desktop_only() -> None:
    gateway = WebSocketMultiplayerGateway(
        config=WebSocketServerConfig(
            host="127.0.0.1",
            port=0,
            allowed_origins=("https://multiplayer.example.com", None),
        )
    )
    with gateway.create_server() as server:
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        url = f"ws://127.0.0.1:{server.socket.getsockname()[1]}"
        try:
            with websocket_connect(
                url,
                origin="https://multiplayer.example.com",
                proxy=None,
            ) as allowed:
                assert _hello(allowed)["type"] == "WELCOME"

            with websocket_connect(url, proxy=None) as desktop:
                assert _hello(desktop)["type"] == "WELCOME"

            with pytest.raises(InvalidStatus):
                websocket_connect(
                    url,
                    origin="https://attacker.example.com",
                    proxy=None,
                )
        finally:
            server.shutdown()
            thread.join(timeout=3)
            assert not thread.is_alive()


def test_deployment_runtime_wires_every_config_value() -> None:
    config = DeploymentConfig.from_environ(_valid_env())
    runtime = build_deployment_runtime(config)

    assert runtime.core.max_rooms == 256
    assert runtime.core.room_idle_timeout_seconds == 300
    assert runtime.core.reconnect_grace_seconds == 90
    assert runtime.core.rate_limit_messages_per_second == 20
    assert runtime.core.rate_limit_burst == 40
    assert runtime.gateway.config.host == "127.0.0.1"
    assert runtime.gateway.config.port == 32145
    assert runtime.gateway.config.max_message_bytes == 65536
    assert runtime.gateway.config.heartbeat_interval_seconds == 20
    assert runtime.gateway.config.heartbeat_timeout_seconds == 21
    assert runtime.gateway.config.reconnect_grace_seconds == 90
    assert runtime.gateway.config.allowed_origins == (
        "https://multiplayer.example.com",
        None,
    )
