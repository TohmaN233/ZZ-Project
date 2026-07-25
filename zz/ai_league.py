from __future__ import annotations

import json
import random
from collections import Counter
from contextlib import nullcontext
from pathlib import Path
from typing import Any

from zz.ai_registry import ResolvedBattlePolicy, _runtime_prior_kwargs, resolve_battle_policy
from zz.batched_eval_profile import aggregate_runtime_profiles
from zz.engine import GameOver
from zz.greedy_ai import GreedyLegalPolicy
from zz.runtime_profile import RuntimeProfile
from zz.rl_ai import (
    DEEP_HUMANLIKE_PRIOR_WEIGHT,
    DEEP_LOOKAHEAD_BRANCH_WIDTH,
    DEEP_LOOKAHEAD_DEPTH,
    DEEP_LOOKAHEAD_KEY_DECISIONS_ONLY,
    DEEP_LOOKAHEAD_WEIGHT,
    DEEP_MAX_LOOKAHEAD_ACTIONS,
    EpisodeRecorder,
    LinearQModel,
    LookaheadRLPolicy,
    model_uses_observed_opponent_features,
)
from zz.rl_ai import _utc_now
from zz.rl_training import _setup_game


DEFAULT_DIFFICULTY_MATCHUPS = (
    ("easy", "normal"),
    ("easy", "deep"),
    ("normal", "deep"),
    ("deep", "normal"),
)


def run_difficulty_league_evaluation(
    *,
    episodes: int,
    seed: int,
    matchups: list[tuple[str, str]] | tuple[tuple[str, str], ...] = DEFAULT_DIFFICULTY_MATCHUPS,
    normal_model_path: str | Path | None = None,
    deep_model_path: str | Path | None = None,
    data_root: str | Path | None = None,
    benchmark_decks: list[Any] | tuple[Any, ...] | None = None,
    deck_root: str | Path | None = None,
    max_deck_pairs: int | None = None,
    max_turns: int = 30,
    max_actions: int = 500,
    report_out: str | Path | None = None,
    profile_runtime: bool = False,
) -> dict[str, Any]:
    deck_pairs = _difficulty_deck_pairs(
        benchmark_decks,
        deck_root=deck_root,
        max_deck_pairs=max_deck_pairs,
    )
    rows: list[dict[str, Any]] = []
    policy_template_cache: dict[str, dict[str, Any]] = {}
    for matchup_index, (model_kind, opponent_kind) in enumerate(matchups):
        for deck_pair_index, (model_deck, opponent_deck) in enumerate(deck_pairs):
            for side_index, model_side in enumerate(("P1", "P2")):
                rows.append(_evaluate_difficulty_matchup(
                    model_kind=model_kind,
                    opponent_kind=opponent_kind,
                    model_side=model_side,
                    episodes=episodes,
                    seed=seed + matchup_index * 10007 + deck_pair_index * 2003 + side_index * 503,
                    normal_model_path=normal_model_path,
                    deep_model_path=deep_model_path,
                    data_root=data_root,
                    model_deck=model_deck,
                    opponent_deck=opponent_deck,
                    policy_template_cache=policy_template_cache,
                    max_turns=max_turns,
                    max_actions=max_actions,
                    profile_runtime=profile_runtime,
                ))

    report = {
        "kind": "battle_policy_difficulty_league",
        "createdAt": _utc_now(),
        "seed": seed,
        "episodesPerSeat": episodes,
        "matchups": len(matchups),
        "deckPairCount": len(deck_pairs),
        "maxTurns": max_turns,
        "maxActions": max_actions,
        "rowCount": len(rows),
        "averageWinRate": sum(row["winRate"] for row in rows) / max(1, len(rows)),
        "minimumWinRate": min((row["winRate"] for row in rows), default=0.0),
        "rows": rows,
    }
    if profile_runtime:
        report["runtimeProfile"] = aggregate_runtime_profiles(rows)
    report["forcePreference"] = _force_preference_from_rows(rows)
    report["recommendation"] = select_recommended_difficulty_champion(report)
    if report_out is not None:
        _write_json(report_out, report)
    return report


