import os
from pathlib import Path

from zz.greedy_ai import GreedyLegalPolicy
from zz.web.session import GameSession


ROOT = Path(__file__).resolve().parents[1]


def test_ai_vs_ai_uses_codeman_or_deep_for_both_seats() -> None:
    session = GameSession(
        seed=1,
        mode="ai-vs-ai",
        asset_root=os.environ.get("ZZ_RELEASE_ASSET_ROOT", str(ROOT / "asserts")),
        player_profile={"codemanId": "kouhou_ai_mina"},
        opponent_profile={"codemanId": "kouhou_ai_mina"},
        opponent_ai_difficulty="easy",
        ai_data_root=str(ROOT / "data"),
    )

    assert all(not isinstance(policy, GreedyLegalPolicy) for policy in session.ai_policies)
    session.auto_step(1)
    assert session.prompt is None


def test_duel_reload_restarts_ai_vs_ai_automatically() -> None:
    app_source = (ROOT / "zz" / "web" / "static" / "app.js").read_text(encoding="utf-8")

    assert 'state.mode === "ai-vs-ai" && !state.gameOver' in app_source
    assert "startAuto();" in app_source[app_source.index("function loadState()") :]
