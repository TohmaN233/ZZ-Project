from __future__ import annotations

import ast
import json
import socket
import ssl
import subprocess
import sys
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from typing import Any, Iterator

import pytest
from websockets.sync.server import serve

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import multiplayer_network_diagnostic as diagnostic
from zz.multiplayer.service import MultiplayerServer
from zz.multiplayer.websocket_server import (
    WebSocketMultiplayerGateway,
    WebSocketServerConfig,
)


MANIFEST = diagnostic._load_manifest(diagnostic._default_manifest_path())


@contextmanager
def _running_gateway(
    *,
    connection_id: str = "diagnostic-test-connection",
    core: MultiplayerServer | None = None,
) -> Iterator[str]:
    gateway = WebSocketMultiplayerGateway(
        core or MultiplayerServer(),
        config=WebSocketServerConfig(
            host="127.0.0.1",
            port=0,
            heartbeat_interval_seconds=0.2,
            heartbeat_timeout_seconds=0.5,
        ),
        connection_id_factory=lambda: connection_id,
    )
    with gateway.create_server() as server:
        thread = Thread(target=server.serve_forever, name="zz-diagnostic-test-gateway")
        thread.start()
        port = server.socket.getsockname()[1]
        try:
            yield f"ws://127.0.0.1:{port}/multiplayer"
        finally:
            server.shutdown()
            thread.join(timeout=3)
            assert not thread.is_alive()


@contextmanager
def _running_raw_websocket(handler: Any) -> Iterator[str]:
    with serve(
        handler,
        "127.0.0.1",
        0,
        compression=None,
        ping_interval=None,
        ping_timeout=None,
    ) as server:
        thread = Thread(target=server.serve_forever, name="zz-diagnostic-test-raw-ws")
        thread.start()
        port = server.socket.getsockname()[1]
        try:
            yield f"ws://127.0.0.1:{port}/"
        finally:
            server.shutdown()
            thread.join(timeout=3)
            assert not thread.is_alive()


@contextmanager
def _running_health(status: int, body: bytes, content_type: str = "application/json") -> Iterator[str]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, _format: str, *_args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, name="zz-diagnostic-test-health")
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/healthz"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
        assert not thread.is_alive()


def _run(
    url: str,
    *,
    health_url: str = "",
    manifest: dict[str, Any] | None = None,
    duration: float = 0.03,
    interval: float = 0.01,
    timeout: float = 0.5,
) -> dict[str, Any]:
    endpoint = diagnostic._parse_endpoint(url, {"ws", "wss"})
    health_endpoint = (
        diagnostic._parse_endpoint(health_url, {"http", "https"})
        if health_url
        else None
    )
    return diagnostic.run_diagnostic(
        endpoint,
        health_endpoint,
        dict(manifest or MANIFEST),
        duration=duration,
        interval=interval,
        timeout=timeout,
    )


def test_diagnostic_connects_to_local_gateway_without_creating_a_room() -> None:
    core = MultiplayerServer()
    with _running_gateway(core=core) as url:
        report = _run(url)

    assert report["overallStatus"] == "passed"
    assert report["schemaVersion"] == 1
    assert report["gameStatus"] == "passed"
    assert report["healthStatus"] == "disabled"
    assert report["startedAt"].endswith("Z")
    assert report["expectedCompatibility"] == MANIFEST
    assert [check["stage"] for check in report["checks"]] == [
        "dns",
        "tcp",
        "tls",
        "websocket_upgrade",
        "game_hello",
        "heartbeat",
        "health_check",
    ]
    assert report["checks"][2]["status"] == "skipped"
    heartbeat = report["checks"][5]["details"]
    assert heartbeat["rttSamplesMs"]
    assert set(heartbeat["rttSummaryMs"]) == {"min", "median", "p95", "max"}
    assert heartbeat["completedDurationSeconds"] >= 0.03
    assert "roomCode" not in json.dumps(report)
    assert core._rooms == {}


def test_report_endpoint_preserves_non_root_path_and_root_path() -> None:
    endpoint = diagnostic._parse_endpoint("wss://example.invalid/multiplayer", {"ws", "wss"})
    root_endpoint = diagnostic._parse_endpoint("ws://example.invalid", {"ws", "wss"})

    assert endpoint.display == "wss://example.invalid:443/multiplayer"
    assert root_endpoint.display == "ws://example.invalid:80/"


