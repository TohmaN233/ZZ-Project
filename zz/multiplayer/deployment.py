from __future__ import annotations

import json
import logging
import re
from collections.abc import Mapping
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from urllib.parse import urlsplit

from zz.multiplayer.protocol import PROTOCOL_VERSION as COMPILED_PROTOCOL_VERSION
from zz.multiplayer.observability import StructuredEventSink
from zz.multiplayer.service import MultiplayerServer
from zz.multiplayer.websocket_server import (
    WebSocketMultiplayerGateway,
    WebSocketServerConfig,
)


_REQUIRED_ENV = (
    "PORT",
    "PUBLIC_ORIGIN",
    "PROTOCOL_VERSION",
    "MAX_ROOMS",
    "ROOM_IDLE_TIMEOUT_MS",
    "RECONNECT_GRACE_MS",
    "MAX_MESSAGE_BYTES",
    "HEARTBEAT_INTERVAL_MS",
    "HEARTBEAT_TIMEOUT_MS",
    "RATE_LIMIT_MESSAGES_PER_SECOND",
    "RATE_LIMIT_BURST",
    "LOG_LEVEL",
)
_LOG_LEVELS = frozenset({"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"})
_HEALTH_BODY = json.dumps(
    {"status": "ok", "protocolVersion": COMPILED_PROTOCOL_VERSION},
    separators=(",", ":"),
).encode("ascii")


class DeploymentConfigError(ValueError):
    pass


@dataclass(frozen=True)
class DeploymentConfig:
    bind_host: str
    port: int
    health_port: int
    public_origin: str
    protocol_version: int
    max_rooms: int
    room_idle_timeout_ms: int
    reconnect_grace_ms: int
    max_message_bytes: int
    heartbeat_interval_ms: int
    heartbeat_timeout_ms: int
    rate_limit_messages_per_second: int
    rate_limit_burst: int
    log_level: str

    @classmethod
    def from_environ(cls, environ: Mapping[str, str]) -> DeploymentConfig:
        missing = [name for name in _REQUIRED_ENV if not environ.get(name)]
        if missing:
            raise DeploymentConfigError(
                f"missing required environment variables: {', '.join(missing)}"
            )

        bind_host = environ.get("BIND_HOST", "127.0.0.1")
        if bind_host != "127.0.0.1":
            raise DeploymentConfigError(
                "BIND_HOST must be 127.0.0.1 behind the production reverse proxy"
            )

        port = _parse_port(environ["PORT"], "PORT")
        health_port = _parse_port(environ.get("HEALTH_PORT", "32146"), "HEALTH_PORT")
        if port == health_port:
            raise DeploymentConfigError("PORT and HEALTH_PORT must be different")

        public_origin = environ["PUBLIC_ORIGIN"]
        _validate_public_origin(public_origin)

        protocol_version = _parse_positive_int(
            environ["PROTOCOL_VERSION"], "PROTOCOL_VERSION"
        )
        if protocol_version != COMPILED_PROTOCOL_VERSION:
            raise DeploymentConfigError(
                "PROTOCOL_VERSION must equal the compiled protocol version "
                f"{COMPILED_PROTOCOL_VERSION}"
            )

        max_rooms = _parse_positive_int(environ["MAX_ROOMS"], "MAX_ROOMS")
        _require_at_most(max_rooms, "MAX_ROOMS", 10_000)
        room_idle_timeout_ms = _parse_positive_int(
            environ["ROOM_IDLE_TIMEOUT_MS"], "ROOM_IDLE_TIMEOUT_MS"
        )
        reconnect_grace_ms = _parse_positive_int(
            environ["RECONNECT_GRACE_MS"], "RECONNECT_GRACE_MS"
        )
        if room_idle_timeout_ms < reconnect_grace_ms:
            raise DeploymentConfigError(
                "ROOM_IDLE_TIMEOUT_MS must be greater than or equal to RECONNECT_GRACE_MS"
            )

        max_message_bytes = _parse_positive_int(
            environ["MAX_MESSAGE_BYTES"], "MAX_MESSAGE_BYTES"
        )
        _require_at_most(max_message_bytes, "MAX_MESSAGE_BYTES", 1_048_576)
        heartbeat_interval_ms = _parse_positive_int(
            environ["HEARTBEAT_INTERVAL_MS"], "HEARTBEAT_INTERVAL_MS"
        )
        heartbeat_timeout_ms = _parse_positive_int(
            environ["HEARTBEAT_TIMEOUT_MS"], "HEARTBEAT_TIMEOUT_MS"
        )
        rate_limit_messages_per_second = _parse_positive_int(
            environ["RATE_LIMIT_MESSAGES_PER_SECOND"],
            "RATE_LIMIT_MESSAGES_PER_SECOND",
        )
        _require_at_most(
            rate_limit_messages_per_second,
            "RATE_LIMIT_MESSAGES_PER_SECOND",
            1_000,
        )
        rate_limit_burst = _parse_positive_int(
            environ["RATE_LIMIT_BURST"], "RATE_LIMIT_BURST"
        )
        _require_at_most(rate_limit_burst, "RATE_LIMIT_BURST", 5_000)
        if rate_limit_burst < rate_limit_messages_per_second:
            raise DeploymentConfigError(
                "RATE_LIMIT_BURST must be greater than or equal to RATE_LIMIT_MESSAGES_PER_SECOND"
            )
        log_level = environ["LOG_LEVEL"]
        if log_level not in _LOG_LEVELS:
            raise DeploymentConfigError(
                "LOG_LEVEL must be one of DEBUG, INFO, WARNING, ERROR, CRITICAL"
            )

        return cls(
            bind_host=bind_host,
            port=port,
            health_port=health_port,
            public_origin=public_origin,
            protocol_version=protocol_version,
            max_rooms=max_rooms,
            room_idle_timeout_ms=room_idle_timeout_ms,
            reconnect_grace_ms=reconnect_grace_ms,
            max_message_bytes=max_message_bytes,
            heartbeat_interval_ms=heartbeat_interval_ms,
            heartbeat_timeout_ms=heartbeat_timeout_ms,
            rate_limit_messages_per_second=rate_limit_messages_per_second,
            rate_limit_burst=rate_limit_burst,
            log_level=log_level,
        )

    def summary(self) -> dict[str, str | int]:
        return {
            "BIND_HOST": self.bind_host,
            "PORT": self.port,
            "HEALTH_PORT": self.health_port,
            "PUBLIC_ORIGIN": self.public_origin,
            "PROTOCOL_VERSION": self.protocol_version,
            "MAX_ROOMS": self.max_rooms,
            "ROOM_IDLE_TIMEOUT_MS": self.room_idle_timeout_ms,
            "RECONNECT_GRACE_MS": self.reconnect_grace_ms,
            "MAX_MESSAGE_BYTES": self.max_message_bytes,
            "HEARTBEAT_INTERVAL_MS": self.heartbeat_interval_ms,
            "HEARTBEAT_TIMEOUT_MS": self.heartbeat_timeout_ms,
            "RATE_LIMIT_MESSAGES_PER_SECOND": self.rate_limit_messages_per_second,
            "RATE_LIMIT_BURST": self.rate_limit_burst,
            "LOG_LEVEL": self.log_level,
        }


