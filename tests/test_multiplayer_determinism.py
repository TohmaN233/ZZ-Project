import random

from zz.ai import RandomLegalPolicy
from zz.multiplayer.actions import CHOOSE_PROMPT_OPTION
from zz.multiplayer.match import AuthoritativeMatch, InitialMatchSpec
from zz.web.session import GameSession


def _safe_progress_choice(prompt: dict) -> dict:
    options = prompt["options"]
    if prompt["kind"] == "mulligan":
        selected = next(option for option in options if option["id"] == "keep")
    else:
        by_kind = {option.get("kind"): option for option in options}
        selected = (
            by_kind.get("end_turn")
            or by_kind.get("skip_mana")
            or by_kind.get("place_colorless_mana")
            or options[0]
        )
    return {
        "kind": CHOOSE_PROMPT_OPTION,
        "promptId": prompt["id"],
        "optionId": selected["id"],
        "payload": {},
    }


def _varied_first_choice(prompt: dict) -> dict:
    selected = prompt["options"][0]
    payload = {}
    if prompt["kind"] == "effect_target":
        required = int(prompt.get("requiredTargetCount", 1))
        payload["selectedOptionIds"] = [
            option["id"] for option in prompt["options"][:required]
        ]
    return {
        "kind": CHOOSE_PROMPT_OPTION,
        "promptId": prompt["id"],
        "optionId": selected["id"],
        "payload": payload,
    }


def _complete_match(match: AuthoritativeMatch) -> tuple:
    results = []
    for index in range(200):
        if match.session._game_over is not None:
            break
        owner = match.prompt_owner_id()
        assert owner is not None
        result = match.submit_controller_action(
            player_id=owner,
            client_action_id=f"action-{index + 1}",
            chooser=_safe_progress_choice,
        )
        assert result.accepted is True, result.rejection
        results.append(result)
    else:
        raise AssertionError("deterministic match did not finish within 200 decisions")
    return tuple(results)


def _complete_varied_match(match: AuthoritativeMatch) -> tuple:
    results = []
    for index in range(400):
        if match.session._game_over is not None:
            break
        owner = match.prompt_owner_id()
        assert owner is not None
        result = match.submit_controller_action(
            player_id=owner,
            client_action_id=f"varied-{index + 1}",
            chooser=_varied_first_choice,
        )
        assert result.accepted is True, result.rejection
        results.append(result)
    else:
        raise AssertionError("varied match did not finish within 400 decisions")
    return tuple(results)


def test_complete_action_log_replays_with_identical_hashes_events_and_winner() -> None:
    spec = InitialMatchSpec.standard(match_id="deterministic-replay", seed=301)
    original = AuthoritativeMatch(spec)
    original_results = _complete_match(original)

    replayed, replay_results = AuthoritativeMatch.replay(spec, original.action_log)

    assert [result.accepted for result in replay_results] == [True] * len(original_results)
    assert [result.revision for result in replay_results] == [
        result.revision for result in original_results
    ]
    assert [result.events for result in replay_results] == [
        result.events for result in original_results
    ]
    assert [result.state_hash for result in replay_results] == [
        result.state_hash for result in original_results
    ]
    assert replayed.state_hash() == original.state_hash()
    assert replayed.session._game_over == original.session._game_over
    assert replayed.revision == original.revision


def test_same_initial_spec_has_same_revision_zero_hash_in_one_process() -> None:
    spec = InitialMatchSpec.standard(match_id="same-initial-hash", seed=302)
    first = AuthoritativeMatch(spec)
    second = AuthoritativeMatch(spec)

    assert first.canonical_state() == second.canonical_state()
    assert first.state_hash() == second.state_hash()


def test_varied_card_effect_and_combat_match_replays_deterministically() -> None:
    spec = InitialMatchSpec.standard(match_id="varied-replay", seed=777)
    original = AuthoritativeMatch(spec)
    original_results = _complete_varied_match(original)

    replayed, replay_results = AuthoritativeMatch.replay(spec, original.action_log)

    assert len(replay_results) == len(original_results)
    assert [result.state_hash for result in replay_results] == [
        result.state_hash for result in original_results
    ]
    assert [result.events for result in replay_results] == [
        result.events for result in original_results
    ]
    assert replayed.state_hash() == original.state_hash()
    assert replayed.session._game_over == original.session._game_over


def test_existing_ai_policies_submit_through_same_authoritative_action_api() -> None:
    spec = InitialMatchSpec.standard(match_id="policy-controller", seed=778)
    match = AuthoritativeMatch(spec)
    policies = {
        "player_1": RandomLegalPolicy(random.Random(1778)),
        "player_2": RandomLegalPolicy(random.Random(2778)),
    }

    for index in range(500):
        if match.session._game_over is not None:
            break
        owner = match.prompt_owner_id()
        assert owner is not None
        result = match.submit_policy_action(
            player_id=owner,
            client_action_id=f"policy-{index + 1}",
            policy=policies[owner],
        )
        assert result.accepted is True, result.rejection
    else:
        raise AssertionError("policy-driven match did not finish within 500 decisions")

    replayed, replay_results = AuthoritativeMatch.replay(spec, match.action_log)
    assert len(replay_results) == len(match.action_log)
    assert replayed.state_hash() == match.state_hash()
    assert replayed.session._game_over == match.session._game_over


def test_authoritative_god_mode_does_not_load_local_ai_checkpoints(
    monkeypatch,
) -> None:
    def fail_if_loaded(_seed: int):
        raise AssertionError("authoritative god mode must not load an AI checkpoint")

    monkeypatch.setattr("zz.web.session._local_game_deep_policy", fail_if_loaded)

    session = GameSession(seed=701, mode="god")

    assert session.ai_policies == []
    assert session.prompt is not None
