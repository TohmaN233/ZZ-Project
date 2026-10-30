from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from urllib.request import urlopen

import zz.web.server as web_server


def test_parallel_asset_requests_initialize_only_one_session(tmp_path, monkeypatch):
    asset = tmp_path / "card.png"
    asset.write_bytes(b"card image")
    created = []

    def create_session(**kwargs):
        session = SimpleNamespace(asset_index=SimpleNamespace(resolve_asset_id=lambda _: asset))
        created.append(session)
        time.sleep(0.1)
        return session

    monkeypatch.setattr(web_server, "GameSession", create_session)
    app = web_server.ServerState(seed=1)
    monkeypatch.setattr(app, "settings_store", lambda: SimpleNamespace(load=lambda: {}))
    server = web_server.make_server("127.0.0.1", 0, app)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    barrier = threading.Barrier(8)

    def fetch(_):
        barrier.wait(timeout=5)
        with urlopen(f"http://127.0.0.1:{server.server_port}/assets/card", timeout=5) as response:
            return response.read()

    try:
        with ThreadPoolExecutor(max_workers=8) as pool:
            responses = list(pool.map(fetch, range(8)))
        assert responses == [b"card image"] * 8
        assert len(created) == 1
        assert app.session is created[0]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