def run_difficulty_focus_evaluation(
    *,
    episodes: int,
    seed: int,
    model_kind: str,
    opponent_kind: str,
    model_side: str,
    model_deck: Any,
    opponent_decks: list[Any] | tuple[Any, ...],
    normal_model_path: str | Path | None = None,
    deep_model_path: str | Path | None = None,
    data_root: str | Path | None = None,
    max_turns: int = 30,
    max_actions: int = 500,
    report_out: str | Path | None = None,
    profile_runtime: bool = False,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    policy_template_cache: dict[str, dict[str, Any]] = {}
    requested_side = str(model_side)
    for opponent_index, opponent_deck in enumerate(opponent_decks):
        if requested_side == "both":
            sides = ["P1", "P2"]
        elif requested_side == "random":
            sides = [random.Random(seed + opponent_index * 2003).choice(["P1", "P2"])]
        else:
            sides = [requested_side]
        for side_index, actual_side in enumerate(sides):
            rows.append(_evaluate_difficulty_matchup(
                model_kind=model_kind,
                opponent_kind=opponent_kind,
                model_side=actual_side,
                episodes=episodes,
                seed=seed + opponent_index * 2003 + side_index * 100_003,
                normal_model_path=normal_model_path,
                deep_model_path=deep_model_path,
                data_root=data_root,
                model_deck=model_deck,
                opponent_deck=opponent_deck,
                policy_template_cache=policy_template_cache,
                max_turns=max_turns,
                max_actions=max_actions,
                profile_runtime=profile_runtime,
            ))
    games = sum(
        int(row["results"].get("model", 0)) + int(row["results"].get("opponent", 0)) + int(row["results"].get("tie", 0))
        for row in rows
    )
    wins = sum(int(row["results"].get("model", 0)) for row in rows)
    report = {
        "kind": "battle_policy_difficulty_focus",
        "createdAt": _utc_now(),
        "seed": seed,
        "episodesPerRow": episodes,
        "modelKind": model_kind,
        "opponentKind": opponent_kind,
        "modelSide": requested_side,
        "focusDeckId": _deck_id_or_none(model_deck),
        "focusDeckName": _deck_name_or_none(model_deck),
        "focusForces": _deck_forces_or_empty(model_deck),
        "opponentDeckCount": len(opponent_decks),
        "maxTurns": max_turns,
        "maxActions": max_actions,
        "rowCount": len(rows),
        "games": games,
        "wins": wins,
        "winRate": wins / max(1, games),
        "limitedGames": sum(int(row.get("limitedGames", 0)) for row in rows),
        "modelTimeouts": sum(int(row.get("modelTimeouts", 0)) for row in rows),
        "opponentTimeouts": sum(int(row.get("opponentTimeouts", 0)) for row in rows),
        "rows": rows,
    }
    if profile_runtime:
        report["runtimeProfile"] = aggregate_runtime_profiles(rows)
    if report_out is not None:
        _write_json(report_out, report)
    return report


def run_player_vs_oldtop10_gate(
    *,
    episodes: int,
    seed: int,
    model_kind: str = "deep",
    opponent_kind: str = "normal",
    player_decks: list[Any] | tuple[Any, ...] | None = None,
    old_top10_decks: list[Any] | tuple[Any, ...] | None = None,
    deck_root: str | Path | None = None,
    top_suite_path: str | Path = "data/ai_training/top_deck_suite_v2_latest.json",
    max_player_decks: int | None = None,
    max_old_top10_decks: int | None = None,
    model_side: str = "random",
    pass_threshold: float = 0.70,
    normal_model_path: str | Path | None = None,
    deep_model_path: str | Path | None = None,
    model_deep_model_path: str | Path | None = None,
    opponent_deep_model_path: str | Path | None = None,
    allow_model_unpromoted_public_deep_v2: bool = False,
    allow_opponent_unpromoted_public_deep_v2: bool = False,
    model_runtime_prior_weights: dict[str, float] | None = None,
    opponent_runtime_prior_weights: dict[str, float] | None = None,
    data_root: str | Path | None = None,
    max_turns: int = 30,
    max_actions: int = 500,
    record_transition_choice_audits: bool = False,
    transition_choice_audit_limit: int = 20,
    transition_choice_audit_changed_only: bool = False,
    report_out: str | Path | None = None,
    policy_template_cache: dict[str, dict[str, Any]] | None = None,
    profile_runtime: bool = False,
    model_action_set_recorder: Any | None = None,
) -> dict[str, Any]:
    resolved_player_decks = _limit_decks(
        list(player_decks) if player_decks is not None else _load_player_gate_decks(deck_root),
        max_player_decks,
    )
    resolved_old_top10_decks = _limit_decks(
        list(old_top10_decks) if old_top10_decks is not None else _load_old_top10_gate_decks(top_suite_path),
        max_old_top10_decks,
    )
    if not resolved_player_decks:
        raise ValueError("player_vs_oldtop10 gate requires at least one player deck")
    if not resolved_old_top10_decks:
        raise ValueError("player_vs_oldtop10 gate requires at least one old top10 deck")

    rows: list[dict[str, Any]] = []
    policy_template_cache = policy_template_cache if policy_template_cache is not None else {}
    seat_rng = random.Random(seed)
    requested_side = str(model_side)
    for player_index, player_deck in enumerate(resolved_player_decks):
        for opponent_index, old_top10_deck in enumerate(resolved_old_top10_decks):
            if requested_side == "both":
                sides = ["P1", "P2"]
            elif requested_side == "random":
                sides = [seat_rng.choice(["P1", "P2"])]
            else:
                sides = [requested_side]
            for side_index, actual_side in enumerate(sides):
                row = _evaluate_difficulty_matchup(
                    model_kind=model_kind,
                    opponent_kind=opponent_kind,
                    model_side=actual_side,
                    episodes=episodes,
                    seed=seed + player_index * 100_003 + opponent_index * 2003 + side_index * 503,
                    normal_model_path=normal_model_path,
                    deep_model_path=deep_model_path,
                    model_deep_model_path=model_deep_model_path,
                    opponent_deep_model_path=opponent_deep_model_path,
                    allow_model_unpromoted_public_deep_v2=allow_model_unpromoted_public_deep_v2,
                    allow_opponent_unpromoted_public_deep_v2=allow_opponent_unpromoted_public_deep_v2,
                    model_runtime_prior_weights=model_runtime_prior_weights,
                    opponent_runtime_prior_weights=opponent_runtime_prior_weights,
                    data_root=data_root,
                    model_deck=player_deck,
                    opponent_deck=old_top10_deck,
                    policy_template_cache=policy_template_cache,
                    max_turns=max_turns,
                    max_actions=max_actions,
                    record_transition_choice_audits=record_transition_choice_audits,
                    transition_choice_audit_limit=transition_choice_audit_limit,
                    transition_choice_audit_changed_only=transition_choice_audit_changed_only,
                    profile_runtime=profile_runtime,
                    model_action_set_recorder=model_action_set_recorder,
                )
                row.update({
                    "playerDeckId": row["modelDeckId"],
                    "playerDeckName": row["modelDeckName"],
                    "playerForces": list(row["modelForces"]),
                    "playerDeckProvenance": _deck_provenance(player_deck, "player"),
                    "oldTop10DeckId": row["opponentDeckId"],
                    "oldTop10DeckName": row["opponentDeckName"],
                    "oldTop10Forces": list(row["opponentForces"]),
                    "oldTop10DeckProvenance": _deck_provenance(old_top10_deck, "old_top10"),
                })
                rows.append(row)

    gate = summarize_player_vs_oldtop10_gate(rows, pass_threshold=pass_threshold)
    report = {
        "kind": "player_vs_oldtop10_gate",
        "createdAt": _utc_now(),
        "seed": seed,
        "episodesPerRow": episodes,
        "modelKind": model_kind,
        "opponentKind": opponent_kind,
        "modelSideMode": requested_side,
        "playerDeckCount": len(resolved_player_decks),
        "oldTop10DeckCount": len(resolved_old_top10_decks),
        "modelRuntimePriorWeights": dict(model_runtime_prior_weights or {}),
        "opponentRuntimePriorWeights": dict(opponent_runtime_prior_weights or {}),
        "maxTurns": max_turns,
        "maxActions": max_actions,
        "recordTransitionChoiceAudits": bool(record_transition_choice_audits),
        "transitionChoiceAuditLimit": max(0, int(transition_choice_audit_limit)),
        "transitionChoiceAuditChangedOnly": bool(transition_choice_audit_changed_only),
        "rowCount": len(rows),
        "averageWinRate": gate["averageWinRate"],
        "minimumRowWinRate": gate["minimumRowWinRate"],
        "gate": gate,
        "rows": rows,
    }
    if profile_runtime:
        report["runtimeProfile"] = aggregate_runtime_profiles(rows)
    if report_out is not None:
        _write_json(report_out, report)
    return report


def run_deck_set_comparison_gate(
    *,
    episodes: int,
    seed: int,
    candidate_decks: list[Any] | tuple[Any, ...],
    reference_decks: list[Any] | tuple[Any, ...],
    model_kind: str = "deep",
    opponent_kind: str | None = None,
    model_side: str = "random",
    pass_threshold: float = 0.50,
    normal_model_path: str | Path | None = None,
    deep_model_path: str | Path | None = None,
    data_root: str | Path | None = None,
    max_candidate_decks: int | None = None,
    max_reference_decks: int | None = None,
    max_turns: int = 30,
    max_actions: int = 500,
    report_out: str | Path | None = None,
    profile_runtime: bool = False,
) -> dict[str, Any]:
    resolved_candidate_decks = _limit_decks(list(candidate_decks), max_candidate_decks)
    resolved_reference_decks = _limit_decks(list(reference_decks), max_reference_decks)
    if not resolved_candidate_decks:
        raise ValueError("deck-set comparison requires at least one candidate deck")
    if not resolved_reference_decks:
        raise ValueError("deck-set comparison requires at least one reference deck")

    resolved_opponent_kind = opponent_kind or model_kind
    rows: list[dict[str, Any]] = []
    policy_template_cache: dict[str, dict[str, Any]] = {}
    seat_rng = random.Random(seed)
    requested_side = str(model_side)
    for candidate_index, candidate_deck in enumerate(resolved_candidate_decks):
        for reference_index, reference_deck in enumerate(resolved_reference_decks):
            if requested_side == "both":
                sides = ["P1", "P2"]
            elif requested_side == "random":
                sides = [seat_rng.choice(["P1", "P2"])]
            else:
                sides = [requested_side]
            for side_index, actual_side in enumerate(sides):
                row = _evaluate_difficulty_matchup(
                    model_kind=model_kind,
                    opponent_kind=resolved_opponent_kind,
                    model_side=actual_side,
                    episodes=episodes,
                    seed=seed + candidate_index * 100_003 + reference_index * 2003 + side_index * 503,
                    normal_model_path=normal_model_path,
                    deep_model_path=deep_model_path,
                    data_root=data_root,
                    model_deck=candidate_deck,
                    opponent_deck=reference_deck,
                    policy_template_cache=policy_template_cache,
                    max_turns=max_turns,
                    max_actions=max_actions,
                    profile_runtime=profile_runtime,
                )
                row.update({
                    "candidateDeckId": row["modelDeckId"],
                    "candidateDeckName": row["modelDeckName"],
                    "candidateForces": list(row["modelForces"]),
                    "candidateDeckProvenance": _deck_provenance(candidate_deck, "candidate"),
                    "referenceDeckId": row["opponentDeckId"],
                    "referenceDeckName": row["opponentDeckName"],
                    "referenceForces": list(row["opponentForces"]),
                    "referenceDeckProvenance": _deck_provenance(reference_deck, "reference"),
                })
                rows.append(row)

    gate = summarize_deck_set_comparison_gate(rows, pass_threshold=pass_threshold)
    report = {
        "kind": "deck_set_comparison_gate",
        "createdAt": _utc_now(),
        "seed": seed,
        "episodesPerRow": episodes,
        "modelKind": model_kind,
        "opponentKind": resolved_opponent_kind,
        "modelSideMode": requested_side,
        "candidateDeckCount": len(resolved_candidate_decks),
        "referenceDeckCount": len(resolved_reference_decks),
        "maxTurns": max_turns,
        "maxActions": max_actions,
        "rowCount": len(rows),
        "candidateWinRate": gate["candidateWinRate"],
        "minimumRowWinRate": gate["minimumRowWinRate"],
        "gate": gate,
        "rows": rows,
    }
    if profile_runtime:
        report["runtimeProfile"] = aggregate_runtime_profiles(rows)
    if report_out is not None:
        _write_json(report_out, report)
    return report


def summarize_player_vs_oldtop10_gate(
    rows: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    *,
    pass_threshold: float = 0.70,
) -> dict[str, Any]:
    wins = games = errors = timeout_count = 0
    seat_stats: dict[str, Counter[str]] = {"P1": Counter(), "P2": Counter()}
    deck_stats: dict[str, Counter[str]] = {}
    zero_rows: list[dict[str, Any]] = []
    row_win_rates: list[float] = []
    for row in rows:
        results = row.get("results") or {}
        row_wins = int(results.get("model", 0))
        row_games = row_wins + int(results.get("opponent", 0)) + int(results.get("tie", 0))
        row_errors = int(results.get("errors", 0))
        wins += row_wins
        games += row_games
        errors += row_errors
        timeout_count += int(row.get("modelTimeouts", 0)) + int(row.get("opponentTimeouts", 0))
        row_win_rates.append(float(row.get("winRate", row_wins / max(1, row_games))))
        if row_games > 0 and row_wins == 0:
            zero_rows.append({
                "playerDeckId": row.get("playerDeckId") or row.get("modelDeckId"),
                "oldTop10DeckId": row.get("oldTop10DeckId") or row.get("opponentDeckId"),
                "modelSide": row.get("modelSide"),
                "seed": row.get("seed"),
            })
        side = str(row.get("modelSide") or "")
        if side in seat_stats:
            seat_stats[side]["wins"] += row_wins
            seat_stats[side]["games"] += row_games
        deck_id = str(row.get("playerDeckId") or row.get("modelDeckId") or "deck")
        deck_stats.setdefault(deck_id, Counter())
        deck_stats[deck_id]["wins"] += row_wins
        deck_stats[deck_id]["games"] += row_games

    per_deck = [
        {
            "playerDeckId": deck_id,
            "wins": int(stats["wins"]),
            "games": int(stats["games"]),
            "winRate": int(stats["wins"]) / max(1, int(stats["games"])),
        }
        for deck_id, stats in sorted(deck_stats.items())
    ]
    average_win_rate = wins / max(1, games)
    minimum_row_win_rate = min(row_win_rates, default=0.0)
    minimum_player_deck_win_rate = min((row["winRate"] for row in per_deck), default=0.0)
    passed = (
        average_win_rate >= float(pass_threshold)
        and not zero_rows
        and errors == 0
        and timeout_count == 0
    )
    return {
        "threshold": float(pass_threshold),
        "passed": passed,
        "wins": wins,
        "games": games,
        "averageWinRate": average_win_rate,
        "p1WinRate": int(seat_stats["P1"]["wins"]) / max(1, int(seat_stats["P1"]["games"])),
        "p2WinRate": int(seat_stats["P2"]["wins"]) / max(1, int(seat_stats["P2"]["games"])),
        "minimumRowWinRate": minimum_row_win_rate,
        "minimumPlayerDeckWinRate": minimum_player_deck_win_rate,
        "zeroRowCount": len(zero_rows),
        "zeroRows": zero_rows,
        "timeoutCount": timeout_count,
        "errorCount": errors,
        "perPlayerDeck": per_deck,
    }


def summarize_deck_set_comparison_gate(
    rows: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    *,
    pass_threshold: float = 0.50,
) -> dict[str, Any]:
    candidate_wins = reference_wins = ties = games = errors = timeout_count = 0
    seat_stats: dict[str, Counter[str]] = {"P1": Counter(), "P2": Counter()}
    candidate_stats: dict[str, Counter[str]] = {}
    reference_stats: dict[str, Counter[str]] = {}
    zero_rows: list[dict[str, Any]] = []
    row_win_rates: list[float] = []
    for row in rows:
        results = row.get("results") or {}
        row_candidate_wins = int(results.get("model", 0))
        row_reference_wins = int(results.get("opponent", 0))
        row_ties = int(results.get("tie", 0))
        row_games = row_candidate_wins + row_reference_wins + row_ties
        row_errors = int(results.get("errors", 0))
        candidate_wins += row_candidate_wins
        reference_wins += row_reference_wins
        ties += row_ties
        games += row_games
        errors += row_errors
        timeout_count += int(row.get("modelTimeouts", 0)) + int(row.get("opponentTimeouts", 0))
        row_win_rate = float(row.get("winRate", row_candidate_wins / max(1, row_games)))
        row_win_rates.append(row_win_rate)
        if row_games > 0 and row_candidate_wins == 0:
            zero_rows.append({
                "candidateDeckId": row.get("candidateDeckId") or row.get("modelDeckId"),
                "referenceDeckId": row.get("referenceDeckId") or row.get("opponentDeckId"),
                "modelSide": row.get("modelSide"),
                "seed": row.get("seed"),
            })
        side = str(row.get("modelSide") or "")
        if side in seat_stats:
            seat_stats[side]["wins"] += row_candidate_wins
            seat_stats[side]["games"] += row_games
        candidate_id = str(row.get("candidateDeckId") or row.get("modelDeckId") or "candidate")
        candidate_stats.setdefault(candidate_id, Counter())
        candidate_stats[candidate_id]["wins"] += row_candidate_wins
        candidate_stats[candidate_id]["games"] += row_games
        reference_id = str(row.get("referenceDeckId") or row.get("opponentDeckId") or "reference")
        reference_stats.setdefault(reference_id, Counter())
        reference_stats[reference_id]["candidateWins"] += row_candidate_wins
        reference_stats[reference_id]["referenceWins"] += row_reference_wins
        reference_stats[reference_id]["games"] += row_games

    per_candidate = [
        {
            "candidateDeckId": deck_id,
            "wins": int(stats["wins"]),
            "games": int(stats["games"]),
            "winRate": int(stats["wins"]) / max(1, int(stats["games"])),
        }
        for deck_id, stats in sorted(candidate_stats.items())
    ]
    per_reference = [
        {
            "referenceDeckId": deck_id,
            "candidateWins": int(stats["candidateWins"]),
            "referenceWins": int(stats["referenceWins"]),
            "games": int(stats["games"]),
            "candidateWinRate": int(stats["candidateWins"]) / max(1, int(stats["games"])),
        }
        for deck_id, stats in sorted(reference_stats.items())
    ]
    candidate_win_rate = candidate_wins / max(1, games)
    minimum_row_win_rate = min(row_win_rates, default=0.0)
    minimum_candidate_deck_win_rate = min((row["winRate"] for row in per_candidate), default=0.0)
    average_threshold_met = candidate_win_rate >= float(pass_threshold)
    passed = (
        average_threshold_met
        and not zero_rows
        and errors == 0
        and timeout_count == 0
    )
    return {
        "threshold": float(pass_threshold),
        "passed": passed,
        "averageThresholdMet": average_threshold_met,
        "qualityTier": _deck_set_quality_tier(candidate_win_rate),
        "candidateWins": candidate_wins,
        "referenceWins": reference_wins,
        "ties": ties,
        "games": games,
        "candidateWinRate": candidate_win_rate,
        "p1WinRate": int(seat_stats["P1"]["wins"]) / max(1, int(seat_stats["P1"]["games"])),
        "p2WinRate": int(seat_stats["P2"]["wins"]) / max(1, int(seat_stats["P2"]["games"])),
        "minimumRowWinRate": minimum_row_win_rate,
        "minimumCandidateDeckWinRate": minimum_candidate_deck_win_rate,
        "zeroRowCount": len(zero_rows),
        "zeroRows": zero_rows,
        "timeoutCount": timeout_count,
        "errorCount": errors,
        "perCandidateDeck": per_candidate,
        "perReferenceDeck": per_reference,
    }


def _deck_set_quality_tier(candidate_win_rate: float) -> str:
    if candidate_win_rate >= 0.70:
        return "strong"
    if candidate_win_rate >= 0.60:
        return "good"
    if candidate_win_rate >= 0.50:
        return "competitive"
    return "behind"


def _evaluate_difficulty_matchup(
    *,
    model_kind: str,
    opponent_kind: str,
    model_side: str,
    episodes: int,
    seed: int,
    normal_model_path: str | Path | None,
    deep_model_path: str | Path | None,
    model_deep_model_path: str | Path | None = None,
    opponent_deep_model_path: str | Path | None = None,
    allow_model_unpromoted_public_deep_v2: bool = False,
    allow_opponent_unpromoted_public_deep_v2: bool = False,
    model_runtime_prior_weights: dict[str, float] | None = None,
    opponent_runtime_prior_weights: dict[str, float] | None = None,
    data_root: str | Path | None,
    model_deck: Any | None = None,
    opponent_deck: Any | None = None,
    policy_template_cache: dict[str, dict[str, Any]] | None = None,
    max_turns: int = 30,
    max_actions: int = 500,
    record_transition_choice_audits: bool = False,
    transition_choice_audit_limit: int = 20,
    transition_choice_audit_changed_only: bool = False,
    profile_runtime: bool = False,
    model_action_set_recorder: Any | None = None,
) -> dict[str, Any]:
    results = {"played": 0, "model": 0, "opponent": 0, "tie": 0, "errors": 0}
    turns_total = 0
    limited_games = 0
    model_timeouts = 0
    opponent_timeouts = 0
    transition_stats = _transition_evaluator_runtime_stats(None)
    bounded_mcts_planner_stats = _bounded_mcts_planner_runtime_stats(None)
    action_set_pruning_stats = _action_set_pruning_runtime_stats(None)
    choice_decision_audits: list[dict[str, Any]] = []
    transition_choice_audits: list[dict[str, Any]] = []
    transition_choice_decision_audits: list[dict[str, Any]] = []
    transition_choice_audit_limit = max(0, int(transition_choice_audit_limit))
    policy_template_cache = policy_template_cache if policy_template_cache is not None else {}
    runtime_profile = RuntimeProfile() if profile_runtime else None
    model_template = _cached_policy_template(
        model_kind,
        seed=seed + 17,
        normal_model_path=normal_model_path,
        deep_model_path=model_deep_model_path or deep_model_path,
        allow_unpromoted_public_deep_v2=allow_model_unpromoted_public_deep_v2,
        runtime_prior_weights=model_runtime_prior_weights,
        data_root=data_root,
        cache=policy_template_cache,
    )
    opponent_template = _cached_policy_template(
        opponent_kind,
        seed=seed + 37,
        normal_model_path=normal_model_path,
        deep_model_path=opponent_deep_model_path or deep_model_path,
        allow_unpromoted_public_deep_v2=allow_opponent_unpromoted_public_deep_v2,
        runtime_prior_weights=opponent_runtime_prior_weights,
        data_root=data_root,
        cache=policy_template_cache,
    )
    total_span = runtime_profile.span("total") if runtime_profile is not None else nullcontext()
    with total_span:
        for index in range(episodes):
            run_seed = seed + index
            model_policy_seed = run_seed + 17
            opponent_policy_seed = run_seed + 37
            _begin_action_set_recorder_replay_context(
                model_action_set_recorder,
                episode_index=index,
                run_seed=run_seed,
                model_policy_seed=model_policy_seed,
                opponent_policy_seed=opponent_policy_seed,
            )
            runtime_policy_kwargs = (
                {"runtime_profiler": runtime_profile}
                if runtime_profile is not None
                else {}
            )
            if record_transition_choice_audits:
                model_policy = _policy_from_template(
                    model_template,
                    model_policy_seed,
                    record_choice_audits=True,
                    choice_audit_limit=transition_choice_audit_limit,
                    choice_audit_changed_only=transition_choice_audit_changed_only,
                    action_set_recorder=model_action_set_recorder,
                    **runtime_policy_kwargs,
                )
            else:
                model_policy = _policy_from_template(
                    model_template,
                    model_policy_seed,
                    action_set_recorder=model_action_set_recorder,
                    **runtime_policy_kwargs,
                )
            opponent_policy = _policy_from_template(
                opponent_template,
                opponent_policy_seed,
                **runtime_policy_kwargs,
            )
            p1_policy, p2_policy = (
                (model_policy, opponent_policy)
                if model_side == "P1"
                else (opponent_policy, model_policy)
            )
            p1_deck = model_deck if model_side == "P1" else opponent_deck
            p2_deck = opponent_deck if model_side == "P1" else model_deck
            results["played"] += 1
            episode_winner_for_audit = "error"
            try:
                winner, turns, limited, limited_side = _play_difficulty_game_with_policy(
                    run_seed,
                    p1_policy=p1_policy,
                    p2_policy=p2_policy,
                    enable_observed_opponent_features=(
                        bool(model_template.get("usesObservedOpponentFeatures"))
                        or bool(opponent_template.get("usesObservedOpponentFeatures"))
                    ),
                    p1_recipe=_deck_recipe_or_none(p1_deck),
                    p2_recipe=_deck_recipe_or_none(p2_deck),
                    p1_forces=_deck_forces_or_none(p1_deck),
                    p2_forces=_deck_forces_or_none(p2_deck),
                    max_turns=max_turns,
                    max_actions=max_actions,
                    runtime_profiler=runtime_profile,
                )
                turns_total += turns
                if limited:
                    limited_games += 1
                    if limited_side == model_side:
                        model_timeouts += 1
                        winner = "P1" if model_side == "P2" else "P2"
                    elif limited_side in {"P1", "P2"}:
                        opponent_timeouts += 1
                        winner = model_side
                episode_winner_for_audit = str(winner)
                if winner == "tie":
                    results["tie"] += 1
                elif winner == model_side:
                    results["model"] += 1
                else:
                    results["opponent"] += 1
            except Exception:
                results["errors"] += 1
                episode_winner_for_audit = "error"
            episode_transition_stats = _transition_evaluator_runtime_stats(model_policy)
            for key, value in episode_transition_stats.items():
                if isinstance(value, dict):
                    target_counts = transition_stats.setdefault(key, {})
                    if not isinstance(target_counts, dict):
                        target_counts = {}
                        transition_stats[key] = target_counts
                    for item_key, item_value in value.items():
                        target_counts[str(item_key)] = int(target_counts.get(str(item_key), 0) or 0) + int(item_value)
                elif isinstance(value, float):
                    transition_stats[key] = float(transition_stats.get(key, 0.0) or 0.0) + float(value)
                else:
                    transition_stats[key] = int(transition_stats.get(key, 0) or 0) + int(value)
            episode_bounded_mcts_planner_stats = _bounded_mcts_planner_runtime_stats(model_policy)
            for key, value in episode_bounded_mcts_planner_stats.items():
                bounded_mcts_planner_stats[key] = (
                    int(bounded_mcts_planner_stats.get(key, 0) or 0) + int(value)
                )
            episode_action_set_pruning_stats = _action_set_pruning_runtime_stats(model_policy)
            for key, value in episode_action_set_pruning_stats.items():
                action_set_pruning_stats[key] = (
                    int(action_set_pruning_stats.get(key, 0) or 0) + int(value)
                )
            if record_transition_choice_audits and len(transition_choice_decision_audits) < transition_choice_audit_limit:
                remaining_raw_decision_count = transition_choice_audit_limit - len(choice_decision_audits)
                for audit in _choice_decision_audits(model_policy, limit=remaining_raw_decision_count):
                    audit.update({
                        "episodeIndex": index,
                        "runSeed": run_seed,
                        "modelPolicySeed": model_policy_seed,
                        "opponentPolicySeed": opponent_policy_seed,
                        "winner": episode_winner_for_audit,
                        "modelWon": episode_winner_for_audit == model_side,
                    })
                    choice_decision_audits.append(audit)
                remaining_decision_count = transition_choice_audit_limit - len(transition_choice_decision_audits)
                for audit in _transition_choice_decision_audits(model_policy, limit=remaining_decision_count):
                    audit.update({
                        "episodeIndex": index,
                        "runSeed": run_seed,
                        "modelPolicySeed": model_policy_seed,
                        "opponentPolicySeed": opponent_policy_seed,
                        "winner": episode_winner_for_audit,
                        "modelWon": episode_winner_for_audit == model_side,
                    })
                    transition_choice_decision_audits.append(audit)
            if record_transition_choice_audits and len(transition_choice_audits) < transition_choice_audit_limit:
                remaining_audit_count = transition_choice_audit_limit - len(transition_choice_audits)
                for audit in _transition_choice_change_audits(model_policy, limit=remaining_audit_count):
                    audit.update({
                        "episodeIndex": index,
                        "runSeed": run_seed,
                        "modelPolicySeed": model_policy_seed,
                        "opponentPolicySeed": opponent_policy_seed,
                        "winner": episode_winner_for_audit,
                        "modelWon": episode_winner_for_audit == model_side,
                    })
                    transition_choice_audits.append(audit)

    completed = max(1, results["model"] + results["opponent"] + results["tie"])
    row = {
        "modelKind": model_kind,
        "opponentKind": opponent_kind,
        "modelResolvedKind": model_template["resolvedKind"],
        "opponentResolvedKind": opponent_template["resolvedKind"],
        "modelCheckpointPath": _path_or_none(model_template["checkpointPath"]),
        "opponentCheckpointPath": _path_or_none(opponent_template["checkpointPath"]),
        "modelRuntimePriorWeights": dict(model_runtime_prior_weights or {}),
        "opponentRuntimePriorWeights": dict(opponent_runtime_prior_weights or {}),
        "modelDeckId": _deck_id_or_none(model_deck),
        "modelDeckName": _deck_name_or_none(model_deck),
        "modelForces": _deck_forces_or_empty(model_deck),
        "opponentDeckId": _deck_id_or_none(opponent_deck),
        "opponentDeckName": _deck_name_or_none(opponent_deck),
        "opponentForces": _deck_forces_or_empty(opponent_deck),
        "modelSide": model_side,
        "seed": seed,
        "episodes": episodes,
        "maxTurns": max_turns,
        "maxActions": max_actions,
        "limitedGames": limited_games,
        "modelTimeouts": model_timeouts,
        "opponentTimeouts": opponent_timeouts,
        "results": results,
        "winRate": results["model"] / completed,
        "averageTurns": turns_total / completed,
    }
    row.update({f"model{key[0].upper()}{key[1:]}": value for key, value in transition_stats.items()})
    row.update({f"model{key[0].upper()}{key[1:]}": value for key, value in bounded_mcts_planner_stats.items()})
    row.update({f"model{key[0].upper()}{key[1:]}": value for key, value in action_set_pruning_stats.items()})
    if runtime_profile is not None:
        runtime_profile.increment(
            "boundedMctsDecisions",
            int(bounded_mcts_planner_stats.get("boundedMctsPlannerDecisions", 0) or 0),
        )
        runtime_profile.increment(
            "transitionEvaluatorCalls",
            int(transition_stats.get("transitionEvaluatorCalls", 0) or 0),
        )
        row["runtimeProfile"] = runtime_profile.to_report(
            timeouts=model_timeouts + opponent_timeouts,
            errors=results["errors"],
        )
    if record_transition_choice_audits:
        raw_decision_kind_pairs = Counter(
            str(audit.get("kindPair", "unknown"))
            for audit in choice_decision_audits
        )
        kind_pairs = Counter(str(audit.get("kindPair", "unknown")) for audit in transition_choice_audits)
        decision_kind_pairs = Counter(
            str(audit.get("kindPair", "unknown"))
            for audit in transition_choice_decision_audits
        )
        row.update({
            "modelChoiceDecisionAuditCount": len(choice_decision_audits),
            "modelChoiceDecisionKindPairs": dict(sorted(raw_decision_kind_pairs.items())),
            "modelChoiceDecisionAudits": choice_decision_audits,
            "modelTransitionChoiceAuditCount": len(transition_choice_audits),
            "modelTransitionChoiceKindPairs": dict(sorted(kind_pairs.items())),
            "modelTransitionChoiceAudits": transition_choice_audits,
            "modelTransitionChoiceDecisionAuditCount": len(transition_choice_decision_audits),
            "modelTransitionChoiceDecisionKindPairs": dict(sorted(decision_kind_pairs.items())),
            "modelTransitionChoiceDecisionAudits": transition_choice_decision_audits,
        })
    return row


def _begin_action_set_recorder_replay_context(
    recorder: Any | None,
    *,
    episode_index: int,
    run_seed: int,
    model_policy_seed: int,
    opponent_policy_seed: int,
) -> None:
    begin = getattr(recorder, "begin_replay_context", None)
    if not callable(begin):
        return
    begin(
        {
            "episodeIndex": int(episode_index),
            "runSeed": int(run_seed),
            "modelPolicySeed": int(model_policy_seed),
            "opponentPolicySeed": int(opponent_policy_seed),
        }
    )


def _transition_evaluator_runtime_stats(policy: Any) -> dict[str, int | float | dict[str, int]]:
    float_keys = {
        "transitionEvaluatorRawSpreadSum",
        "transitionEvaluatorNoChangeBaselineMarginSum",
        "transitionEvaluatorNoChangeFinalMarginSum",
    }
    zeros = {
        "transitionEvaluatorCalls": 0,
        "transitionEvaluatorDecisions": 0,
        "transitionEvaluatorAppliedDecisions": 0,
        "transitionEvaluatorAbstentions": 0,
        "transitionEvaluatorChoiceChanges": 0,
        "transitionEvaluatorRawSpreadSum": 0.0,
        "transitionEvaluatorFeatureNoveltyAbstentionCalls": 0,
        "transitionEvaluatorAllNoveltyDecisions": 0,
        "transitionEvaluatorNoChangeMarginCount": 0,
        "transitionEvaluatorNoChangeBaselineMarginSum": 0.0,
        "transitionEvaluatorNoChangeFinalMarginSum": 0.0,
        "transitionEvaluatorUnknownFeatureCounts": {},
    }
    if policy is None or not hasattr(policy, "transition_evaluator_runtime_stats"):
        return zeros
    try:
        raw = dict(policy.transition_evaluator_runtime_stats())
    except Exception:
        return zeros
    return {
        key: (
            {str(item_key): int(item_value) for item_key, item_value in dict(raw.get(key) or {}).items()}
            if key == "transitionEvaluatorUnknownFeatureCounts"
            else (
                float(raw.get(key, 0.0) or 0.0)
                if key in float_keys
                else int(raw.get(key, 0) or 0)
            )
        )
        for key in zeros
    }


def _bounded_mcts_planner_runtime_stats(policy: Any) -> dict[str, int]:
    zeros = {
        "boundedMctsPlannerDecisions": 0,
        "boundedMctsPlannerChoiceChanges": 0,
        "boundedMctsPlannerSimulations": 0,
        "boundedMctsPlannerFallbacks": 0,
    }
    if policy is None or not hasattr(policy, "bounded_mcts_planner_runtime_stats"):
        return zeros
    try:
        raw = dict(policy.bounded_mcts_planner_runtime_stats())
    except Exception:
        return zeros
    return {
        key: int(raw.get(key, 0) or 0)
        for key in zeros
    }


def _action_set_pruning_runtime_stats(policy: Any) -> dict[str, int]:
    zeros = {
        "actionSetPruneDecisions": 0,
        "actionSetPruneInputActions": 0,
        "actionSetPruneKeptActions": 0,
        "actionSetPruneModelRescues": 0,
        "actionSetPruneErrors": 0,
        "actionSetSkipMctsDecisions": 0,
        "actionSetFastSelectDecisions": 0,
        "actionSetTakeoverDecisions": 0,
    }
    if policy is None or not hasattr(policy, "action_set_pruning_runtime_stats"):
        return zeros
    try:
        raw = dict(policy.action_set_pruning_runtime_stats())
    except Exception:
        return zeros
    return {
        key: int(raw.get(key, 0) or 0)
        for key in zeros
    }


def _transition_choice_change_audits(policy: Any, *, limit: int = 20) -> list[dict[str, Any]]:
    return [
        audit
        for audit in _transition_choice_decision_audits(policy, limit=limit, include_no_change=False)
    ]


def _transition_choice_decision_audits(
    policy: Any,
    *,
    limit: int = 20,
    include_no_change: bool = True,
) -> list[dict[str, Any]]:
    return _choice_decision_audits(
        policy,
        limit=limit,
        include_no_change=include_no_change,
        require_runtime_evaluation=True,
    )


def _choice_decision_audits(
    policy: Any,
    *,
    limit: int = 20,
    include_no_change: bool = True,
    require_runtime_evaluation: bool = False,
) -> list[dict[str, Any]]:
    recorder = getattr(policy, "recorder", None)
    raw_audits = list(getattr(recorder, "choice_score_audits", []) or [])
    out: list[dict[str, Any]] = []
    for raw_audit in raw_audits:
        if len(out) >= max(0, int(limit)):
            break
        audit = dict(raw_audit or {})
        choices = [dict(choice or {}) for choice in list(audit.get("choices") or [])]
        if len(choices) < 2:
            continue
        selected_index = _bounded_choice_index(audit.get("selectedIndex"), choices)
        if selected_index is None:
            continue
        scored_without_transition = [
            _choice_score_without_transition(choice)
            for choice in choices
        ]
        baseline_index = max(
            range(len(choices)),
            key=lambda index: (scored_without_transition[index], -index),
        )
        selected = choices[selected_index]
        baseline = choices[baseline_index]
        selected_transition = _choice_transition_value(selected)
        baseline_transition = _choice_transition_value(baseline)
        transition_was_evaluated = any(
            _choice_transition_value(choice) != 0.0
            or _choice_transition_raw_value(choice) != 0.0
            or float(dict(choice.get("breakdown") or {}).get("transitionEvaluatorAbstained", 0.0) or 0.0) > 0.0
            for choice in choices
        )
        bounded_mcts_was_evaluated = any(
            _choice_bounded_mcts_was_evaluated(choice)
            for choice in choices
        )
        if bounded_mcts_was_evaluated:
            scored_without_transition_and_bounded_mcts = [
                _choice_score_without_transition_and_bounded_mcts(choice)
                for choice in choices
            ]
            baseline_index = max(
                range(len(choices)),
                key=lambda index: (scored_without_transition_and_bounded_mcts[index], -index),
            )
            baseline = choices[baseline_index]
            baseline_transition = _choice_transition_value(baseline)
        else:
            scored_without_transition_and_bounded_mcts = list(scored_without_transition)
        if require_runtime_evaluation and not transition_was_evaluated and not bounded_mcts_was_evaluated:
            continue
        if baseline_index == selected_index and not include_no_change:
            continue
        selected_summary = _choice_audit_action_summary(selected)
        baseline_summary = _choice_audit_action_summary(baseline)
        transition_baseline_index = max(
            range(len(choices)),
            key=lambda index: (scored_without_transition[index], -index),
        )
        decision_audit = {
            "source": str(audit.get("source", "")),
            "choiceAuditIndex": int(audit.get("choiceAuditIndex", -1)),
            "sourceChoiceAuditIndex": int(audit.get("sourceChoiceAuditIndex", -1)),
            "selectedIndex": int(selected_index),
            "baselineIndex": int(baseline_index),
            "changedByTransition": bool(
                transition_was_evaluated and transition_baseline_index != selected_index
            ),
            "changedByBoundedMcts": bool(
                bounded_mcts_was_evaluated and baseline_index != selected_index
            ),
            "kindPair": (
                f"{baseline_summary['actionKind']}->{selected_summary['actionKind']}"
            ),
            "selectedAction": selected_summary,
            "baselineAction": baseline_summary,
            "selectedScore": _choice_score(selected),
            "baselineScore": _choice_score(baseline),
            "selectedScoreWithoutTransition": float(scored_without_transition[selected_index]),
            "baselineScoreWithoutTransition": float(scored_without_transition[baseline_index]),
            "selectedScoreWithoutTransitionAndBoundedMcts": float(
                scored_without_transition_and_bounded_mcts[selected_index]
            ),
            "baselineScoreWithoutTransitionAndBoundedMcts": float(
                scored_without_transition_and_bounded_mcts[baseline_index]
            ),
            "selectedTransitionEvaluator": selected_transition,
            "baselineTransitionEvaluator": baseline_transition,
            "selectedBoundedMctsPlanner": _choice_bounded_mcts_value(selected),
            "baselineBoundedMctsPlanner": _choice_bounded_mcts_value(baseline),
            "scoreDeltaWithTransition": float(_choice_score(selected) - _choice_score(baseline)),
            "scoreDeltaWithoutTransition": float(
                scored_without_transition[selected_index] - scored_without_transition[baseline_index]
            ),
            "scoreDeltaWithoutTransitionAndBoundedMcts": float(
                scored_without_transition_and_bounded_mcts[selected_index]
                - scored_without_transition_and_bounded_mcts[baseline_index]
            ),
            "topChoices": [
                _choice_audit_action_summary(choice)
                for choice in choices[: min(5, len(choices))]
            ],
        }
        learner_firstness = str(audit.get("learnerFirstness") or "").strip().lower()
        if learner_firstness in {"first", "second"}:
            decision_audit["learnerFirstness"] = learner_firstness
        before_state_features = audit.get("beforeStateFeatures")
        if isinstance(before_state_features, dict):
            decision_audit["beforeStateFeatures"] = dict(before_state_features)
        out.append(decision_audit)
    return out


def _bounded_choice_index(value: Any, choices: list[dict[str, Any]]) -> int | None:
    try:
        index = int(value)
    except Exception:
        return None
    if index < 0 or index >= len(choices):
        return None
    return index


def _choice_score(choice: dict[str, Any]) -> float:
    if "score" in choice:
        return float(choice.get("score", 0.0) or 0.0)
    breakdown = dict(choice.get("breakdown") or {})
    return float(breakdown.get("total", 0.0) or 0.0)


def _choice_transition_value(choice: dict[str, Any]) -> float:
    breakdown = dict(choice.get("breakdown") or {})
    return float(breakdown.get("transitionEvaluator", 0.0) or 0.0)


def _choice_transition_raw_value(choice: dict[str, Any]) -> float:
    breakdown = dict(choice.get("breakdown") or {})
    return float(breakdown.get("transitionEvaluatorRaw", 0.0) or 0.0)


def _choice_bounded_mcts_value(choice: dict[str, Any]) -> float:
    breakdown = dict(choice.get("breakdown") or {})
    return float(breakdown.get("boundedMctsPlanner", 0.0) or 0.0)


def _choice_bounded_mcts_was_evaluated(choice: dict[str, Any]) -> bool:
    breakdown = dict(choice.get("breakdown") or {})
    for key in (
        "boundedMctsPlannerCandidate",
        "boundedMctsPlannerPrior",
        "boundedMctsPlannerVisits",
        "boundedMctsPlannerQ",
        "boundedMctsPlanner",
        "boundedMctsPlannerBaselineSelected",
        "boundedMctsPlannerSelected",
        "boundedMctsPlannerAbstained",
    ):
        try:
            if float(breakdown.get(key, 0.0) or 0.0) != 0.0:
                return True
        except (TypeError, ValueError):
            continue
    return False


def _choice_score_without_transition(choice: dict[str, Any]) -> float:
    return float(_choice_score(choice) - _choice_transition_value(choice))


def _choice_score_without_transition_and_bounded_mcts(choice: dict[str, Any]) -> float:
    return float(_choice_score_without_transition(choice) - _choice_bounded_mcts_value(choice))


def _choice_breakdown_summary(choice: dict[str, Any]) -> dict[str, float]:
    out: dict[str, float] = {}
    for key, value in dict(choice.get("breakdown") or {}).items():
        try:
            out[str(key)] = float(value)
        except (TypeError, ValueError):
            continue
    return out


def _choice_audit_action_summary(choice: dict[str, Any]) -> dict[str, Any]:
    summary = {
        "label": str(choice.get("label", "")),
        "actionKind": str(choice.get("actionKind", "unknown")),
        "actionPayload": dict(choice.get("actionPayload") or {}),
        "score": _choice_score(choice),
        "scoreWithoutTransition": _choice_score_without_transition(choice),
        "scoreWithoutTransitionAndBoundedMcts": _choice_score_without_transition_and_bounded_mcts(choice),
        "breakdown": _choice_breakdown_summary(choice),
        "transitionEvaluator": _choice_transition_value(choice),
        "transitionEvaluatorRaw": _choice_transition_raw_value(choice),
        "boundedMctsPlanner": _choice_bounded_mcts_value(choice),
        "transitionEvaluatorAbstained": float(
            dict(choice.get("breakdown") or {}).get("transitionEvaluatorAbstained", 0.0) or 0.0
        ),
        "lookahead": float(dict(choice.get("breakdown") or {}).get("lookahead", 0.0) or 0.0),
        "tags": list(choice.get("tags") or []),
    }
    features = choice.get("features")
    if isinstance(features, dict):
        feature_summary: dict[str, float] = {}
        for key, value in features.items():
            try:
                feature_summary[str(key)] = float(value)
            except (TypeError, ValueError):
                continue
        summary["features"] = feature_summary
    return summary


def _play_difficulty_game_with_policy(
    seed: int,
    *,
    p1_policy: Any,
    p2_policy: Any,
    enable_observed_opponent_features: bool = False,
    p1_recipe: dict[str, int] | None = None,
    p2_recipe: dict[str, int] | None = None,
    p1_forces: list[str] | None = None,
    p2_forces: list[str] | None = None,
    max_turns: int = 30,
    max_actions: int = 500,
    runtime_profiler: RuntimeProfile | None = None,
) -> tuple[str, int, bool, str | None]:
    engine, _ = _setup_game(
        seed,
        p1_policy,
        p2_policy,
        p1_recipe=p1_recipe,
        p2_recipe=p2_recipe,
        p1_forces=p1_forces,
        p2_forces=p2_forces,
    )
    engine.enable_observed_opponent_features = bool(enable_observed_opponent_features)
    actions_taken = 0
    try:
        env_span = runtime_profiler.span("env") if runtime_profiler is not None else nullcontext()
        with env_span:
            engine.begin_turn()
        while True:
            if engine.state.turn > max_turns or actions_taken >= max_actions:
                return "tie", engine.state.turn, True, engine.state.active.name
            action = engine.policy_for(engine.state.active).choose(engine)
            actions_taken += 1
            if runtime_profiler is not None:
                runtime_profiler.increment("actions", 1)
            env_span = runtime_profiler.span("env") if runtime_profiler is not None else nullcontext()
            with env_span:
                engine.apply(action)
    except GameOver as game_over:
        return game_over.winner.name if game_over.winner else "tie", engine.state.turn, False, None


def _cached_policy_template(
    kind: str,
    *,
    seed: int,
    normal_model_path: str | Path | None,
    deep_model_path: str | Path | None,
    allow_unpromoted_public_deep_v2: bool = False,
    runtime_prior_weights: dict[str, float] | None = None,
    data_root: str | Path | None,
    cache: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    key = "|".join((
        str(kind).strip().lower(),
        f"normal={Path(normal_model_path) if normal_model_path is not None else ''}",
        f"deep={Path(deep_model_path) if deep_model_path is not None else ''}",
        f"allowV2={bool(allow_unpromoted_public_deep_v2)}",
        f"priors={json.dumps(runtime_prior_weights or {}, sort_keys=True)}",
    ))
    if key not in cache:
        cache[key] = _policy_template_for_kind(
            str(kind).strip().lower(),
            seed=seed,
            normal_model_path=normal_model_path,
            deep_model_path=deep_model_path,
            allow_unpromoted_public_deep_v2=allow_unpromoted_public_deep_v2,
            runtime_prior_weights=runtime_prior_weights,
            data_root=data_root,
        )
    return cache[key]


def _policy_template_for_kind(
    kind: str,
    *,
    seed: int,
    normal_model_path: str | Path | None,
    deep_model_path: str | Path | None,
    allow_unpromoted_public_deep_v2: bool = False,
    runtime_prior_weights: dict[str, float] | None = None,
    data_root: str | Path | None,
) -> dict[str, Any]:
    resolved: ResolvedBattlePolicy = resolve_battle_policy(
        kind,
        seed=seed,
        normal_model_path=normal_model_path,
        deep_model_path=deep_model_path,
        data_root=data_root,
        allow_unpromoted_public_deep_v2=allow_unpromoted_public_deep_v2,
        runtime_prior_weights=runtime_prior_weights,
    )
    return {
        "requestedKind": resolved.requested_kind,
        "resolvedKind": resolved.resolved_kind,
        "checkpointPath": resolved.checkpoint_path,
        "model": getattr(resolved.policy, "model", None),
        "runtimePriorWeights": dict(runtime_prior_weights or {}),
        "usesObservedOpponentFeatures": model_uses_observed_opponent_features(getattr(resolved.policy, "model", None)),
    }


def _policy_from_template(
    template: dict[str, Any],
    seed: int,
    *,
    record_choice_audits: bool = False,
    choice_audit_limit: int | None = None,
    choice_audit_changed_only: bool = False,
    runtime_profiler: RuntimeProfile | None = None,
    action_set_recorder: Any | None = None,
) -> Any:
    checkpoint_path = template.get("checkpointPath")
    if checkpoint_path is None:
        return GreedyLegalPolicy(random.Random(seed))
    path = Path(checkpoint_path)
    model = template.get("model")
    if model is None:
        if path.suffix.lower() == ".pt":
            from zz.deep_rl import TorchActionValueModel

            model = TorchActionValueModel.load(path)
        else:
            model = LinearQModel.load(path)
    if path.suffix.lower() == ".pt":
        policy_kwargs = {
            "lookahead_weight": DEEP_LOOKAHEAD_WEIGHT,
            "max_lookahead_actions": DEEP_MAX_LOOKAHEAD_ACTIONS,
            "lookahead_depth": DEEP_LOOKAHEAD_DEPTH,
            "lookahead_branch_width": DEEP_LOOKAHEAD_BRANCH_WIDTH,
            "lookahead_key_decisions_only": DEEP_LOOKAHEAD_KEY_DECISIONS_ONLY,
            "humanlike_prior_weight": DEEP_HUMANLIKE_PRIOR_WEIGHT,
        }
        policy_kwargs.update(_runtime_prior_kwargs(dict(template.get("runtimePriorWeights") or {})))
        return LookaheadRLPolicy(
            model=model,
            rng=random.Random(seed),
            epsilon=0.0,
            recorder=(
                EpisodeRecorder(
                    record_choice_audits=True,
                    max_choice_audits=choice_audit_limit,
                    changed_choice_audits_only=choice_audit_changed_only,
                )
                if record_choice_audits
                else None
            ),
            **policy_kwargs,
            runtime_profiler=runtime_profiler,
            action_set_recorder=action_set_recorder,
        )
    return LookaheadRLPolicy(
        model=model,
        rng=random.Random(seed),
        epsilon=0.0,
        recorder=(
            EpisodeRecorder(
                record_choice_audits=True,
                max_choice_audits=choice_audit_limit,
                changed_choice_audits_only=choice_audit_changed_only,
            )
            if record_choice_audits
            else None
        ),
        **_runtime_prior_kwargs(dict(template.get("runtimePriorWeights") or {})),
        runtime_profiler=runtime_profiler,
        action_set_recorder=action_set_recorder,
    )


def select_recommended_difficulty_champion(
    report: dict[str, Any],
    *,
    min_deep_margin: float = 0.0,
    min_deep_floor: float = 0.50,
) -> dict[str, Any]:
    rows = list(report.get("rows") or [])
    deep_rows = [row for row in rows if row.get("modelKind") == "deep"]
    normal_rows = [row for row in rows if row.get("modelKind") == "normal"]
    deep_available = any(row.get("modelResolvedKind") == "deep" for row in deep_rows)
    normal_available = any(row.get("modelResolvedKind") == "normal" for row in normal_rows)
    deep_average = _average_win_rate(deep_rows)
    normal_average = _average_win_rate(normal_rows)
    deep_minimum = min((float(row.get("winRate", 0.0)) for row in deep_rows), default=0.0)
    normal_minimum = min((float(row.get("winRate", 0.0)) for row in normal_rows), default=0.0)
    if deep_available and deep_average >= normal_average + min_deep_margin and deep_minimum >= min_deep_floor:
        difficulty = "deep"
        reason = "deep cleared the normal comparison gate"
    elif normal_available:
        difficulty = "normal"
        reason = "normal remains the safer promoted difficulty"
    else:
        difficulty = "easy"
        reason = "no promoted public checkpoint was available"
    return {
        "difficulty": difficulty,
        "reason": reason,
        "deepAverageWinRate": deep_average,
        "deepMinimumWinRate": deep_minimum,
        "normalAverageWinRate": normal_average,
        "normalMinimumWinRate": normal_minimum,
        "minDeepMargin": min_deep_margin,
        "minDeepFloor": min_deep_floor,
    }


def _average_win_rate(rows: list[dict[str, Any]]) -> float:
    return sum(float(row.get("winRate", 0.0)) for row in rows) / max(1, len(rows))


def _difficulty_deck_pairs(
    benchmark_decks: list[Any] | tuple[Any, ...] | None,
    *,
    deck_root: str | Path | None,
    max_deck_pairs: int | None,
) -> list[tuple[Any | None, Any | None]]:
    decks = list(benchmark_decks or [])
    if not decks and deck_root is not None:
        from zz.deck_ai import load_benchmark_decks

        decks = load_benchmark_decks(deck_root)
    if not decks:
        return [(None, None)]
    if len(decks) == 1:
        pairs = [(decks[0], decks[0])]
    else:
        pairs = [(left, right) for left in decks for right in decks if _deck_id_or_none(left) != _deck_id_or_none(right)]
    if max_deck_pairs is not None:
        return pairs[:max(1, int(max_deck_pairs))]
    return pairs


def _load_player_gate_decks(deck_root: str | Path | None) -> list[Any]:
    from zz.ai_deck_analysis import load_saved_decks
    from zz.deck_ai import load_benchmark_decks

    decks = load_saved_decks(deck_root)
    if decks:
        return decks
    return load_benchmark_decks(deck_root)


def _load_old_top10_gate_decks(top_suite_path: str | Path) -> list[Any]:
    from zz.deck_ai import load_top_suite_decks

    return load_top_suite_decks(top_suite_path)


def _limit_decks(decks: list[Any], max_decks: int | None) -> list[Any]:
    if max_decks is None:
        return decks
    return decks[: max(0, int(max_decks))]


def _deck_provenance(deck: Any | None, default: str) -> str:
    if deck is None:
        return default
    if isinstance(deck, dict):
        return str(deck.get("provenance") or default)
    return str(getattr(deck, "provenance", default))


def _force_preference_from_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    stats: dict[tuple[str, ...], dict[str, Any]] = {}
    for row in rows:
        force_pair = tuple(str(force_id) for force_id in row.get("modelForces") or [])
        if not force_pair:
            continue
        entry = stats.setdefault(force_pair, {"wins": 0, "games": 0, "rows": 0})
        results = row.get("results") or {}
        games = int(results.get("model", 0)) + int(results.get("opponent", 0)) + int(results.get("tie", 0))
        entry["wins"] += int(results.get("model", 0))
        entry["games"] += games
        entry["rows"] += 1
    preferences = [
        {
            "forcePair": list(force_pair),
            "wins": int(entry["wins"]),
            "games": int(entry["games"]),
            "rows": int(entry["rows"]),
            "winRate": int(entry["wins"]) / max(1, int(entry["games"])),
        }
        for force_pair, entry in stats.items()
    ]
    preferences.sort(key=lambda item: (item["winRate"], item["games"], item["rows"]), reverse=True)
    return preferences


def _deck_id_or_none(deck: Any | None) -> str | None:
    if deck is None:
        return None
    if isinstance(deck, dict):
        return str(deck.get("id") or "deck")
    return str(getattr(deck, "id", "deck"))


def _deck_name_or_none(deck: Any | None) -> str | None:
    if deck is None:
        return None
    if isinstance(deck, dict):
        return str(deck.get("name") or _deck_id_or_none(deck))
    return str(getattr(deck, "name", _deck_id_or_none(deck)))


def _deck_recipe_or_none(deck: Any | None) -> dict[str, int] | None:
    if deck is None:
        return None
    recipe = deck.get("recipe") if isinstance(deck, dict) else getattr(deck, "recipe")
    return {str(card_id): int(count) for card_id, count in recipe.items()}


def _deck_forces_or_none(deck: Any | None) -> list[str] | None:
    if deck is None:
        return None
    return _deck_forces_or_empty(deck)


def _deck_forces_or_empty(deck: Any | None) -> list[str]:
    if deck is None:
        return []
    forces = deck.get("forces") if isinstance(deck, dict) else getattr(deck, "forces")
    return [str(force_id) for force_id in forces]


def _path_or_none(path: Path | None) -> str | None:
    return None if path is None else str(path)


def _write_json(path: str | Path, report: dict[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=True, indent=2), encoding="utf-8")
