from __future__ import annotations

import argparse
import secrets
from collections.abc import Callable, Mapping
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
    PROTOCOL_VERSION,
    ProtocolError,
    parse_client_hello,
    parse_client_message,
    serialize_server_message,
)
from zz.multiplayer.service import MultiplayerServer


@dataclass(frozen=True)
class WebSocketServerConfig:
    host: str = "127.0.0.1"
    port: int = 32145
    max_message_bytes: int = MAX_MESSAGE_BYTES
    hello_timeout_seconds: float = 10.0
    heartbeat_interval_seconds: float = 20.0
    heartbeat_timeout_seconds: float = 20.0
    close_timeout_seconds: float = 10.0
    reconnect_grace_seconds: float = 90.0
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

        def emit(message: Mapping[str, Any]) -> None:
            outgoing = dict(message)
            if outgoing.get("type") == "WELCOME":
                payload = dict(outgoing.get("payload") or {})
                payload["compatibility"] = compatibility_payload()
                outgoing["payload"] = payload
            encoded = serialize_server_message(
                outgoing,
                max_bytes=self.config.max_message_bytes,
            )
            try:
                with send_lock:
                    socket.send(encoded)
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
    parser.add_argument("--reconnect-grace-seconds", type=float, default=90.0)
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
