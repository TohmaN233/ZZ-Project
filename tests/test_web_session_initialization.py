from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from urllib.request import urlopen

import zz.web.server as web_server


def test_parallel_session_requests_initialize_only_one_session(monkeypatch):
    created = []

    def create_session(**kwargs):
        session = object()
        created.append(session)
        time.sleep(0.1)
        return session

    monkeypatch.setattr(web_server, "GameSession", create_session)
    app = web_server.ServerState(seed=1)
    monkeypatch.setattr(app, "settings_store", lambda: SimpleNamespace(load=lambda: {}))
    barrier = threading.Barrier(8)

    def get_session(_):
        barrier.wait(timeout=5)
        return app.ensure_session()

    with ThreadPoolExecutor(max_workers=8) as pool:
        sessions = list(pool.map(get_session, range(8)))
    assert len(created) == 1
    assert all(session is created[0] for session in sessions)


def test_parallel_asset_requests_do_not_create_a_game_session(tmp_path, monkeypatch):
    asset = tmp_path / "card.png"
    asset.write_bytes(b"card image")
    index = SimpleNamespace(resolve_asset_id=lambda _: asset, resolve_audio_id=lambda _: asset)
    created = []

    def create_session(**kwargs):
        created.append(True)
        return SimpleNamespace(asset_index=index)

    monkeypatch.setattr(web_server, "GameSession", create_session)
    monkeypatch.setattr(web_server, "AssetIndex", lambda _: index, raising=False)
    app = web_server.ServerState(seed=1)
    monkeypatch.setattr(app, "settings_store", lambda: SimpleNamespace(load=lambda: {}))
    server = web_server.make_server("127.0.0.1", 0, app)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    barrier = threading.Barrier(8)

    def fetch(i):
        barrier.wait(timeout=5)
        resource = "/assets/card" if i % 2 == 0 else "/audio/bgm"
        with urlopen(f"http://127.0.0.1:{server.server_port}{resource}", timeout=5) as response:
            return response.read()

    try:
        with ThreadPoolExecutor(max_workers=8) as pool:
            responses = list(pool.map(fetch, range(8)))
        assert responses == [b"card image"] * 8
        assert not created
        assert app.session is None
        session_asset = tmp_path / "session-card.png"
        session_asset.write_bytes(b"session image")
        session_index = SimpleNamespace(resolve_asset_id=lambda _: session_asset)
        app.session = SimpleNamespace(asset_index=session_index)
        with urlopen(f"http://127.0.0.1:{server.server_port}/assets/card", timeout=5) as response:
            assert response.read() == b"session image"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
