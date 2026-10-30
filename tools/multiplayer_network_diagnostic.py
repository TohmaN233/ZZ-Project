from __future__ import annotations

import argparse
import http.client
import json
import math
import queue
import re
import socket
import ssl
import statistics
import sys
import threading
import time
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from websockets.exceptions import ConnectionClosed, InvalidHandshake
from websockets.sync.client import connect as websocket_connect


DEFAULT_URL = "wss://zz.tgy233.top/multiplayer"
DEFAULT_HEALTH_URL = "https://zz-health.tgy233.top/healthz"
MANIFEST_FIELDS = frozenset({
    "applicationVersion",
    "protocolVersion",
    "rulesVersion",
    "cardDatabaseChecksum",
})
HELLO_FIELDS = (
    "applicationVersion",
    "rulesVersion",
    "cardDatabaseChecksum",
)
GAME_STAGES = (
    "dns",
    "tcp",
    "tls",
    "websocket_upgrade",
    "game_hello",
    "heartbeat",
)
MAX_HEALTH_BODY_BYTES = 4096
_SAFE_SERVER_CODE = re.compile(r"[A-Z][A-Z0-9_]{0,63}\Z")


@dataclass(frozen=True)
class Endpoint:
    url: str
    scheme: str
    hostname: str
    port: int
    path: str

    @property
    def display(self) -> str:
        host = f"[{self.hostname}]" if ":" in self.hostname else self.hostname
        return f"{self.scheme}://{host}:{self.port}{self.path}"