def test_refused_tcp_is_reported_with_resolved_address_and_skipped_stages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class RefusedSocket:
        def settimeout(self, _timeout: float) -> None:
            return None

        def connect(self, _address: Any) -> None:
            raise ConnectionRefusedError(10061, "PRIVATE_REFUSAL_DETAIL")

        def close(self) -> None:
            return None

    monkeypatch.setattr(diagnostic.socket, "socket", lambda *_args: RefusedSocket())
    monkeypatch.setattr(
        diagnostic,
        "_resolve_addresses",
        lambda *_args: (
            [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("203.0.113.8", 32145))],
            [{"family": "IPv4", "address": "203.0.113.8", "outcome": "resolved"}],
        ),
    )
    report = _run("ws://zz.example.invalid:32145/", timeout=0.3)

    assert report["failedStage"] == "tcp"
    assert report["error"] == {"kind": "network", "code": "ECONNREFUSED"}
    assert report["checks"][0]["details"]["addresses"]
    assert report["checks"][1]["status"] == "failed"
    assert report["checks"][2]["status"] == "skipped"
    assert report["checks"][3]["status"] == "skipped"


def test_dns_timeout_is_bounded_and_dns_errors_are_allowlisted(monkeypatch: pytest.MonkeyPatch) -> None:
    import time

    def delayed_lookup(*_args: Any, **_kwargs: Any) -> list[Any]:
        time.sleep(0.1)
        return []

    monkeypatch.setattr(diagnostic.socket, "getaddrinfo", delayed_lookup)
    with pytest.raises(diagnostic.NetworkFailure) as timeout_error:
        diagnostic._resolve_addresses("slow.invalid", 443, 0.01)
    assert (timeout_error.value.kind, timeout_error.value.code) == ("timeout", "EAI_TIMEOUT")

    def failed_lookup(*_args: Any, **_kwargs: Any) -> list[Any]:
        raise socket.gaierror(getattr(socket, "EAI_NONAME", -2), "PRIVATE_LOOKUP_DETAIL")

    monkeypatch.setattr(diagnostic.socket, "getaddrinfo", failed_lookup)
    with pytest.raises(diagnostic.NetworkFailure) as dns_error:
        diagnostic._resolve_addresses("missing.invalid", 443, 0.2)
    assert (dns_error.value.kind, dns_error.value.code) == ("dns", "EAI_NONAME")
    assert "PRIVATE_LOOKUP_DETAIL" not in repr(dns_error.value.details)


def test_tls_certificate_failure_is_reported_without_raw_tls_error(monkeypatch: pytest.MonkeyPatch) -> None:
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    port = listener.getsockname()[1]

    def fail_tls(*_args: Any, **_kwargs: Any) -> Any:
        raise ssl.SSLCertVerificationError("PRIVATE_CERTIFICATE_DETAIL")

    monkeypatch.setattr(diagnostic, "_wrap_tls", fail_tls)
    try:
        report = _run(f"wss://127.0.0.1:{port}/", timeout=0.3)
    finally:
        listener.close()

    assert report["failedStage"] == "tls"
    assert report["error"] == {"kind": "tls", "code": "CERTIFICATE_VERIFY_FAILED"}
    assert report["checks"][1]["status"] == "passed"
    assert report["checks"][2]["status"] == "failed"
    assert "PRIVATE_CERTIFICATE_DETAIL" not in json.dumps(report)


def test_gateway_rejects_incompatible_hello_and_reports_close_code() -> None:
    mismatched = {**MANIFEST, "applicationVersion": "9.9.9"}
    with _running_gateway() as url:
        report = _run(url, manifest=mismatched)

    assert report["failedStage"] == "game_hello"
    assert report["error"] == {"kind": "server_error", "code": "INCOMPATIBLE_GAME_VERSION"}
    check = report["checks"][4]
    assert check["details"]["serverErrorCode"] == "INCOMPATIBLE_GAME_VERSION"
    assert check["details"]["closeCode"] == 1002
    assert report["checks"][5]["status"] == "skipped"


def test_invalid_welcome_compatibility_is_rejected_without_recording_connection_id() -> None:
    private_connection_id = "PRIVATE_CONNECTION_ID"

    def handler(websocket: Any) -> None:
        websocket.recv(timeout=1)
        bad_compatibility = {**MANIFEST, "rulesVersion": "wrong-rules"}
        websocket.send(json.dumps({
            "protocolVersion": MANIFEST["protocolVersion"],
            "messageId": "welcome-1",
            "type": "WELCOME",
            "payload": {
                "connectionId": private_connection_id,
                "compatibility": bad_compatibility,
            },
        }))

    with _running_raw_websocket(handler) as url:
        report = _run(url)

    assert report["failedStage"] == "game_hello"
    assert report["error"] == {"kind": "compatibility", "code": "COMPATIBILITY_MISMATCH"}
    assert private_connection_id not in json.dumps(report)


