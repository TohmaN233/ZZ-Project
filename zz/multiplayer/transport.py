from __future__ import annotations

import base64
from copy import deepcopy
import json
from threading import Event, RLock, Thread, current_thread
from typing import Any, Callable, Mapping, Protocol
from uuid import uuid4

from zz.multiplayer.compatibility import hello_compatibility_payload
from zz.multiplayer.protocol import (
    MAX_LOGICAL_MESSAGE_BYTES,
    PROTOCOL_VERSION,
    serialize_client_hello,
    validate_server_envelope,
)

Message = Mapping[str, Any]
MessageListener = Callable[[dict[str, Any]], None]
Unsubscribe = Callable[[], None]


def websocket_connect(url: str, **kwargs: Any) -> Any:
    try:
        from websockets.sync.client import connect
    except ImportError as exc:  # pragma: no cover - depends on optional install
        raise RuntimeError(
            "WebSocketTransport requires the 'multiplayer' optional dependency"
        ) from exc
    return connect(url, **kwargs)


class MultiplayerTransport(Protocol):
    def connect(self) -> None: ...

    def send(self, message: Message) -> None: ...

    def close(self) -> None: ...

    def on_message(self, listener: MessageListener) -> Unsubscribe: ...


class InMemoryServerEndpoint(Protocol):
    def connect(self, connection_id: str, emit: MessageListener) -> None: ...

    def receive(self, connection_id: str, message: Message) -> None: ...

    def disconnect(self, connection_id: str) -> None: ...


class InMemoryTransport:
    def __init__(self, endpoint: InMemoryServerEndpoint, connection_id: str):
        if not connection_id:
            raise ValueError("connection_id must not be empty")
        self.endpoint = endpoint
        self.connection_id = connection_id
        self._connected = False
        self._listeners: dict[int, MessageListener] = {}
        self._next_listener_id = 1

    @property
    def connected(self) -> bool:
        return self._connected

    def connect(self) -> None:
        if self._connected:
            raise RuntimeError("transport is already connected")
        self._connected = True
        try:
            self.endpoint.connect(self.connection_id, self._emit)
        except Exception:
            self._connected = False
            raise

    def send(self, message: Message) -> None:
        if not self._connected:
            raise RuntimeError("transport is not connected")
        if not isinstance(message, Mapping):
            raise TypeError("message must be a mapping")
        self.endpoint.receive(self.connection_id, deepcopy(dict(message)))

    def close(self) -> None:
        if not self._connected:
            return
        self._connected = False
        self.endpoint.disconnect(self.connection_id)

    def on_message(self, listener: MessageListener) -> Unsubscribe:
        if not callable(listener):
            raise TypeError("listener must be callable")
        listener_id = self._next_listener_id
        self._next_listener_id += 1
        self._listeners[listener_id] = listener

        def unsubscribe() -> None:
            self._listeners.pop(listener_id, None)

        return unsubscribe

    def _emit(self, message: Message) -> None:
        if not self._connected:
            return
        if not isinstance(message, Mapping):
            raise TypeError("server message must be a mapping")
        for listener in tuple(self._listeners.values()):
            listener(deepcopy(dict(message)))