class NetworkFailure(Exception):
    def __init__(
        self,
        kind: str,
        code: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(code)
        self.kind = kind
        self.code = code
        self.details = details or {}


class ProbeFailure(Exception):
    def __init__(
        self,
        stage: str,
        kind: str,
        code: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(code)
        self.stage = stage
        self.kind = kind
        self.code = code
        self.details = details or {}


@dataclass
class ConnectedSocket:
    sock: socket.socket
    selected_address: dict[str, str]
    tcp_attempts: list[dict[str, Any]]
    tls_attempts: list[dict[str, Any]]
    tcp_elapsed_ms: int
    tls_elapsed_ms: int


def _parse_endpoint(value: str, schemes: set[str]) -> Endpoint:
    if not isinstance(value, str) or not value or any(
        char.isspace() or ord(char) < 32 or ord(char) == 127 for char in value
    ):
        raise ValueError("invalid URL")
    try:
        parsed = urllib.parse.urlsplit(value)
        port = parsed.port
        hostname = parsed.hostname
    except ValueError as exc:
        raise ValueError("invalid URL") from exc
    if (
        parsed.scheme.lower() not in schemes
        or not parsed.netloc
        or hostname is None
        or "@" in parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or "?" in value
        or "#" in value
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("invalid URL")
    scheme = parsed.scheme.lower()
    if port is None:
        port = 443 if scheme in {"wss", "https"} else 80
    if not 1 <= port <= 65535:
        raise ValueError("invalid port")
    return Endpoint(
        url=value,
        scheme=scheme,
        hostname=hostname,
        port=port,
        path=parsed.path or "/",
    )


def _default_manifest_path() -> Path:
    if getattr(sys, "frozen", False):
        bundle_dir = Path(getattr(sys, "_MEIPASS"))
        return bundle_dir / "compatibility.json"
    sibling = Path(__file__).resolve().with_name("compatibility.json")
    if sibling.exists():
        return sibling
    return Path(__file__).resolve().parents[1] / "zz" / "multiplayer" / "compatibility.json"


def _reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate JSON key")
        value[key] = item
    return value


def _reject_json_constant(_value: str) -> None:
    raise ValueError("invalid JSON constant")


def _load_manifest(path: Path) -> dict[str, Any]:
    try:
        manifest = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_pairs,
            parse_constant=_reject_json_constant,
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError("invalid compatibility manifest") from exc
    if not isinstance(manifest, dict) or set(manifest) != MANIFEST_FIELDS:
        raise ValueError("invalid compatibility manifest")
    if (
        not isinstance(manifest["applicationVersion"], str)
        or re.fullmatch(r"\d+\.\d+\.\d+", manifest["applicationVersion"]) is None
        or isinstance(manifest["protocolVersion"], bool)
        or not isinstance(manifest["protocolVersion"], int)
        or manifest["protocolVersion"] <= 0
        or not isinstance(manifest["rulesVersion"], str)
        or not manifest["rulesVersion"]
        or not isinstance(manifest["cardDatabaseChecksum"], str)
        or re.fullmatch(r"sha256:[0-9a-f]{64}", manifest["cardDatabaseChecksum"]) is None
    ):
        raise ValueError("invalid compatibility manifest")
    return manifest


def _proxy_present() -> bool:
    proxies = urllib.request.getproxies()
    return any(
        key.lower() not in {"no", "no_proxy"} and bool(value)
        for key, value in proxies.items()
    )


def _family_name(family: int) -> str:
    if family == socket.AF_INET:
        return "IPv4"
    if family == socket.AF_INET6:
        return "IPv6"
    return "Other"


def _network_error(exc: BaseException) -> tuple[str, str]:
    if isinstance(exc, ssl.SSLCertVerificationError):
        return "tls", "CERTIFICATE_VERIFY_FAILED"
    if isinstance(exc, ssl.SSLError):
        return "tls", "TLS_ERROR"
    if isinstance(exc, socket.gaierror):
        code = exc.errno
        if code == getattr(socket, "EAI_AGAIN", object()) or code == 11002:
            return "dns", "EAI_AGAIN"
        if code == getattr(socket, "EAI_NONAME", object()) or code == 11001:
            return "dns", "EAI_NONAME"
        return "dns", "EAI_ERROR"
    if isinstance(exc, (TimeoutError, socket.timeout)):
        return "timeout", "ETIMEDOUT"
    if isinstance(exc, OSError):
        winerror_codes = {
            10051: "ENETUNREACH",
            10060: "ETIMEDOUT",
            10061: "ECONNREFUSED",
            10065: "EHOSTUNREACH",
        }
        code = winerror_codes.get(getattr(exc, "winerror", None))
        if code is None:
            error_number = getattr(exc, "errno", None)
            code = winerror_codes.get(error_number)
        if code is None:
            error_number = getattr(exc, "errno", None)
            code = {
                13: "EACCES",
                32: "EPIPE",
                54: "ECONNRESET",
                57: "ENETUNREACH",
                60: "ETIMEDOUT",
                61: "ECONNREFUSED",
                64: "EHOSTUNREACH",
                101: "ENETUNREACH",
                103: "ECONNABORTED",
                104: "ECONNRESET",
                110: "ETIMEDOUT",
                111: "ECONNREFUSED",
                113: "EHOSTUNREACH",
            }.get(error_number)
        if code is None:
            code = "NETWORK_ERROR"
        return "network", code
    return "network", "NETWORK_ERROR"


def _resolve_addresses(
    hostname: str,
    port: int,
    timeout: float,
) -> tuple[list[tuple[Any, ...]], list[dict[str, str]]]:
    result_queue: queue.Queue[tuple[bool, Any]] = queue.Queue(maxsize=1)

    def lookup() -> None:
        try:
            result_queue.put((True, socket.getaddrinfo(
                hostname,
                port,
                type=socket.SOCK_STREAM,
            )))
        except Exception as exc:
            result_queue.put((False, exc))

    threading.Thread(target=lookup, name="zz-dns-lookup", daemon=True).start()
    try:
        ok, result = result_queue.get(timeout=timeout)
    except queue.Empty as exc:
        raise NetworkFailure("timeout", "EAI_TIMEOUT") from exc
    if not ok:
        kind, code = _network_error(result)
        raise NetworkFailure(kind, code)
    infos = list(result)
    answers = [
        {
            "family": _family_name(info[0]),
            "address": str(info[4][0]),
            "outcome": "resolved",
        }
        for info in infos
    ]
    if not infos:
        raise NetworkFailure("dns", "EAI_NONAME", {"addresses": answers})
    return infos, answers


def _wrap_tls(
    raw_socket: socket.socket,
    hostname: str,
    timeout: float,
    context: ssl.SSLContext,
) -> socket.socket:
    raw_socket.settimeout(timeout)
    wrapped = context.wrap_socket(raw_socket, server_hostname=hostname)
    wrapped.settimeout(timeout)
    return wrapped


def _connect_direct(
    infos: list[tuple[Any, ...]],
    hostname: str,
    timeout: float,
    *,
    use_tls: bool,
) -> ConnectedSocket:
    tcp_attempts: list[dict[str, Any]] = []
    tls_attempts: list[dict[str, Any]] = []
    tcp_connected = False
    last_tcp_error: tuple[str, str] = ("network", "NETWORK_ERROR")
    last_tls_error: tuple[str, str] = ("tls", "TLS_ERROR")
    context = ssl.create_default_context() if use_tls else None
    tcp_elapsed_ms = 0
    tls_elapsed_ms = 0

    for family, socktype, proto, _canonname, sockaddr in infos:
        family_label = _family_name(family)
        address = str(sockaddr[0])
        attempt = {"family": family_label, "address": address}
        raw_socket = socket.socket(family, socktype, proto)
        raw_socket.settimeout(timeout)
        tcp_started = time.perf_counter()
        try:
            raw_socket.connect(sockaddr)
        except OSError as exc:
            tcp_elapsed_ms += _elapsed_ms(tcp_started)
            kind, code = _network_error(exc)
            last_tcp_error = (kind, code)
            tcp_attempts.append({**attempt, "outcome": "failed", "errorKind": kind, "errorCode": code})
            raw_socket.close()
            continue
        tcp_elapsed_ms += _elapsed_ms(tcp_started)

        tcp_connected = True
        tcp_attempts.append({**attempt, "outcome": "connected"})
        if not use_tls:
            return ConnectedSocket(
                raw_socket,
                {"family": family_label, "address": address},
                tcp_attempts,
                tls_attempts,
                tcp_elapsed_ms,
                tls_elapsed_ms,
            )

        tls_started = time.perf_counter()
        try:
            assert context is not None
            tls_socket = _wrap_tls(raw_socket, hostname, timeout, context)
        except (OSError, ssl.SSLError, TimeoutError) as exc:
            tls_elapsed_ms += _elapsed_ms(tls_started)
            kind, code = _network_error(exc)
            last_tls_error = (kind, code)
            tls_attempts.append({**attempt, "outcome": "failed", "errorKind": kind, "errorCode": code})
            raw_socket.close()
            continue
        tls_elapsed_ms += _elapsed_ms(tls_started)
        tls_attempts.append({**attempt, "outcome": "passed"})
        return ConnectedSocket(
            tls_socket,
            {"family": family_label, "address": address},
            tcp_attempts,
            tls_attempts,
            tcp_elapsed_ms,
            tls_elapsed_ms,
        )

    if use_tls and tcp_connected:
        kind, code = last_tls_error
        raise NetworkFailure(kind, code, {
            "tcpAttempts": tcp_attempts,
            "tlsAttempts": tls_attempts,
            "tcpConnected": True,
            "tcpElapsedMs": tcp_elapsed_ms,
            "tlsElapsedMs": tls_elapsed_ms,
        })
    kind, code = last_tcp_error
    raise NetworkFailure(kind, code, {
        "tcpAttempts": tcp_attempts,
        "tlsAttempts": tls_attempts,
        "tcpConnected": False,
        "tcpElapsedMs": tcp_elapsed_ms,
        "tlsElapsedMs": tls_elapsed_ms,
    })


def _elapsed_ms(started: float) -> int:
    return max(0, round((time.perf_counter() - started) * 1000))


def _append_check(
    report: dict[str, Any],
    stage: str,
    status: str,
    started: float,
    details: dict[str, Any] | None = None,
    *,
    progress: Callable[[str, str], None] | None = None,
    elapsed_ms: int | None = None,
) -> dict[str, Any]:
    check: dict[str, Any] = {
        "stage": stage,
        "status": status,
        "elapsedMs": _elapsed_ms(started) if elapsed_ms is None else max(0, elapsed_ms),
    }
    if details:
        check["details"] = details
    report["checks"].append(check)
    if progress is not None:
        progress(stage, status)
    return check


def _begin_stage(
    stage: str,
    progress: Callable[[str, str], None] | None,
) -> float:
    if progress is not None:
        progress(stage, "running")
    return time.perf_counter()


def _authority(endpoint: Endpoint, default_port: int) -> str:
    host = f"[{endpoint.hostname}]" if ":" in endpoint.hostname else endpoint.hostname
    if endpoint.port == default_port:
        return host
    return f"{host}:{endpoint.port}"


def _websocket_transport_uri(endpoint: Endpoint) -> str:
    # TLS is established and validated explicitly before the WebSocket upgrade.
    # A ws URI tells websockets to use the already TLS-wrapped socket as-is.
    authority = _authority(endpoint, 443 if endpoint.scheme == "wss" else 80)
    path = endpoint.path or "/"
    return urllib.parse.urlunsplit(("ws", authority, path, "", ""))


def _decode_message(raw: str | bytes) -> dict[str, Any]:
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    value = json.loads(
        raw,
        object_pairs_hook=_reject_duplicate_pairs,
        parse_constant=_reject_json_constant,
    )
    if not isinstance(value, dict):
        raise ValueError("server message is not an object")
    return value


def _valid_compatibility(value: Any, expected: dict[str, Any]) -> bool:
    if not isinstance(value, dict) or set(value) != MANIFEST_FIELDS:
        return False
    if isinstance(value.get("protocolVersion"), bool) or not isinstance(value.get("protocolVersion"), int):
        return False
    return all(type(value[field]) is type(expected[field]) and value[field] == expected[field] for field in MANIFEST_FIELDS)


def _close_code(websocket: Any, error: BaseException | None = None) -> int | None:
    received = getattr(error, "rcvd", None)
    candidates = (
        getattr(received, "code", None),
        getattr(websocket, "close_code", None),
        getattr(getattr(websocket, "protocol", None), "close_code", None),
    )
    for code in candidates:
        if isinstance(code, int) and not isinstance(code, bool) and 1000 <= code <= 4999:
            return code
    return None


def _safe_server_error_code(value: Any) -> str:
    if isinstance(value, str) and _SAFE_SERVER_CODE.fullmatch(value):
        return value
    return "INVALID_SERVER_ERROR_CODE"


def _hello(
    websocket: Any,
    manifest: dict[str, Any],
    timeout: float,
    *,
    progress: Callable[[str, str], None] | None,
) -> dict[str, Any]:
    hello = {
        "protocolVersion": manifest["protocolVersion"],
        "messageId": f"zz-diagnostic-{uuid.uuid4().hex}",
        "type": "HELLO",
        "payload": {field: manifest[field] for field in HELLO_FIELDS},
    }
    try:
        websocket.send(json.dumps(hello, separators=(",", ":")))
        raw = websocket.recv(timeout=timeout)
    except (TimeoutError, socket.timeout) as exc:
        failure = ProbeFailure("game_hello", "timeout", "WELCOME_TIMEOUT")
        raise failure from exc
    except ConnectionClosed as exc:
        raise ProbeFailure(
            "game_hello",
            "connection_closed",
            "CONNECTION_CLOSED",
            {"closeCode": _close_code(websocket, exc)},
        ) from exc
    except OSError as exc:
        kind, code = _network_error(exc)
        raise ProbeFailure("game_hello", kind, code) from exc

    try:
        message = _decode_message(raw)
    except (UnicodeError, ValueError, json.JSONDecodeError, RecursionError) as exc:
        raise ProbeFailure("game_hello", "protocol", "INVALID_SERVER_MESSAGE") from exc
    if set(message) != {"protocolVersion", "messageId", "type", "payload"}:
        raise ProbeFailure("game_hello", "protocol", "INVALID_SERVER_MESSAGE")
    if (
        type(message["protocolVersion"]) is not int
        or message["protocolVersion"] != manifest["protocolVersion"]
        or not isinstance(message["messageId"], str)
        or not message["messageId"]
        or not isinstance(message["type"], str)
        or not isinstance(message["payload"], dict)
    ):
        raise ProbeFailure("game_hello", "protocol", "INVALID_SERVER_MESSAGE")

    if message["type"] == "ERROR":
        code = _safe_server_error_code(message["payload"].get("code"))
        close_code = None
        try:
            websocket.recv(timeout=min(timeout, 0.25))
        except ConnectionClosed as exc:
            close_code = _close_code(websocket, exc)
        except (TimeoutError, socket.timeout):
            close_code = _close_code(websocket)
        raise ProbeFailure(
            "game_hello",
            "server_error",
            code,
            {"serverErrorCode": code, "closeCode": close_code},
        )
    payload = message["payload"]
    if message["type"] != "WELCOME":
        raise ProbeFailure("game_hello", "protocol", "EXPECTED_WELCOME")
    if (
        set(payload) - {"connectionId", "playerId", "compatibility", "recoveryPersistenceAck"}
        or not isinstance(payload.get("connectionId"), str)
        or not payload["connectionId"]
        or ("playerId" in payload and not isinstance(payload["playerId"], str))
        or ("recoveryPersistenceAck" in payload and not isinstance(payload["recoveryPersistenceAck"], bool))
    ):
        raise ProbeFailure("game_hello", "protocol", "INVALID_WELCOME")
    compatible = _valid_compatibility(payload.get("compatibility"), manifest)
    if not compatible:
        raise ProbeFailure(
            "game_hello",
            "compatibility",
            "COMPATIBILITY_MISMATCH",
            {"compatibilityMatches": False},
        )
    return {"compatibilityMatches": True}


def _rtt_summary(samples: list[float]) -> dict[str, float | None]:
    if not samples:
        return {"min": None, "median": None, "p95": None, "max": None}
    ordered = sorted(samples)
    p95_index = max(0, math.ceil(0.95 * len(ordered)) - 1)
    return {
        "min": round(ordered[0], 3),
        "median": round(statistics.median(ordered), 3),
        "p95": round(ordered[p95_index], 3),
        "max": round(ordered[-1], 3),
    }


def _heartbeat_details(
    samples: list[float],
    started: float,
    websocket: Any,
) -> dict[str, Any]:
    return {
        "rttSamplesMs": [round(sample, 3) for sample in samples],
        "rttSummaryMs": _rtt_summary(samples),
        "completedDurationSeconds": round(time.monotonic() - started, 3),
        "closeCode": _close_code(websocket),
    }


def _heartbeat(
    websocket: Any,
    duration: float,
    interval: float,
    timeout: float,
) -> dict[str, Any]:
    started = time.monotonic()
    deadline = started + duration
    samples: list[float] = []
    while True:
        probe_started = time.monotonic()
        ping_started = time.perf_counter()
        try:
            pong = websocket.ping()
            if not pong.wait(timeout):
                details = _heartbeat_details(samples, started, websocket)
                raise ProbeFailure("heartbeat", "timeout", "PONG_TIMEOUT", details)
        except ProbeFailure:
            raise
        except ConnectionClosed as exc:
            details = _heartbeat_details(samples, started, websocket)
            details["closeCode"] = _close_code(websocket, exc)
            raise ProbeFailure(
                "heartbeat",
                "connection_closed",
                "CONNECTION_CLOSED",
                details,
            ) from exc
        except (TimeoutError, socket.timeout) as exc:
            details = _heartbeat_details(samples, started, websocket)
            raise ProbeFailure("heartbeat", "timeout", "PONG_TIMEOUT", details) from exc
        except OSError as exc:
            kind, code = _network_error(exc)
            details = _heartbeat_details(samples, started, websocket)
            raise ProbeFailure("heartbeat", kind, code, details) from exc
        samples.append((time.perf_counter() - ping_started) * 1000)
        remaining = deadline - time.monotonic()
        if probe_started >= deadline:
            break
        if remaining <= 0:
            # The last probe began before the observation window ended. Make
            # one more probe at its end so a close during the final sleep is seen.
            continue
        time.sleep(min(interval, remaining))
    return _heartbeat_details(samples, started, websocket)


def _close_websocket(websocket: Any) -> tuple[int | None, tuple[str, str] | None]:
    try:
        websocket.close()
    except (OSError, TimeoutError, socket.timeout) as exc:
        kind, code = _network_error(exc)
        return _close_code(websocket), (kind, code)
    return _close_code(websocket), None


def _probe_game(
    endpoint: Endpoint,
    manifest: dict[str, Any],
    *,
    duration: float,
    interval: float,
    timeout: float,
    report: dict[str, Any],
    progress: Callable[[str, str], None] | None,
    set_active: Callable[[str], None],
) -> None:
    tls = endpoint.scheme == "wss"
    stage_started = _begin_stage("dns", progress)
    set_active("dns")
    try:
        infos, answers = _resolve_addresses(endpoint.hostname, endpoint.port, timeout)
    except NetworkFailure as exc:
        details = dict(exc.details)
        details.update({"errorKind": exc.kind, "errorCode": exc.code})
        _append_check(report, "dns", "failed", stage_started, details, progress=progress)
        raise ProbeFailure("dns", exc.kind, exc.code, details) from exc
    _append_check(
        report,
        "dns",
        "passed",
        stage_started,
        {"addresses": answers, "answerCount": len(answers)},
        progress=progress,
    )

    stage_started = _begin_stage("tcp", progress)
    set_active("tcp")
    try:
        connected = _connect_direct(
            infos,
            endpoint.hostname,
            timeout,
            use_tls=tls,
        )
    except NetworkFailure as exc:
        details = dict(exc.details)
        tcp_attempts = details.get("tcpAttempts", [])
        tls_attempts = details.get("tlsAttempts", [])
        tcp_connected = bool(details.get("tcpConnected"))
        _append_check(
            report,
            "tcp",
            "passed" if tcp_connected else "failed",
            stage_started,
            {"attempts": tcp_attempts},
            progress=progress,
            elapsed_ms=details.get("tcpElapsedMs"),
        )
        if tls:
            _append_check(
                report,
                "tls",
                "failed" if tcp_connected else "skipped",
                time.perf_counter(),
                {"attempts": tls_attempts, "reason": "all_tls_attempts_failed" if tcp_connected else "tcp_unavailable"},
                progress=progress,
                elapsed_ms=details.get("tlsElapsedMs"),
            )
        stage = "tls" if tls and tcp_connected else "tcp"
        details.update({"errorKind": exc.kind, "errorCode": exc.code})
        raise ProbeFailure(stage, exc.kind, exc.code, details) from exc

    _append_check(
        report,
        "tcp",
        "passed",
        stage_started,
        {
            "attempts": connected.tcp_attempts,
            "selectedAddress": connected.selected_address,
        },
        progress=progress,
        elapsed_ms=connected.tcp_elapsed_ms,
    )
    if tls:
        _append_check(
            report,
            "tls",
            "passed",
            time.perf_counter(),
            {
                "attempts": connected.tls_attempts,
                "selectedAddress": connected.selected_address,
                "certificateValidation": "enabled",
            },
            progress=progress,
            elapsed_ms=connected.tls_elapsed_ms,
        )
    else:
        _append_check(
            report,
            "tls",
            "skipped",
            time.perf_counter(),
            {"reason": "endpoint_uses_ws"},
            progress=progress,
        )

    websocket = None
    stage_started = _begin_stage("websocket_upgrade", progress)
    set_active("websocket_upgrade")
    try:
        websocket = websocket_connect(
            _websocket_transport_uri(endpoint),
            sock=connected.sock,
            proxy=None,
            open_timeout=timeout,
            close_timeout=min(timeout, 1.0),
            ping_interval=None,
            ping_timeout=None,
            compression=None,
            max_size=16_384,
        )
    except (TimeoutError, socket.timeout) as exc:
        kind, code = _network_error(exc)
        _append_check(
            report,
            "websocket_upgrade",
            "failed",
            stage_started,
            {"errorKind": kind, "errorCode": "WEBSOCKET_UPGRADE_TIMEOUT"},
            progress=progress,
        )
        raise ProbeFailure("websocket_upgrade", "timeout", "WEBSOCKET_UPGRADE_TIMEOUT") from exc
    except InvalidHandshake as exc:
        status_code = getattr(getattr(exc, "response", None), "status_code", None)
        details = {"errorKind": "websocket", "errorCode": "INVALID_HANDSHAKE"}
        if isinstance(status_code, int) and not isinstance(status_code, bool):
            details["httpStatus"] = status_code
        _append_check(report, "websocket_upgrade", "failed", stage_started, details, progress=progress)
        raise ProbeFailure("websocket_upgrade", "websocket", "INVALID_HANDSHAKE", details) from exc
    except (OSError, ssl.SSLError) as exc:
        kind, code = _network_error(exc)
        details = {"errorKind": kind, "errorCode": code}
        _append_check(report, "websocket_upgrade", "failed", stage_started, details, progress=progress)
        raise ProbeFailure("websocket_upgrade", kind, code, details) from exc
    _append_check(report, "websocket_upgrade", "passed", stage_started, progress=progress)

    stage_started = _begin_stage("game_hello", progress)
    set_active("game_hello")
    try:
        hello_details = _hello(websocket, manifest, timeout, progress=None)
    except ProbeFailure as exc:
        _append_check(
            report,
            "game_hello",
            "failed",
            stage_started,
            {**exc.details, "errorKind": exc.kind, "errorCode": exc.code},
            progress=progress,
        )
        close_code, close_error = _close_websocket(websocket)
        last_check = report["checks"][-1]
        details = last_check.get("details", {})
        if details.get("closeCode") is None:
            details["closeCode"] = close_code
        if close_error is not None:
            details["closeErrorKind"], details["closeErrorCode"] = close_error
        exc.details = details
        raise
    _append_check(report, "game_hello", "passed", stage_started, hello_details, progress=progress)

    stage_started = _begin_stage("heartbeat", progress)
    set_active("heartbeat")
    try:
        heartbeat_details = _heartbeat(websocket, duration, interval, timeout)
    except ProbeFailure as exc:
        _append_check(
            report,
            "heartbeat",
            "failed",
            stage_started,
            {**exc.details, "errorKind": exc.kind, "errorCode": exc.code},
            progress=progress,
        )
        close_code, close_error = _close_websocket(websocket)
        last_check = report["checks"][-1]
        details = last_check.get("details", {})
        details["closeCode"] = details.get("closeCode") or close_code
        if close_error is not None:
            details["closeErrorKind"], details["closeErrorCode"] = close_error
        exc.details = details
        raise
    close_code, close_error = _close_websocket(websocket)
    heartbeat_details["closeCode"] = close_code
    if close_error is not None:
        heartbeat_details["closeErrorKind"], heartbeat_details["closeErrorCode"] = close_error
        _append_check(
            report,
            "heartbeat",
            "failed",
            stage_started,
            {**heartbeat_details, "errorKind": close_error[0], "errorCode": "WEBSOCKET_CLOSE_FAILED"},
            progress=progress,
        )
        raise ProbeFailure("heartbeat", close_error[0], "WEBSOCKET_CLOSE_FAILED", heartbeat_details)
    if close_code is not None and close_code != 1000:
        _append_check(
            report,
            "heartbeat",
            "failed",
            stage_started,
            {
                **heartbeat_details,
                "errorKind": "connection_closed",
                "errorCode": "UNEXPECTED_CLOSE_CODE",
            },
            progress=progress,
        )
        raise ProbeFailure(
            "heartbeat",
            "connection_closed",
            "UNEXPECTED_CLOSE_CODE",
            heartbeat_details,
        )
    _append_check(report, "heartbeat", "passed", stage_started, heartbeat_details, progress=progress)


def _health_host_header(endpoint: Endpoint) -> str:
    return _authority(endpoint, 443 if endpoint.scheme == "https" else 80)


def _probe_health(
    endpoint: Endpoint,
    expected_protocol: int,
    timeout: float,
    report: dict[str, Any],
    *,
    progress: Callable[[str, str], None] | None,
    set_active: Callable[[str], None],
) -> None:
    started = _begin_stage("health_check", progress)
    set_active("health_check")
    details: dict[str, Any] = {}
    try:
        infos, addresses = _resolve_addresses(endpoint.hostname, endpoint.port, timeout)
        details["addresses"] = addresses
    except NetworkFailure as exc:
        details.update({"errorKind": exc.kind, "errorCode": exc.code})
        _append_check(report, "health_check", "failed", started, details, progress=progress)
        raise ProbeFailure("health_check", exc.kind, exc.code, details) from exc
    try:
        connected = _connect_direct(
            infos,
            endpoint.hostname,
            timeout,
            use_tls=endpoint.scheme == "https",
        )
    except NetworkFailure as exc:
        details.update(exc.details)
        details.update({"errorKind": exc.kind, "errorCode": exc.code})
        _append_check(report, "health_check", "failed", started, details, progress=progress)
        raise ProbeFailure("health_check", exc.kind, exc.code, details) from exc

    sock = connected.sock
    sock.settimeout(timeout)
    details.update({
        "tcpAttempts": connected.tcp_attempts,
        "tlsAttempts": connected.tls_attempts,
        "selectedAddress": connected.selected_address,
    })
    response: http.client.HTTPResponse | None = None
    try:
        target = urllib.parse.quote(endpoint.path or "/", safe="/%:@!$&'()*+,;=-._~")
        request = (
            f"GET {target} HTTP/1.1\r\n"
            f"Host: {_health_host_header(endpoint)}\r\n"
            "Accept: application/json\r\n"
            "Connection: close\r\n\r\n"
        ).encode("ascii")
        sock.sendall(request)
        response = http.client.HTTPResponse(sock)
        response.begin()
        details["httpStatus"] = int(response.status)
        content_type = response.getheader("Content-Type", "")
        details["contentTypeValid"] = content_type.split(";", 1)[0].strip().lower() == "application/json"
        if response.status != 200:
            raise ProbeFailure("health_check", "health", "HTTP_STATUS", details)
        if not details["contentTypeValid"]:
            raise ProbeFailure("health_check", "health", "INVALID_CONTENT_TYPE", details)
        body = response.read(MAX_HEALTH_BODY_BYTES + 1)
        if len(body) > MAX_HEALTH_BODY_BYTES:
            raise ProbeFailure("health_check", "health", "HEALTH_BODY_TOO_LARGE", details)
        try:
            payload = json.loads(
                body.decode("utf-8"),
                object_pairs_hook=_reject_duplicate_pairs,
                parse_constant=_reject_json_constant,
            )
        except (UnicodeError, ValueError, json.JSONDecodeError, RecursionError) as exc:
            raise ProbeFailure("health_check", "health", "INVALID_JSON", details) from exc
        if (
            not isinstance(payload, dict)
            or set(payload) != {"status", "protocolVersion"}
            or payload.get("status") != "ok"
            or isinstance(payload.get("protocolVersion"), bool)
            or not isinstance(payload.get("protocolVersion"), int)
            or payload["protocolVersion"] != expected_protocol
        ):
            details["protocolMatches"] = False
            raise ProbeFailure("health_check", "health", "PROTOCOL_MISMATCH", details)
        details["protocolMatches"] = True
        details["healthStatus"] = "ok"
    except ProbeFailure as exc:
        exc.details = {**details, **exc.details}
        _append_check(report, "health_check", "failed", started, exc.details, progress=progress)
        raise
    except (OSError, TimeoutError, socket.timeout, http.client.HTTPException) as exc:
        kind, code = _network_error(exc)
        details.update({"errorKind": kind, "errorCode": code})
        _append_check(report, "health_check", "failed", started, details, progress=progress)
        raise ProbeFailure("health_check", kind, code, details) from exc
    finally:
        try:
            if response is not None:
                response.close()
        finally:
            sock.close()
    _append_check(report, "health_check", "passed", started, details, progress=progress)


def _mark_unrun_game_stages(
    report: dict[str, Any],
    active_stage: str,
    progress: Callable[[str, str], None] | None,
) -> None:
    present = {check["stage"] for check in report["checks"]}
    try:
        start_index = GAME_STAGES.index(active_stage) + 1
    except ValueError:
        start_index = 0
    for stage in GAME_STAGES[start_index:]:
        if stage not in present:
            _append_check(
                report,
                stage,
                "skipped",
                time.perf_counter(),
                {"reason": "earlier_stage_failed"},
                progress=progress,
            )


def run_diagnostic(
    endpoint: Endpoint,
    health_endpoint: Endpoint | None,
    manifest: dict[str, Any],
    *,
    duration: float = 60.0,
    interval: float = 5.0,
    timeout: float = 8.0,
    progress: Callable[[str, str], None] | None = None,
) -> dict[str, Any]:
    report: dict[str, Any] = {
        "schemaVersion": 1,
        "startedAt": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "endpoint": endpoint.display,
        "healthEndpoint": health_endpoint.display if health_endpoint is not None else None,
        "routeMode": "direct",
        "routeScope": "application_proxy_bypass_only",
        "routeNote": "Application proxies are bypassed; VPN/TUN routing is not measured, and this diagnostic cannot prove mainland residential egress.",
        "proxyPresent": _proxy_present(),
        "expectedCompatibility": dict(manifest),
        "checks": [],
    }
    active_stage = "dns"

    def set_active(stage: str) -> None:
        nonlocal active_stage
        active_stage = stage

    failure: ProbeFailure | None = None
    cancelled = False
    try:
        _probe_game(
            endpoint,
            manifest,
            duration=duration,
            interval=interval,
            timeout=timeout,
            report=report,
            progress=progress,
            set_active=set_active,
        )
    except ProbeFailure as exc:
        failure = exc
        _mark_unrun_game_stages(report, exc.stage, progress)
    except KeyboardInterrupt:
        cancelled = True
        _append_check(
            report,
            active_stage,
            "cancelled",
            time.perf_counter(),
            {"errorKind": "cancelled", "errorCode": "CANCELLED"},
            progress=progress,
        )
        _mark_unrun_game_stages(report, active_stage, progress)
        failure = ProbeFailure(active_stage, "cancelled", "CANCELLED")
    except Exception as exc:
        details = {
            "errorKind": "internal",
            "errorCode": "UNEXPECTED_ERROR",
            "exceptionType": type(exc).__name__,
        }
        _append_check(
            report,
            active_stage,
            "failed",
            time.perf_counter(),
            details,
            progress=progress,
        )
        _mark_unrun_game_stages(report, active_stage, progress)
        failure = ProbeFailure(active_stage, "internal", "UNEXPECTED_ERROR", details)

    if health_endpoint is None:
        _append_check(
            report,
            "health_check",
            "skipped",
            time.perf_counter(),
            {"reason": "disabled"},
            progress=progress,
        )
        report["healthStatus"] = "disabled"
    elif cancelled:
        _append_check(
            report,
            "health_check",
            "skipped",
            time.perf_counter(),
            {"reason": "diagnostic_cancelled"},
            progress=progress,
        )
        report["healthStatus"] = "skipped"
    else:
        try:
            _probe_health(
                health_endpoint,
                manifest["protocolVersion"],
                timeout,
                report,
                progress=progress,
                set_active=set_active,
            )
            report["healthStatus"] = "passed"
        except ProbeFailure as exc:
            if failure is None:
                failure = exc
            report["healthStatus"] = "failed"
        except KeyboardInterrupt:
            cancelled = True
            details = {"errorKind": "cancelled", "errorCode": "CANCELLED"}
            _append_check(
                report,
                "health_check",
                "cancelled",
                time.perf_counter(),
                details,
                progress=progress,
            )
            if failure is None:
                failure = ProbeFailure("health_check", "cancelled", "CANCELLED")
            report["healthStatus"] = "skipped"
        except Exception as exc:
            details = {
                "errorKind": "internal",
                "errorCode": "UNEXPECTED_ERROR",
                "exceptionType": type(exc).__name__,
            }
            _append_check(
                report,
                "health_check",
                "failed",
                time.perf_counter(),
                details,
                progress=progress,
            )
            if failure is None:
                failure = ProbeFailure("health_check", "internal", "UNEXPECTED_ERROR", details)
            report["healthStatus"] = "failed"

    game_failed = any(
        check["stage"] in GAME_STAGES and check["status"] in {"failed", "cancelled"}
        for check in report["checks"]
    )
    report["gameStatus"] = "failed" if game_failed else "passed"
    report["overallStatus"] = "failed" if failure is not None else "passed"
    report["failedStage"] = failure.stage if failure is not None else None
    report["error"] = (
        {"kind": failure.kind, "code": failure.code}
        if failure is not None
        else None
    )
    return report


def _validate_timing(duration: float, interval: float, timeout: float) -> bool:
    return all(math.isfinite(value) and value > 0 for value in (duration, interval, timeout))


def _default_output_path() -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    return Path.cwd() / f"zz-multiplayer-network-diagnostic-{stamp}.json"


def _write_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Diagnose direct ZZ multiplayer connectivity")
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--health-url", default=DEFAULT_HEALTH_URL)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--duration", type=float, default=60.0)
    parser.add_argument("--interval", type=float, default=5.0)
    parser.add_argument("--timeout", type=float, default=8.0)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)

    try:
        endpoint = _parse_endpoint(args.url, {"ws", "wss"})
    except ValueError:
        parser.error("--url must be a ws:// or wss:// URL without credentials, query, or fragment")
    try:
        health_endpoint = (
            _parse_endpoint(args.health_url, {"http", "https"})
            if args.health_url != ""
            else None
        )
    except ValueError:
        parser.error("--health-url must be an http:// or https:// URL without credentials, query, or fragment")
    if not _validate_timing(args.duration, args.interval, args.timeout):
        parser.error("--duration, --interval, and --timeout must be finite positive numbers")
    try:
        manifest = _load_manifest(args.manifest or _default_manifest_path())
    except ValueError:
        parser.error("compatibility manifest is missing or invalid")

    output_path = args.output or _default_output_path()
    current_stage = "dns"

    def progress(stage: str, status: str) -> None:
        nonlocal current_stage
        if status == "running":
            current_stage = stage
        print(f"[{stage}] {status}", flush=True)

    try:
        report = run_diagnostic(
            endpoint,
            health_endpoint,
            manifest,
            duration=args.duration,
            interval=args.interval,
            timeout=args.timeout,
            progress=progress,
        )
    except Exception as exc:
        report = {
            "schemaVersion": 1,
            "startedAt": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "endpoint": endpoint.display,
            "healthEndpoint": health_endpoint.display if health_endpoint is not None else None,
            "routeMode": "direct",
            "routeScope": "application_proxy_bypass_only",
            "routeNote": "Application proxies are bypassed; VPN/TUN routing is not measured, and this diagnostic cannot prove mainland residential egress.",
            "proxyPresent": _proxy_present(),
            "expectedCompatibility": dict(manifest),
            "checks": [{
                "stage": current_stage,
                "status": "failed",
                "elapsedMs": 0,
                "details": {
                    "errorKind": "internal",
                    "errorCode": "UNEXPECTED_ERROR",
                    "exceptionType": type(exc).__name__,
                },
            }],
            "gameStatus": "failed" if current_stage in GAME_STAGES else "passed",
            "healthStatus": "failed" if current_stage == "health_check" else "skipped",
            "overallStatus": "failed",
            "failedStage": current_stage,
            "error": {"kind": "internal", "code": "UNEXPECTED_ERROR"},
        }
        print(f"[{current_stage}] failed ({type(exc).__name__})", flush=True)
    _write_report(output_path, report)
    print(f"report: {output_path}", flush=True)
    return 0 if report["overallStatus"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
