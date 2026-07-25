from zz import codeman_replay_correction as correction
from zz.enums import AttackTargetKind
from zz.model import AttackTarget
from zz.web.session import GameSession


def _ready_god_session(seed: int = 901) -> GameSession:
    session = GameSession(seed=seed, mode="god")
    for _ in range(2):
        prompt = session.prompt
        assert prompt is not None and prompt["kind"] == "mulligan"
        session.choose(
            prompt["id"],
            "keep",
            {"promptId": prompt["id"], "optionId": "keep"},
        )
    return session


def test_corrected_replay_branch_keeps_duel_animation_events(monkeypatch, tmp_path) -> None:
    session = _ready_god_session()
    engine = session.engine
    action = next(action for action in engine.legal_actions() if action.kind == "play_to_base")

    monkeypatch.setattr(correction, "_engine_from_event_snapshot", lambda *args, **kwargs: engine)
    monkeypatch.setattr(correction, "TRAINING_MAX_ACTIONS", 1)

    result = correction._play_replay_branch(
        {"player_side": engine.state.active.side.name, "mode": "god", "seed": 901},
        {"playerSide": engine.state.active.side.name, "mode": "god", "seed": 901},
        {"eventIndex": 0, "snapshotIndex": 1},
        action,
        data_root=tmp_path,
        seed=902,
    )

    assert len(result["stateSnapshots"]) == 2
    assert any(
        event.get("type") == "zone_move"
        for event in result["stateSnapshots"][1]["animationEvents"]
    )


def test_corrected_replay_combat_uses_live_duel_attack_event_shape() -> None:
    session = _ready_god_session(seed=903)
    engine = session.engine
    attacker = engine.state.active.hand[0]
    target = AttackTarget(AttackTargetKind.PLAYER, engine.state.opponent)

    class _TargetPolicy:
        def choose_attack_target(self, _engine, _attacker, _targets):
            return target

    recorder = correction._ReplayAnimationRecorder(engine, session.asset_index)
    before = recorder.visual_snapshot()
    selected = correction._ReplayVisualPolicy(_TargetPolicy()).choose_attack_target(
        engine,
        attacker,
        [target],
    )
    events = recorder.collect(before)

    assert selected is target
    assert events == [{
        "type": "attack",
        "side": attacker.owner.side.name,
        "attacker": session._card_log_payload(attacker),
        "attackerIid": attacker.iid,
        "targetKind": "player",
        "targetSide": engine.state.opponent.side.name,
        "targetForceId": None,
        "targetCardIid": None,
    }]
