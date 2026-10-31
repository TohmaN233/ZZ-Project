from __future__ import annotations

import argparse
import base64
import json
import secrets
from collections.abc import Callable, Mapping
from copy import deepcopy
from dataclasses import dataclass
from threading import Lock
from typing import Any

from websockets.exceptions import ConnectionClosed
from websockets.sync.server import Server, ServerConnection, serve

from zz.multiplayer.compatibility import (
    compatibility_payload,
    is_compatible_hello,
)
from zz.multiplayer.protocol import (
    MAX_MESSAGE_BYTES,
    MAX_LOGICAL_MESSAGE_BYTES,
    MAX_MESSAGE_FRAGMENTS,
    PROTOCOL_VERSION,
    ProtocolError,
    parse_client_hello,
    parse_client_message,
    serialize_server_message,
)
from zz.multiplayer.service import MultiplayerServer
from zz.multiplayer.views import fit_player_log_page, fit_player_view_log_history


@dataclass(frozen=True)
class WebSocketServerConfig:
    host: str = "127.0.0.1"
    port: int = 32145
    max_message_bytes: int = MAX_MESSAGE_BYTES
    hello_timeout_seconds: float = 10.0
    heartbeat_interval_seconds: float = 20.0
    heartbeat_timeout_seconds: float = 20.0
    close_timeout_seconds: float = 10.0
    reconnect_grace_seconds: float = 600.0
    allowed_origins: tuple[str | None, ...] | None = None

    def __post_init__(self) -> None:
        if not self.host:
            raise ValueError("host must not be empty")
        if isinstance(self.port, bool) or not isinstance(self.port, int) or not 0 <= self.port <= 65535:
            raise ValueError("port must be an integer from 0 to 65535")
        if self.max_message_bytes <= 0:
            raise ValueError("max_message_bytes must be positive")
        for field_name in (
            "hello_timeout_seconds",
            "heartbeat_interval_seconds",
            "heartbeat_timeout_seconds",
            "close_timeout_seconds",
            "reconnect_grace_seconds",
        ):
            if float(getattr(self, field_name)) <= 0:
                raise ValueError(f"{field_name} must be positive")
        if self.allowed_origins is not None:
            if not self.allowed_origins:
                raise ValueError("allowed_origins must not be empty")
            if any(origin is not None and not origin for origin in self.allowed_origins):
                raise ValueError("allowed_origins entries must be non-empty strings or None")