def test_heartbeat_timeout_records_partial_rtt_and_close_evidence() -> None:
    class PendingPong:
        def wait(self, _timeout: float) -> bool:
            return False

    class StalledWebSocket:
        close_code = None

        def ping(self) -> PendingPong:
            return PendingPong()

    with pytest.raises(diagnostic.ProbeFailure) as error:
        diagnostic._heartbeat(StalledWebSocket(), duration=0.02, interval=0.01, timeout=0.01)

    assert error.value.stage == "heartbeat"
    assert (error.value.kind, error.value.code) == ("timeout", "PONG_TIMEOUT")
    assert error.value.details["rttSamplesMs"] == []
    assert error.value.details["rttSummaryMs"] == {
        "min": None,
        "median": None,
        "p95": None,
        "max": None,
    }
    assert error.value.details["completedDurationSeconds"] >= 0
    assert error.value.details["closeCode"] is None


def test_heartbeat_observes_server_close_during_final_interval() -> None:
    def handler(websocket: Any) -> None:
        websocket.recv(timeout=1)
        websocket.send(json.dumps({
            "protocolVersion": MANIFEST["protocolVersion"],
            "messageId": "welcome-1",
            "type": "WELCOME",
            "payload": {
                "connectionId": "loopback-diagnostic",
                "compatibility": MANIFEST,
            },
        }))
        import time
        time.sleep(0.12)
        websocket.close(code=1011, reason="test server failure")

    with _running_raw_websocket(handler) as url:
        report = _run(url, duration=0.25, interval=0.4, timeout=0.5)

    assert report["failedStage"] == "heartbeat"
    assert report["error"] == {"kind": "connection_closed", "code": "CONNECTION_CLOSED"}
    heartbeat = report["checks"][5]
    assert heartbeat["status"] == "failed"
    assert heartbeat["details"]["closeCode"] == 1011


def test_unexpected_close_code_fails_even_without_close_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeSocket:
        def close(self) -> None:
            return None

    class Pong:
        def wait(self, _timeout: float) -> bool:
            return True

    class FakeWebSocket:
        close_code = None

        def ping(self) -> Pong:
            return Pong()

    websocket = FakeWebSocket()
    monkeypatch.setattr(
        diagnostic,
        "_resolve_addresses",
        lambda *_args: (
            [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("203.0.113.8", 80))],
            [{"family": "IPv4", "address": "203.0.113.8", "outcome": "resolved"}],
        ),
    )
    monkeypatch.setattr(
        diagnostic,
        "_connect_direct",
        lambda *_args, **_kwargs: diagnostic.ConnectedSocket(
            sock=FakeSocket(),
            selected_address={"family": "IPv4", "address": "203.0.113.8"},
            tcp_attempts=[],
            tls_attempts=[],
            tcp_elapsed_ms=0,
            tls_elapsed_ms=0,
        ),
    )
    monkeypatch.setattr(diagnostic, "websocket_connect", lambda *_args, **_kwargs: websocket)
    monkeypatch.setattr(diagnostic, "_hello", lambda *_args, **_kwargs: {"compatibilityMatches": True})
    monkeypatch.setattr(diagnostic, "_close_websocket", lambda _websocket: (1011, None))
    report: dict[str, Any] = {"checks": []}

    with pytest.raises(diagnostic.ProbeFailure) as error:
        diagnostic._probe_game(
            diagnostic._parse_endpoint("ws://example.invalid/multiplayer", {"ws", "wss"}),
            MANIFEST,
            duration=0.001,
            interval=0.001,
            timeout=0.01,
            report=report,
            progress=None,
            set_active=lambda _stage: None,
        )

    assert (error.value.stage, error.value.kind, error.value.code) == (
        "heartbeat",
        "connection_closed",
        "UNEXPECTED_CLOSE_CODE",
    )
    assert report["checks"][-1]["status"] == "failed"
    assert report["checks"][-1]["details"]["closeCode"] == 1011


def test_health_failure_is_separate_from_successful_game_route() -> None:
    body = b"PRIVATE_HEALTH_RESPONSE_BODY"
    with _running_gateway() as ws_url, _running_health(503, body) as health_url:
        report = _run(ws_url, health_url=health_url)

    assert report["gameStatus"] == "passed"
    assert report["healthStatus"] == "failed"
    assert report["overallStatus"] == "failed"
    assert report["failedStage"] == "health_check"
    assert report["error"] == {"kind": "health", "code": "HTTP_STATUS"}
    assert report["checks"][-1]["details"]["httpStatus"] == 503
    assert body.decode() not in json.dumps(report)


