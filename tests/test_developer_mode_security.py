from __future__ import annotations

from zz.web.server import DEV_MODE_PASSWORD_ENV, ServerState, dispatch_api


def test_developer_mode_fails_closed_until_password_is_configured(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv(DEV_MODE_PASSWORD_ENV, raising=False)
    app = ServerState(settings_root=tmp_path)

    status, payload = dispatch_api(
        app,
        "POST",
        "/api/settings/developer-mode",
        {"enabled": True, "password": "guess"},
    )

    assert status == 503
    assert payload["error"]["code"] == "developer_mode_unconfigured"


def test_developer_mode_uses_environment_password(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv(DEV_MODE_PASSWORD_ENV, "release-test-password")
    app = ServerState(settings_root=tmp_path)

    wrong_status, wrong_payload = dispatch_api(
        app,
        "POST",
        "/api/settings/developer-mode",
        {"enabled": True, "password": "wrong"},
    )
    ok_status, ok_payload = dispatch_api(
        app,
        "POST",
        "/api/settings/developer-mode",
        {"enabled": True, "password": "release-test-password"},
    )

    assert wrong_status == 403
    assert wrong_payload["error"]["code"] == "invalid_developer_password"
    assert ok_status == 200
    assert ok_payload["devMode"] is True