def _parse_positive_int(value: str, name: str) -> int:
    if not re.fullmatch(r"[0-9]+", value):
        raise DeploymentConfigError(f"{name} must be a positive integer")
    parsed = int(value)
    if parsed <= 0:
        raise DeploymentConfigError(f"{name} must be a positive integer")
    return parsed


def _parse_port(value: str, name: str) -> int:
    port = _parse_positive_int(value, name)
    if port > 65535:
        raise DeploymentConfigError(f"{name} must be between 1 and 65535")
    return port


def _require_at_most(value: int, name: str, maximum: int) -> None:
    if value > maximum:
        raise DeploymentConfigError(f"{name} must be at most {maximum}")


def _validate_public_origin(value: str) -> None:
    try:
        parsed = urlsplit(value)
        parsed_port = parsed.port
    except ValueError as exc:
        raise DeploymentConfigError("PUBLIC_ORIGIN must be a valid HTTPS origin") from exc
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path
        or parsed.query
        or parsed.fragment
        or value != f"https://{parsed.netloc}"
        or parsed_port == 0
    ):
        raise DeploymentConfigError(
            "PUBLIC_ORIGIN must be an exact production HTTPS origin without a path"
        )


class _HealthRequestHandler(BaseHTTPRequestHandler):
    server_version = "ZZHealth"
    sys_version = ""

    def do_GET(self) -> None:
        if self.path != "/healthz":
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(_HEALTH_BODY)))
        self.end_headers()
        self.wfile.write(_HEALTH_BODY)

    def log_message(self, _format: str, *_args: object) -> None:
        return


def create_health_server(host: str, port: int) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, port), _HealthRequestHandler)


@dataclass
class DeploymentRuntime:
    config: DeploymentConfig
    core: MultiplayerServer
    gateway: WebSocketMultiplayerGateway
    event_sink: StructuredEventSink

    def serve_forever(self) -> None:
        with self.gateway.create_server() as websocket_server:
            with create_health_server(
                self.config.bind_host, self.config.health_port
            ) as health_server:
                health_thread = Thread(
                    target=health_server.serve_forever,
                    name="zz-multiplayer-health",
                    daemon=True,
                )
                health_thread.start()
                self.event_sink("deployment_started")
                try:
                    websocket_server.serve_forever()
                finally:
                    health_server.shutdown()
                    health_thread.join(timeout=5)
                    if health_thread.is_alive():
                        raise RuntimeError("health server did not stop")


def build_deployment_runtime(config: DeploymentConfig) -> DeploymentRuntime:
    event_sink = StructuredEventSink(logging.getLogger("zz.multiplayer"))
    core = MultiplayerServer(
        reconnect_grace_seconds=config.reconnect_grace_ms / 1000,
        max_rooms=config.max_rooms,
        room_idle_timeout_seconds=config.room_idle_timeout_ms / 1000,
        rate_limit_messages_per_second=config.rate_limit_messages_per_second,
        rate_limit_burst=config.rate_limit_burst,
        event_sink=event_sink,
    )
    gateway = WebSocketMultiplayerGateway(
        core,
        config=WebSocketServerConfig(
            host=config.bind_host,
            port=config.port,
            max_message_bytes=config.max_message_bytes,
            heartbeat_interval_seconds=config.heartbeat_interval_ms / 1000,
            heartbeat_timeout_seconds=config.heartbeat_timeout_ms / 1000,
            reconnect_grace_seconds=config.reconnect_grace_ms / 1000,
            allowed_origins=(config.public_origin, None),
        ),
    )
    return DeploymentRuntime(
        config=config,
        core=core,
        gateway=gateway,
        event_sink=event_sink,
    )