class WebSocketMultiplayerGateway:
    """WebSocket handshake and framing adapter for ``MultiplayerServer``."""

    def __init__(
        self,
        core: MultiplayerServer | None = None,
        *,
        config: WebSocketServerConfig | None = None,
        connection_id_factory: Callable[[], str] | None = None,
    ) -> None:
        self.config = config or WebSocketServerConfig()
        self.core = core or MultiplayerServer(
            reconnect_grace_seconds=self.config.reconnect_grace_seconds,
        )
        self._connection_id_factory = connection_id_factory or (
            lambda: f"connection-{secrets.token_hex(12)}"
        )
        self._message_lock = Lock()
        self._next_message_id = 1

    def create_server(self) -> Server:
        return serve(
            self.handle_connection,
            self.config.host,
            self.config.port,
            origins=self.config.allowed_origins,
            ping_interval=self.config.heartbeat_interval_seconds,
            ping_timeout=self.config.heartbeat_timeout_seconds,
            close_timeout=self.config.close_timeout_seconds,
            max_size=self.config.max_message_bytes,
            compression=None,
        )

    def serve_forever(self) -> None:
        with self.create_server() as server:
            bound_host, bound_port = server.socket.getsockname()[:2]
            print(
                f"Serving ZZ multiplayer WebSocket at ws://{bound_host}:{bound_port}/",
                flush=True,
            )
            server.serve_forever()

    def handle_connection(self, socket: ServerConnection) -> None:
        connection_id = self._connection_id_factory()
        send_lock = Lock()
        registered = False
        fragments_enabled = False
        headers = getattr(getattr(socket, "request", None), "headers", {})
        supports_extensions = headers.get("X-ZZ-Client-Features") == "replay-fragments-v1"

        def emit(message: Mapping[str, Any]) -> None:
            outgoing = deepcopy(dict(message))
            def wire_bytes(value: Any) -> int:
                return len(json.dumps(value, ensure_ascii=False, separators=(",", ":"),
                                      allow_nan=False).encode("utf-8"))

            if outgoing.get("type") == "WELCOME":
                payload = dict(outgoing.get("payload") or {})
                payload["compatibility"] = compatibility_payload()
                if supports_extensions:
                    payload["messageFragments"] = True
                    payload["replayFrames"] = True
                outgoing["payload"] = payload
            payload = outgoing.get("payload")
            view = payload.get("view") if isinstance(payload, dict) else None
            if (isinstance(view, dict) and "logEvents" in view) or outgoing.get("type") == "LOG_HISTORY":
                if outgoing.get("type") == "LOG_HISTORY":
                    fit_player_log_page(payload, max_message_bytes=self.config.max_message_bytes,
                                        envelope_bytes=wire_bytes(outgoing) - wire_bytes(payload))
                else:
                    fit_player_view_log_history(
                        view, max_message_bytes=self.config.max_message_bytes,
                        envelope_bytes=wire_bytes(outgoing) - wire_bytes(view),
                    )
            encoded = serialize_server_message(
                outgoing,
                max_bytes=MAX_LOGICAL_MESSAGE_BYTES,
            )
            encoded_bytes = encoded.encode("utf-8")
            size = len(encoded_bytes)
            limit = self.config.max_message_bytes
            frames = [encoded]
            if size > limit:
                sizes = ({
                    "viewBytes": wire_bytes(view),
                    "logBytes": wire_bytes(view.get("logEvents")),
                    "animationBytes": wire_bytes(view.get("animationEvents")),
                    "boardBytes": wire_bytes(view.get("players")),
                    "promptBytes": wire_bytes(view.get("prompt")),
                } if isinstance(view, dict) else {})
                if not fragments_enabled:
                    self.core._observe("outbound_message_too_large", level="WARNING",
                                       connectionId=connection_id, messageType=outgoing["type"],
                                       messageBytes=size, messageLimit=limit, **sizes)
                    raise ProtocolError("MESSAGE_TOO_LARGE", f"message size {size} exceeds {limit} bytes", fatal=True)
                # Keep the fragment and its envelope below the configured wire limit.
                raw_part_size = min(32_768, max(0, (limit - 512) * 3 // 4))
                if raw_part_size == 0:
                    raise ProtocolError("MESSAGE_TOO_LARGE", "message limit is too small for fragmentation", fatal=True)
                count = (size + raw_part_size - 1) // raw_part_size
                if count > MAX_MESSAGE_FRAGMENTS:
                    raise ProtocolError("MESSAGE_TOO_LARGE", "message requires too many fragments", fatal=True)
                frames = []
                for index in range(count):
                    fragment = {
                        "protocolVersion": PROTOCOL_VERSION,
                        "messageId": self._new_message_id(),
                        "type": "MESSAGE_FRAGMENT",
                        "payload": {
                            "id": outgoing["messageId"], "index": index, "count": count,
                            "data": base64.b64encode(encoded_bytes[index * raw_part_size:(index + 1) * raw_part_size]).decode("ascii"),
                        },
                    }
                    frames.append(serialize_server_message(fragment, max_bytes=limit))
                self.core._observe("outbound_message_fragmented", connectionId=connection_id,
                                   messageType=outgoing["type"], messageBytes=size,
                                   messageLimit=limit, fragmentCount=count, **sizes)
            try:
                with send_lock:
                    for frame in frames:
                        socket.send(frame)
            except ConnectionClosed:
                return

        try:
            try:
                raw_hello = socket.recv(timeout=self.config.hello_timeout_seconds)
                hello = parse_client_hello(
                    raw_hello,
                    max_bytes=self.config.max_message_bytes,
                )
                if not is_compatible_hello(hello["payload"]):
                    raise ProtocolError(
                        "INCOMPATIBLE_GAME_VERSION",
                        "Client game version is incompatible with this server.",
                        fatal=True,
                    )
            except ProtocolError as exc:
                self._send_protocol_error(socket, send_lock, exc)
                socket.close(code=1002, reason=exc.code)
                return
            except TimeoutError:
                error = ProtocolError(
                    "HELLO_TIMEOUT",
                    "HELLO was not received before the handshake timeout",
                    fatal=True,
                )
                self._send_protocol_error(socket, send_lock, error)
                socket.close(code=1002, reason=error.code)
                return

            self.core.connect(connection_id, emit)
            registered = True
            for raw_message in socket:
                try:
                    message = parse_client_message(
                        raw_message,
                        max_bytes=self.config.max_message_bytes,
                    )
                except ProtocolError as exc:
                    self._send_protocol_error(socket, send_lock, exc)
                    if exc.fatal:
                        socket.close(code=1002, reason=exc.code)
                        break
                    continue
                if message["type"] == "ENABLE_MESSAGE_FRAGMENTS":
                    if fragments_enabled:
                        error = ProtocolError("INVALID_MESSAGE", "message fragmentation was already enabled", fatal=True)
                        self._send_protocol_error(socket, send_lock, error)
                        socket.close(code=1002, reason=error.code)
                        break
                    fragments_enabled = True
                    continue
                self.core.receive(connection_id, message)
        except ConnectionClosed:
            return
        finally:
            if registered:
                self.core.disconnect(connection_id)

    def _send_protocol_error(
        self,
        socket: ServerConnection,
        send_lock: Lock,
        error: ProtocolError,
    ) -> None:
        message = {
            "protocolVersion": PROTOCOL_VERSION,
            "messageId": self._new_message_id(),
            "type": "ERROR",
            "payload": error.to_dict(),
        }
        try:
            encoded = serialize_server_message(
                message,
                max_bytes=self.config.max_message_bytes,
            )
            with send_lock:
                socket.send(encoded)
        except ConnectionClosed:
            return

    def _new_message_id(self) -> str:
        with self._message_lock:
            value = self._next_message_id
            self._next_message_id += 1
        return f"gateway-{value}"


def main() -> None:
    parser = argparse.ArgumentParser(description="ZZ authoritative multiplayer WebSocket server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=32145)
    parser.add_argument("--max-message-bytes", type=int, default=MAX_MESSAGE_BYTES)
    parser.add_argument("--reconnect-grace-seconds", type=float, default=600.0)
    args = parser.parse_args()
    gateway = WebSocketMultiplayerGateway(config=WebSocketServerConfig(
        host=args.host,
        port=args.port,
        max_message_bytes=args.max_message_bytes,
        reconnect_grace_seconds=args.reconnect_grace_seconds,
    ))
    gateway.serve_forever()


if __name__ == "__main__":
    main()
