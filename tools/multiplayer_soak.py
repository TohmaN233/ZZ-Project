from __future__ import annotations

import argparse
import json
from concurrent.futures import ProcessPoolExecutor
from typing import Any

from zz.multiplayer.actions import CHOOSE_PROMPT_OPTION, SubmittedAction
from zz.multiplayer.match import AuthoritativeMatch, InitialMatchSpec


def _progress_action(prompt: dict[str, Any]) -> dict[str, Any]:
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


def _assert_private_view(match: AuthoritativeMatch, player_id: str) -> None:
    view = match.get_view_for(player_id)
    opponent = view["players"]["opponent"]
    if "deck" in opponent:
        raise AssertionError("opponent deck order leaked")
    forbidden_card_keys = {"iid", "cardId", "nameJp", "abilityJp"}
    for card in opponent["hand"]:
        leaked = forbidden_card_keys.intersection(card)
        if leaked:
            raise AssertionError(f"opponent hand leaked fields: {sorted(leaked)}")
    owner = match.prompt_owner_id()
    if owner != player_id and view["prompt"] is not None:
        raise AssertionError("prompt options leaked to the non-owning player")
    if "seed" in view or "rngState" in view:
        raise AssertionError("server-only RNG data leaked")


def _run_match(args: tuple[int, int, int]) -> tuple[int, int]:
    match_index, seed, max_decisions = args
    total_actions = 0
    duplicate_accepted_actions = 0
    spec = InitialMatchSpec.standard(
        match_id=f"soak-{match_index + 1}",
        seed=seed + match_index,
    )
    match = AuthoritativeMatch(spec)
    original_results = []
    for decision_index in range(max_decisions):
        if match.session._game_over is not None:
            break
        owner = match.prompt_owner_id()
        if owner is None:
            raise AssertionError("unfinished match has no prompt owner")
        prompt = match.get_view_for(owner)["prompt"]
        if prompt is None:
            raise AssertionError("prompt owner has no prompt")
        submitted = SubmittedAction(
            match_id=match.match_id,
            player_id=owner,
            client_action_id=f"soak-{match_index + 1}-{decision_index + 1}",
            expected_revision=match.revision,
            action=_progress_action(prompt),
        )
        action_count = len(match.action_log)
        result = match.submit_action(submitted)
        if not result.accepted:
            raise AssertionError(f"soak action rejected: {result.rejection}")
        original_results.append(result)
        total_actions += 1
        if decision_index == 0:
            duplicate = match.submit_action(submitted)
            if duplicate != result:
                raise AssertionError("duplicate action did not return its cached result")
            if len(match.action_log) != action_count + 1:
                duplicate_accepted_actions += 1
        _assert_private_view(match, "player_1")
        _assert_private_view(match, "player_2")
    if match.session._game_over is None:
        raise AssertionError(
            f"match {match.match_id} did not finish within {max_decisions} decisions"
        )
    replayed, replay_results = AuthoritativeMatch.replay(spec, match.action_log)
    if [result.state_hash for result in replay_results] != [
        result.state_hash for result in original_results
    ]:
        raise AssertionError(f"replay hash sequence diverged for {match.match_id}")
    if [result.events for result in replay_results] != [
        result.events for result in original_results
    ]:
        raise AssertionError(f"replay event sequence diverged for {match.match_id}")
    if replayed.state_hash() != match.state_hash():
        raise AssertionError(f"final state hash diverged for {match.match_id}")
    if replayed.session._game_over != match.session._game_over:
        raise AssertionError(f"final result diverged for {match.match_id}")
    return total_actions, duplicate_accepted_actions


def run_soak(
    *,
    matches: int = 100,
    seed: int = 10_000,
    max_decisions: int = 250,
    workers: int = 1,
) -> dict[str, int]:
    if matches <= 0 or max_decisions <= 0 or workers <= 0:
        raise ValueError("matches, max_decisions and workers must be positive")
    arguments = [
        (match_index, seed, max_decisions)
        for match_index in range(matches)
    ]
    if workers == 1:
        results = [_run_match(args) for args in arguments]
    else:
        with ProcessPoolExecutor(max_workers=workers) as executor:
            results = list(executor.map(_run_match, arguments))
    total_actions = sum(result[0] for result in results)
    duplicate_accepted_actions = sum(result[1] for result in results)
    return {
        "completeMatches": matches,
        "desyncs": 0,
        "uncaughtExceptions": 0,
        "duplicateAcceptedActions": duplicate_accepted_actions,
        "hiddenInformationLeaks": 0,
        "totalActions": total_actions,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the ZZ deterministic multiplayer smoke gate")
    parser.add_argument("--matches", type=int, default=100)
    parser.add_argument("--seed", type=int, default=10_000)
    parser.add_argument("--max-decisions", type=int, default=250)
    parser.add_argument("--workers", type=int, default=1)
    args = parser.parse_args()
    report = run_soak(
        matches=args.matches,
        seed=args.seed,
        max_decisions=args.max_decisions,
        workers=args.workers,
    )
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
