from zz.web.session import GameSession


def test_existing_web_choice_payload_remains_compatible() -> None:
    session = GameSession(seed=401, mode="human-vs-ai")
    prompt = session.prompt
    assert prompt is not None and prompt["kind"] == "mulligan"

    state = session.choose(
        prompt["id"],
        "keep",
        {"promptId": prompt["id"], "optionId": "keep"},
    )

    assert state["error"] is None
    assert session.engine.state.players[0].mulligan_done is True


def test_invalid_payload_does_not_clear_active_prompt() -> None:
    session = GameSession(seed=402, mode="human-vs-ai")
    prompt = session.prompt
    assert prompt is not None

    state = session.choose(
        prompt["id"],
        "keep",
        {"promptId": prompt["id"], "optionId": "keep", "unexpected": True},
    )

    assert state["error"]["code"] == "invalid_payload"
    assert session.prompt is not None
    assert session.prompt["id"] == prompt["id"]
