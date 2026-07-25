from __future__ import annotations

from pathlib import Path

from zz.ai_registry import resolve_battle_policy
from zz.web.server import ServerState
from zz.web.session import GameSession


def main() -> None:
    root = Path.cwd()
    assert (root / "zz").is_dir(), root
    assert (root / "ai_training").is_dir(), root
    app = ServerState(seed=123)
    catalog = app.catalog()
    assert catalog.get("cards"), "empty catalog"
    session = GameSession(seed=123, mode="human-vs-ai", opponent_ai_difficulty="easy")
    state = session.state_dto()
    assert state.get("players") and state.get("prompt") is not None
    normal = GameSession(seed=124, mode="human-vs-ai", opponent_ai_difficulty="normal")
    assert normal.opponent_ai_difficulty == "normal"
    deep = GameSession(seed=125, mode="human-vs-ai", opponent_ai_difficulty="deep")
    assert deep.opponent_ai_difficulty == "deep"
    codeman = resolve_battle_policy("codeman", seed=126, codeman_id="codeman_03_nonoin_nillon")
    assert codeman.resolved_kind == "deep"
    assert codeman.fallback_used is True
    assert (root / "docs" / "index.html").is_file()
    assert (root / "PUBLIC_RELEASE_MANIFEST.json").is_file()
    import ai_training.codeman_training as codeman_training
    assert codeman_training.CODEMAN_DEFAULT_CIRCLES == 10
    print("clean-release-smoke-ok")


if __name__ == "__main__":
    main()