class WebSocketTransport:
    def __init__(
        self,
        url: str,
        *,
        hello_payload: Mapping[str, Any] | None = None,
        max_size: int | None = 1_048_576,
        open_timeout: float | None = 10,
        ping_interval: float | None = 20,
        ping_timeout: float | None = 20,
        close_timeout: float | None = 10,
    ) -> None:
        if not isinstance(url, str) or not url:
            raise ValueError("url must not be empty")
        if hello_payload is not None and not isinstance(hello_payload, Mapping):
            raise TypeError("hello_payload must be a mapping")
        self.url = url
        self.hello_payload = {
            **hello_compatibility_payload(),
            **deepcopy(dict(hello_payload or {})),
        }
        self.max_size = max_size
        self.open_timeout = open_timeout
        self.ping_interval = ping_interval
        self.ping_timeout = ping_timeout
        self.close_timeout = close_timeout
        self._socket: Any | None = None
        self._receiver_thread: Thread | None = None
        self._stop_receiver = Event()
        self._connected = False
        self._connecting = False
        self._listeners: dict[int, MessageListener] = {}
        self._next_listener_id = 1
        self._lock = RLock()
        self._last_error: BaseException | None = None

    @property
    def connected(self) -> bool:
        with self._lock:
            return self._connected

    @property
    def last_error(self) -> BaseException | None:
        with self._lock:
            return self._last_error

    def connect(self) -> None:
        with self._lock:
            if self._connected or self._connecting:
                raise RuntimeError("transport is already connected")
            if (
                self._receiver_thread is not None
                and self._receiver_thread.is_alive()
            ):
                raise RuntimeError("previous transport connection is still closing")
            self._connecting = True
            self._last_error = None
            self._stop_receiver.clear()

        socket: Any | None = None
        try:
            socket = websocket_connect(
                self.url,
                additional_headers={"X-ZZ-Client-Features": "replay-fragments-v1"},
                max_size=self.max_size,
                open_timeout=self.open_timeout,
                ping_interval=self.ping_interval,
                ping_timeout=self.ping_timeout,
                close_timeout=self.close_timeout,
            )
            hello = {
                "protocolVersion": PROTOCOL_VERSION,
                "messageId": str(uuid4()),
                "type": "HELLO",
                "payload": deepcopy(self.hello_payload),
            }
            socket.send(serialize_client_hello(hello))
            receiver = Thread(
                target=self._receive_messages,
                args=(socket,),
                name="zz-websocket-receiver",
                daemon=True,
            )
            with self._lock:
                self._socket = socket
                self._receiver_thread = receiver
                self._connected = True
                self._connecting = False
            receiver.start()
        except Exception as exc:
            if socket is not None:
                self._close_socket(socket)
            with self._lock:
                self._socket = None
                self._receiver_thread = None
                self._connected = False
                self._connecting = False
                self._last_error = exc
            raise

    def send(self, message: Message) -> None:
        if not isinstance(message, Mapping):
            raise TypeError("message must be a mapping")
        encoded = json.dumps(
            deepcopy(dict(message)),
            ensure_ascii=False,
            separators=(",", ":"),
        )
        with self._lock:
            if not self._connected or self._socket is None:
                raise RuntimeError("transport is not connected")
            socket = self._socket
        try:
            socket.send(encoded)
        except Exception as exc:
            self._disconnect_failed_socket(socket, exc)
            raise

    def close(self) -> None:
        with self._lock:
            socket = self._socket
            receiver = self._receiver_thread
            if (
                not self._connected
                and not self._connecting
                and socket is None
                and receiver is None
            ):
                return
            self._connected = False
            self._connecting = False
            self._socket = None
            self._stop_receiver.set()
        if socket is not None:
            self._close_socket(socket)
        if receiver is not None and receiver is not current_thread():
            receiver.join(timeout=self._receiver_join_timeout())
        with self._lock:
            if self._receiver_thread is receiver and (
                receiver is None or not receiver.is_alive()
            ):
                self._receiver_thread = None

    def on_message(self, listener: MessageListener) -> Unsubscribe:
        if not callable(listener):
            raise TypeError("listener must be callable")
        with self._lock:
            listener_id = self._next_listener_id
            self._next_listener_id += 1
            self._listeners[listener_id] = listener

        def unsubscribe() -> None:
            with self._lock:
                self._listeners.pop(listener_id, None)

        return unsubscribe

    def _receive_messages(self, socket: Any) -> None:
        fragments_enabled = False
        fragments: dict[str, Any] | None = None
        try:
            while not self._stop_receiver.is_set():
                raw_message = socket.recv()
                if isinstance(raw_message, bytes):
                    raw_message = raw_message.decode("utf-8")
                if not isinstance(raw_message, str):
                    raise TypeError("websocket message must be text or UTF-8 bytes")
                decoded = json.loads(raw_message)
                if not isinstance(decoded, Mapping):
                    raise ValueError("websocket message must contain a JSON object")
                if decoded.get("type") == "WELCOME" and decoded.get("payload", {}).get("messageFragments") is True:
                    self.send({"protocolVersion": PROTOCOL_VERSION, "messageId": str(uuid4()),
                               "type": "ENABLE_MESSAGE_FRAGMENTS", "payload": {}})
                    fragments_enabled = True
                elif decoded.get("type") == "MESSAGE_FRAGMENT":
                    if not fragments_enabled:
                        raise ValueError("unexpected message fragment")
                    part = validate_server_envelope(decoded)["payload"]
                    if fragments is None:
                        if part["index"] != 0:
                            raise ValueError("message fragments are out of order")
                        fragments = {"id": part["id"], "count": part["count"], "parts": [], "bytes": 0}
                    if (fragments["id"] != part["id"] or fragments["count"] != part["count"]
                            or len(fragments["parts"]) != part["index"]):
                        raise ValueError("message fragments are out of order")
                    raw_part = base64.b64decode(part["data"], validate=True)
                    if base64.b64encode(raw_part).decode("ascii") != part["data"]:
                        raise ValueError("invalid message fragment encoding")
                    fragments["bytes"] += len(raw_part)
                    if fragments["bytes"] > MAX_LOGICAL_MESSAGE_BYTES:
                        raise ValueError("fragmented message exceeds logical size limit")
                    fragments["parts"].append(raw_part)
                    if len(fragments["parts"]) < fragments["count"]:
                        continue
                    decoded = json.loads(b"".join(fragments["parts"]).decode("utf-8"))
                    if not isinstance(decoded, Mapping) or decoded.get("messageId") != fragments["id"] or decoded.get("type") == "MESSAGE_FRAGMENT":
                        raise ValueError("fragmented message identity does not match")
                    decoded = validate_server_envelope(decoded)
                    fragments = None
                elif fragments is not None:
                    raise ValueError("server interrupted a fragmented message")
                self._emit(decoded)
        except Exception as exc:
            if not self._stop_receiver.is_set():
                with self._lock:
                    self._last_error = exc
        finally:
            self._close_socket(socket)
            with self._lock:
                if self._socket is socket:
                    self._socket = None
                    self._connected = False
                if self._receiver_thread is current_thread():
                    self._receiver_thread = None

    def _emit(self, message: Message) -> None:
        with self._lock:
            if not self._connected:
                return
            listeners = tuple(self._listeners.values())
        for listener in listeners:
            listener(deepcopy(dict(message)))

    def _disconnect_failed_socket(
        self,
        socket: Any,
        error: BaseException,
    ) -> None:
        with self._lock:
            receiver = self._receiver_thread
            if self._socket is socket:
                self._socket = None
                self._connected = False
                self._last_error = error
                self._stop_receiver.set()
        self._close_socket(socket)

        if receiver is not None and receiver is not current_thread():
            receiver.join(timeout=self._receiver_join_timeout())
        with self._lock:
            if self._receiver_thread is receiver and (
                receiver is None or not receiver.is_alive()
            ):
                self._receiver_thread = None

    def _close_socket(self, socket: Any) -> None:
        try:
            socket.close()
        except Exception as exc:
            with self._lock:
                if self._last_error is None:
                    self._last_error = exc

    def _receiver_join_timeout(self) -> float:
        return (10 if self.close_timeout is None else self.close_timeout) + 1
