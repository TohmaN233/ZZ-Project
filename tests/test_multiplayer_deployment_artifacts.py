from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_deployment_environment_example_has_required_non_secret_configuration() -> None:
    text = (ROOT / "deploy" / "zz-multiplayer.env.example").read_text(encoding="utf-8")
    keys = {
        line.split("=", 1)[0]
        for line in text.splitlines()
        if line and not line.startswith("#")
    }
    assert {
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
    } <= keys
    assert "password" not in text.lower()
    assert "secret" not in text.lower()
    assert "token" not in text.lower()
    assert "127.0.0.1" in text


def test_python_package_discovery_excludes_non_package_release_directories() -> None:
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")

    assert '[tool.setuptools.packages.find]' in pyproject
    assert 'include = ["zz*"]' in pyproject
    assert 'exclude = ["data*", "deploy*", "tests*", "tools*"]' in pyproject
    assert '"zz.multiplayer" = ["compatibility.json"]' in pyproject


def test_authoritative_server_import_does_not_load_optional_ai_runtime() -> None:
    script = """
import sys
import zz.multiplayer.deployment_server

forbidden = {"numpy", "zz.deep_runtime", "zz.ai_registry", "zz.ai_runtime_stack"}
loaded = forbidden.intersection(sys.modules)
if loaded:
    raise SystemExit(f"optional AI runtime imported by PvP server: {sorted(loaded)}")
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout


def test_systemd_and_nginx_keep_internal_ports_private_and_enable_restart() -> None:
    service = (ROOT / "deploy" / "systemd" / "zz-multiplayer.service").read_text(
        encoding="utf-8"
    )
    nginx = (ROOT / "deploy" / "nginx" / "zz-multiplayer.conf").read_text(
        encoding="utf-8"
    )

    assert "EnvironmentFile=/etc/zz-multiplayer.env" in service
    assert "python -m zz.multiplayer.deployment_server" in service
    assert "Restart=on-failure" in service
    assert "NoNewPrivileges=true" in service
    assert "proxy_pass http://127.0.0.1:32145" in nginx
    assert "proxy_pass http://127.0.0.1:32146/healthz" in nginx
    assert "proxy_set_header Upgrade $http_upgrade" in nginx
    assert 'proxy_set_header Connection "upgrade"' in nginx
    assert "listen 443 ssl" in nginx


def test_runbook_keeps_external_acceptance_explicitly_human_owned() -> None:
    runbook = (ROOT / "docs" / "multiplayer" / "vm-deployment.md").read_text(
        encoding="utf-8"
    )

    assert "--check-config" in runbook
    assert "nginx -t" in runbook
    assert "systemctl enable --now" in runbook
    assert "human-help-checklist.md" in runbook
    assert "different networks" in runbook