def test_health_requires_exact_json_protocol_shape() -> None:
    good_body = json.dumps({
        "status": "ok",
        "protocolVersion": MANIFEST["protocolVersion"],
    }).encode("ascii")
    bad_body = json.dumps({
        "status": "ok",
        "protocolVersion": MANIFEST["protocolVersion"] + 1,
    }).encode("ascii")
    with _running_gateway() as ws_url, _running_health(200, good_body) as health_url:
        good_report = _run(ws_url, health_url=health_url)
    with _running_gateway() as ws_url, _running_health(200, bad_body) as health_url:
        bad_report = _run(ws_url, health_url=health_url)

    assert good_report["healthStatus"] == "passed"
    assert good_report["checks"][-1]["details"]["protocolMatches"] is True
    assert bad_report["gameStatus"] == "passed"
    assert bad_report["healthStatus"] == "failed"
    assert bad_report["error"] == {"kind": "health", "code": "PROTOCOL_MISMATCH"}


def test_report_redacts_proxy_values_and_connection_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    proxy_secret = "PRIVATE_PROXY_CREDENTIAL"
    monkeypatch.setattr(
        diagnostic.urllib.request,
        "getproxies",
        lambda: {"https": f"http://user:{proxy_secret}@proxy.internal"},
    )
    with _running_gateway(connection_id="PRIVATE_CONNECTION_ID") as url:
        report = _run(url)

    encoded = json.dumps(report)
    assert report["proxyPresent"] is True
    assert report["routeMode"] == "direct"
    assert "VPN/TUN routing is not measured" in report["routeNote"]
    assert proxy_secret not in encoded
    assert "proxy.internal" not in encoded
    assert "PRIVATE_CONNECTION_ID" not in encoded


def test_cli_failure_writes_json_and_exits_nonzero(tmp_path: Path) -> None:
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    listener.close()
    output = tmp_path / "network-report.json"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "tools.multiplayer_network_diagnostic",
            "--url",
            f"ws://127.0.0.1:{port}/",
            "--health-url",
            "",
            "--timeout",
            "0.3",
            "--output",
            str(output),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert result.returncode == 1
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["failedStage"] == "tcp"
    assert report["error"]["code"] in {"ECONNREFUSED", "ETIMEDOUT"}
    assert "report:" in result.stdout


def test_invalid_cli_configuration_exits_two_without_leaking_url_secret(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    secret = "PRIVATE_URL_SECRET"
    output = tmp_path / "invalid.json"
    with pytest.raises(SystemExit) as exit_error:
        diagnostic.main([
            "--url",
            f"ftp://example.invalid/{secret}",
            "--output",
            str(output),
        ])
    assert exit_error.value.code == 2
    assert secret not in capsys.readouterr().err
    assert not output.exists()


@pytest.mark.parametrize(
    "url",
    [
        "wss://user:password@example.invalid/multiplayer",
        "wss://example.invalid/multiplayer?",
        "wss://example.invalid/multiplayer#",
    ],
)
def test_endpoint_rejects_credentials_query_and_fragment(url: str) -> None:
    with pytest.raises(ValueError):
        diagnostic._parse_endpoint(url, {"ws", "wss"})


def test_standalone_manifest_sibling_takes_precedence_and_is_not_fallen_back(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    script_dir = tmp_path / "standalone"
    script_dir.mkdir()
    monkeypatch.setattr(diagnostic, "__file__", str(script_dir / "multiplayer_network_diagnostic.py"))
    sibling = script_dir / "compatibility.json"
    sibling.write_text("{invalid", encoding="utf-8")

    assert diagnostic._default_manifest_path() == sibling
    with pytest.raises(ValueError, match="invalid compatibility manifest"):
        diagnostic._load_manifest(diagnostic._default_manifest_path())


def test_frozen_manifest_is_loaded_from_pyinstaller_bundle_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(diagnostic.sys, "frozen", True, raising=False)
    monkeypatch.setattr(diagnostic.sys, "_MEIPASS", str(tmp_path), raising=False)

    assert diagnostic._default_manifest_path() == tmp_path / "compatibility.json"


def test_diagnostic_module_has_no_game_or_asset_imports() -> None:
    tree = ast.parse(Path(diagnostic.__file__).read_text(encoding="utf-8"))
    imported_roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_roots.add(node.module.split(".", 1)[0])
    assert not ({"zz", "PIL", "torch", "numpy"} & imported_roots)
