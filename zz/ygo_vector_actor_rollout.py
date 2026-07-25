from __future__ import annotations

import hashlib
import json
import math
import multiprocessing as mp
import queue
import random
import threading
import time
import traceback
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

from zz.action_set_dataset import build_action_set_teacher_row
from zz.action_set_ygo_policy import YgoStyleActionSetPolicyScorer
from zz.current_policy_actor_contract import load_current_policy_actor_artifact
from zz.current_policy_runtime import (
    action_identities_from_row,
    actor_logits_from_runtime_scores,
    masked_argmax_action,
)
from zz.engine import GameOver
from zz.model import Action, Player
from zz.policy_factories import (
    OLD_BASELINE_DEEP_POLICY_ID,
    OLD_BASELINE_EASY_POLICY_ID,
    create_rollout_policy,
)
from zz.rl_ai import _action_set_scorer_json_mapping, target_selection_player_for_context
from zz.rl_training import StateSnapshot, calculate_step_reward, _setup_game
from tools.hidden_multiprocessing_spawn import install_hidden_multiprocessing_spawn


VECTOR_ACTOR_ROLLOUT_VERSION = "ygo_vector_actor_rollout_v1"
VECTOR_ROLLOUT_BACKEND = "persistent_vector_batched_inference"
WORKER_LOCAL_VECTOR_ROLLOUT_BACKEND = "persistent_worker_internal_vectorized_rollout"
CURRENT_POLICY_TRAJECTORY_ROWS_SCHEMA = "current_policy_sampled_trajectory_rows_v1"
FULL_LEGAL_ACTION_VALUE_ROWS_SCHEMA = "snapshot_branch_full_legal_action_value_rows_v1"
DEFAULT_SELFPLAY_GAMES_PER_POOL = 32
DEFAULT_ORIGINAL_GAMES_PER_POOL = 48
DEFAULT_ORIGINAL_OPPONENT_POLICY_IDS = (
    OLD_BASELINE_EASY_POLICY_ID,
    OLD_BASELINE_DEEP_POLICY_ID,
)
DEFAULT_TRAINING_POOL_SCHEDULE = "default"
EASY_TOP10_MATRIX_TRAINING_POOL_SCHEDULE = "selfplay_player_matrix_x3_plus_easy_top10_matrix_v1"
DEFAULT_WORKER_IDLE_TIMEOUT_SECONDS = 60.0
DEFAULT_WORKER_LOCAL_VECTOR_PROCESS_CAP = 16
PERSISTENT_WORKER_RESULT_ROW_CHUNK_SIZE = 512


def _normalise_training_pool_schedule(value: str | None) -> str:
    schedule = str(value or DEFAULT_TRAINING_POOL_SCHEDULE).strip().lower()
    if not schedule or schedule in {"default", "legacy", "original48"}:
        return DEFAULT_TRAINING_POOL_SCHEDULE
    if schedule in {
        "easy_top10_matrix_v1",
        "selfplay_player_matrix_x3_plus_easy_top10_matrix_v1",
    }:
        return EASY_TOP10_MATRIX_TRAINING_POOL_SCHEDULE
    raise ValueError(f"unknown training_pool_schedule={value!r}")


def _worker_idle_timeout_seconds(config: Mapping[str, Any]) -> float:
    return max(1.0, float(config.get("workerIdleTimeoutSeconds", DEFAULT_WORKER_IDLE_TIMEOUT_SECONDS) or DEFAULT_WORKER_IDLE_TIMEOUT_SECONDS))


def _worker_error_is_retryable_idle_timeout(item: Mapping[str, Any]) -> bool:
    text = f"{item.get('error') or ''}\n{item.get('traceback') or ''}"
    return "_queue.Empty" in text or "queue.Empty" in text


def _put_worker_result_chunks(
    output_queue: Any,
    *,
    batch_id: str,
    worker_index: int,
    result: Mapping[str, Any],
    model_load_count: int,
    model_reload_count: int,
    include_game_rows: bool = False,
    row_chunk_size: int = PERSISTENT_WORKER_RESULT_ROW_CHUNK_SIZE,
) -> None:
    chunk_size = max(1, int(row_chunk_size or PERSISTENT_WORKER_RESULT_ROW_CHUNK_SIZE))

    def _put_rows(row_kind: str, rows: Any) -> None:
        if not rows:
            return
        values = rows if isinstance(rows, list) else list(rows)
        for start in range(0, len(values), chunk_size):
            output_queue.put(
                {
                    "kind": "worker_rows",
                    "batchId": str(batch_id),
                    "workerIndex": int(worker_index),
                    "rowKind": str(row_kind),
                    "rows": values[start : start + chunk_size],
                }
            )

    _put_rows("trajectory", result.get("trajectoryRows"))
    _put_rows("bridge", result.get("bridgeRows"))
    if include_game_rows:
        _put_rows("game", result.get("gameRows"))
    summary = {
        key: value
        for key, value in dict(result).items()
        if key not in {"trajectoryRows", "bridgeRows", "gameRows"}
    }
    output_queue.put(
        {
            "kind": "worker_done",
            "batchId": str(batch_id),
            "workerIndex": int(worker_index),
            **summary,
            "modelLoadCount": int(model_load_count),
            "modelReloadCount": int(model_reload_count),
            "modelBroadcastCount": 1,
            "rowTransport": "queue_chunks",
            "rowChunkSize": int(chunk_size),
        }
    )


def _append_worker_result_rows(
    item: Mapping[str, Any],
    *,
    trajectory_rows: list[dict[str, Any]],
    bridge_rows: list[dict[str, Any]],
    game_rows: list[dict[str, Any]] | None = None,
    errors: list[dict[str, Any]] | None = None,
) -> None:
    row_kind = str(item.get("rowKind") or "")
    if row_kind == "trajectory":
        _append_mapping_rows(trajectory_rows, item.get("rows"))
    elif row_kind == "bridge":
        _append_mapping_rows(bridge_rows, item.get("rows"))
    elif row_kind == "game" and game_rows is not None:
        _append_mapping_rows(game_rows, item.get("rows"))
    elif errors is not None:
        errors.append(
            {
                "kind": "worker_error",
                "batchId": str(item.get("batchId") or ""),
                "workerIndex": int(item.get("workerIndex", -1) or -1),
                "error": f"unknown worker row kind: {row_kind}",
            }
        )


def score_decision_batch(
    requests: Sequence[Mapping[str, Any]],
    *,
    scorer: Any,
    actor_policy_id: str,
    rng: random.Random,
    temperature: float = 1.0,
    scorer_batch_size: int = 512,
    selection_mode: str = "sampled_from_logits",
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    materialized = [request for request in requests if isinstance(request, Mapping)]
    if not materialized:
        return [], _batch_stats([])
    rows = [request["row"] for request in materialized]
    scores_by_row = scorer.score_rows_batched(rows, batch_size=max(1, int(scorer_batch_size)))
    if len(scores_by_row) != len(rows):
        raise ValueError("batched scorer returned the wrong number of rows")

    actor_id = str(actor_policy_id or "").strip()
    if not actor_id:
        raise ValueError("actor_policy_id must be non-empty")
    results: list[dict[str, Any]] = []
    for request, row, scores in zip(materialized, rows, scores_by_row, strict=True):
        logits = actor_logits_from_runtime_scores(row, scores)
        legal_mask = [bool(value) for value in list(row.get("legalMask") or row.get("mask_") or [])]
        action_identities = action_identities_from_row(row)
        top = masked_argmax_action(
            logits=logits,
            legal_mask=legal_mask,
            action_identities=action_identities,
            policy_id=actor_id,
        )
        resolved_selection_mode = str(selection_mode or "sampled_from_logits")
        if resolved_selection_mode in {"masked_argmax_action", "argmax", "greedy"}:
            slot = int(top.slot)
            log_prob = _log_prob_for_slot(logits=logits, legal_mask=legal_mask, slot=slot)
        else:
            slot, log_prob = _sample_slot_from_logits(
                logits=logits,
                legal_mask=legal_mask,
                rng=rng,
                temperature=float(temperature),
            )
        old_value: float | None = None
        state_value = getattr(scorer, "state_value", None)
        if callable(state_value):
            try:
                old_value = float(state_value(row))
            except Exception:
                old_value = None
        result = {
            "requestId": str(request.get("requestId") or ""),
            "slot": int(slot),
            "actorActionIdentity": str(action_identities[int(slot)]),
            "actorActionLogProb": float(log_prob),
            "actorLogits": [float(value) for value in logits],
            "actorTopSlot": int(top.slot),
            "actorTopActionIdentity": str(top.action_identity),
            "oldPolicyStateValue": old_value,
        }
        result.update(_runtime_recurrent_hidden_snapshot_payload(scorer, row))
        results.append(result)
    prune_cache = getattr(scorer, "prune_recurrent_runtime_cache", None)
    if callable(prune_cache):
        prune_cache(max_state_sequences=64, clear_row_context=True)
    return results, _batch_stats([len(materialized)])


def _runtime_recurrent_hidden_snapshot_payload(scorer: Any, row: Mapping[str, Any]) -> dict[str, Any]:
    snapshot_fn = getattr(scorer, "runtime_recurrent_hidden_snapshot", None)
    if not callable(snapshot_fn):
        return {}
    try:
        snapshot = snapshot_fn(row)
    except Exception:
        return {}
    if not isinstance(snapshot, Mapping) or not bool(snapshot.get("enabled")):
        return {}

    def float_vector(key: str) -> list[float]:
        values = snapshot.get(key)
        if not isinstance(values, list | tuple):
            return []
        out: list[float] = []
        for value in values:
            parsed = _finite_float_or_none(value)
            if parsed is not None:
                out.append(float(parsed))
        return out

    initial = float_vector("initialHiddenState")
    hidden = float_vector("hiddenState")
    if not initial and not hidden:
        return {}
    payload: dict[str, Any] = {
        "runtimeRecurrentHiddenStateSource": "actor_runtime_scorer",
    }
    sequence_key = str(snapshot.get("sequenceKey") or "").strip()
    row_key = str(snapshot.get("rowKey") or "").strip()
    if sequence_key:
        payload["runtimeRecurrentSequenceKey"] = sequence_key
    if row_key:
        payload["runtimeRecurrentRowKey"] = row_key
    if initial:
        payload["runtimeRecurrentInitialHiddenState"] = initial
    if hidden:
        payload["runtimeRecurrentHiddenState"] = hidden
    return payload


def score_value_batch(
    requests: Sequence[Mapping[str, Any]],
    *,
    scorer: Any,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    materialized = [request for request in requests if isinstance(request, Mapping)]
    results: list[dict[str, Any]] = []
    state_value = getattr(scorer, "state_value", None)
    if not callable(state_value):
        raise ValueError("scorer does not provide state_value")
    for request in materialized:
        row = request["row"]
        results.append(
            {
                "requestId": str(request.get("requestId") or ""),
                "stateValue": float(state_value(row)),
            }
        )
    prune_cache = getattr(scorer, "prune_recurrent_runtime_cache", None)
    if callable(prune_cache):
        prune_cache(max_state_sequences=64, clear_row_context=True)
    return results, _batch_stats([len(materialized)] if materialized else [])


def _request_actor_policy_id(request: Mapping[str, Any], *, default_actor_policy_id: str) -> str:
    row = request.get("row") if isinstance(request.get("row"), Mapping) else {}
    metadata = row.get("metadata") if isinstance(row, Mapping) and isinstance(row.get("metadata"), Mapping) else {}
    for source in (request, row, metadata):
        text = str(source.get("actorPolicyId") or source.get("runtimePolicyId") or "").strip()
        if text:
            return text
    return str(default_actor_policy_id or "").strip()


def _require_actor_scorer_key(actor_policy_id: str, scorer_by_actor_id: Mapping[str, Any]) -> str:
    actor_id = str(actor_policy_id or "").strip()
    if actor_id in scorer_by_actor_id:
        return actor_id
    raise ValueError(f"no vector actor scorer loaded for policy id: {actor_id or '<empty>'}")


def _score_decision_requests_by_actor(
    requests: Sequence[Mapping[str, Any]],
    *,
    scorer_by_actor_id: Mapping[str, Any],
    default_actor_policy_id: str,
    rng: random.Random,
    temperature: float = 1.0,
    scorer_batch_size: int = 512,
    selection_mode: str = "sampled_from_logits",
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    materialized = [request for request in requests if isinstance(request, Mapping)]
    if not materialized:
        return [], _batch_stats([])
    grouped: dict[str, list[tuple[int, Mapping[str, Any]]]] = {}
    for index, request in enumerate(materialized):
        actor_id = _request_actor_policy_id(request, default_actor_policy_id=default_actor_policy_id)
        scorer_key = _require_actor_scorer_key(actor_id, scorer_by_actor_id)
        grouped.setdefault(scorer_key, []).append((int(index), request))

    replies_by_index: dict[int, dict[str, Any]] = {}
    batch_sizes: list[int] = []
    for actor_id, indexed_requests in grouped.items():
        actor_requests = [request for _index, request in indexed_requests]
        replies, _stats = score_decision_batch(
            actor_requests,
            scorer=scorer_by_actor_id[actor_id],
            actor_policy_id=actor_id,
            rng=rng,
            temperature=float(temperature),
            scorer_batch_size=max(1, int(scorer_batch_size)),
            selection_mode=str(selection_mode or "sampled_from_logits"),
        )
        batch_sizes.append(len(actor_requests))
        for (index, _request), reply in zip(indexed_requests, replies, strict=True):
            replies_by_index[int(index)] = reply
    return [replies_by_index[index] for index in range(len(materialized))], _batch_stats(batch_sizes)


def _actor_model_paths_by_policy_id_from_config(
    config: Mapping[str, Any],
    *,
    default_actor_policy_id: str,
) -> dict[str, str]:
    out: dict[str, str] = {}
    actor_id = str(default_actor_policy_id or "").strip()
    actor_model_path = str(config.get("actorModelPath") or "").strip()
    if actor_id and actor_model_path:
        out[actor_id] = str(Path(actor_model_path))
    raw_paths = config.get("actorModelPathsByPolicyId")
    if isinstance(raw_paths, Mapping):
        for raw_actor_id, raw_path in raw_paths.items():
            policy_id = str(raw_actor_id or "").strip()
            model_path = str(raw_path or "").strip()
            if policy_id and model_path:
                out[policy_id] = str(Path(model_path))
    return out


def _worker_local_actor_scorers(
    config: Mapping[str, Any],
    *,
    actor_id: str,
    scorer: Any | None,
) -> tuple[dict[str, Any], int]:
    actor_paths = _actor_model_paths_by_policy_id_from_config(config, default_actor_policy_id=actor_id)
    if not actor_paths:
        raise ValueError("vector rollout requires at least one actor model path")
    scorer_by_actor_id: dict[str, Any] = {}
    model_load_count = 0
    default_actor_id = str(actor_id or "").strip()
    if scorer is not None and default_actor_id:
        scorer_by_actor_id[default_actor_id] = scorer
    for policy_id, model_path in actor_paths.items():
        if policy_id in scorer_by_actor_id:
            continue
        scorer_by_actor_id[policy_id] = _load_actor_scorer(model_path, actor_policy_id=policy_id)
        model_load_count += 1
    return scorer_by_actor_id, int(model_load_count)


def _batched_actor_policy_ids_from_config(config: Mapping[str, Any], *, default_actor_policy_id: str) -> set[str]:
    return set(
        _actor_model_paths_by_policy_id_from_config(
            config,
            default_actor_policy_id=str(default_actor_policy_id or "").strip(),
        )
    )


def _batched_actor_sides_for_pool_plan(pool_plan: Mapping[str, Any], *, batched_actor_ids: set[str]) -> set[str]:
    sides = {str(side) for side in list(pool_plan.get("currentActorSides") or []) if str(side) in {"P1", "P2"}}
    p1_policy_id = str(pool_plan.get("p1PolicyId") or "").strip()
    p2_policy_id = str(pool_plan.get("p2PolicyId") or "").strip()
    if p1_policy_id in batched_actor_ids:
        sides.add("P1")
    if p2_policy_id in batched_actor_ids:
        sides.add("P2")
    return sides


def run_ygo_vector_actor_rollout(
    *,
    out_dir: str | Path,
    run_id: str,
    current_policy_id: str,
    current_policy_model_path: str | Path,
    seed: int,
    generation_seeds: Sequence[int] | None = None,
    fixed_gate_seed: int | None = None,
    env_count: int = 32,
    worker_env_slots: int = 1,
    worker_local_inference: bool = False,
    num_steps: int = 128,
    inference_batch_size: int = 512,
    inference_timeout_ms: int = 2,
    worker_idle_timeout_seconds: float = DEFAULT_WORKER_IDLE_TIMEOUT_SECONDS,
    action_set_max_actions: int = 128,
    max_game_actions: int = 500,
    max_games_per_env: int = 32,
    selfplay_games_per_pool: int = DEFAULT_SELFPLAY_GAMES_PER_POOL,
    original_games_per_pool: int = DEFAULT_ORIGINAL_GAMES_PER_POOL,
    original_opponent_policy_ids: Sequence[str] = DEFAULT_ORIGINAL_OPPONENT_POLICY_IDS,
    training_pool_schedule: str = DEFAULT_TRAINING_POOL_SCHEDULE,
    training_pool_schedule_cycle_index: int = 0,
    max_bridge_decisions_per_env: int = 16,
    drain_to_terminal: bool = False,
    original_drain_to_terminal: bool = False,
    selfplay_drain_to_terminal: bool = False,
    execution_backend: str = "process",
    compact_action_rows: bool = True,
    current_policy_rollout_selection_mode: str | None = "sampled_from_logits",
    current_policy_rollout_temperature: float = 1.0,
    sqlite_debug_log: bool = False,
    gate_task_specs: Sequence[Mapping[str, Any]] | None = None,
    actor_model_paths_by_policy_id: Mapping[str, str | Path] | None = None,
    gate_deck_pool_payloads: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
    rolling_env_state: bool = False,
    return_rows: bool = True,
) -> dict[str, Any]:
    actor_id = str(current_policy_id or "").strip()
    if not actor_id:
        raise ValueError("current_policy_id must be non-empty")
    if str(current_policy_rollout_selection_mode or "sampled_from_logits") not in {
        "sampled_from_logits",
        "stochastic_rollout",
        "masked_argmax_action",
        "argmax",
        "greedy",
    }:
        raise ValueError("vector rollout requires sampled_from_logits/stochastic_rollout or masked_argmax_action")
    envs = max(1, int(env_count))
    worker_slots = max(1, int(worker_env_slots))
    steps = max(1, int(num_steps))
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    if bool(worker_local_inference) or worker_slots > 1:
        worker_count = max(1, int(math.ceil(envs / float(worker_slots))))
        if worker_count > DEFAULT_WORKER_LOCAL_VECTOR_PROCESS_CAP:
            raise ValueError(
                "worker-local vector rollout would start "
                f"{worker_count} worker processes for env_count={envs}, worker_env_slots={worker_slots}; "
                f"the current cap is {DEFAULT_WORKER_LOCAL_VECTOR_PROCESS_CAP}."
            )
        return _run_ygo_worker_local_vectorized_rollout(
            out_path=out_path,
            run_id=str(run_id),
            actor_id=actor_id,
            current_policy_model_path=current_policy_model_path,
            seed=int(seed),
            generation_seeds=generation_seeds,
            fixed_gate_seed=fixed_gate_seed,
            worker_count=worker_count,
            worker_env_slots=worker_slots,
            num_steps=steps,
            inference_batch_size=inference_batch_size,
            inference_timeout_ms=inference_timeout_ms,
            worker_idle_timeout_seconds=worker_idle_timeout_seconds,
            action_set_max_actions=action_set_max_actions,
            max_game_actions=max_game_actions,
            max_games_per_env=max_games_per_env,
            selfplay_games_per_pool=selfplay_games_per_pool,
            original_games_per_pool=original_games_per_pool,
            original_opponent_policy_ids=original_opponent_policy_ids,
            training_pool_schedule=training_pool_schedule,
            training_pool_schedule_cycle_index=training_pool_schedule_cycle_index,
            max_bridge_decisions_per_env=max_bridge_decisions_per_env,
            drain_to_terminal=drain_to_terminal,
            original_drain_to_terminal=original_drain_to_terminal,
            selfplay_drain_to_terminal=selfplay_drain_to_terminal,
            execution_backend=execution_backend,
            compact_action_rows=compact_action_rows,
            current_policy_rollout_selection_mode=current_policy_rollout_selection_mode,
            current_policy_rollout_temperature=current_policy_rollout_temperature,
            sqlite_debug_log=sqlite_debug_log,
            gate_task_specs=gate_task_specs,
            actor_model_paths_by_policy_id=actor_model_paths_by_policy_id,
            gate_deck_pool_payloads=gate_deck_pool_payloads,
            rolling_env_state=bool(rolling_env_state),
            return_rows=return_rows,
        )
    scorer = _load_actor_scorer(current_policy_model_path, actor_policy_id=actor_id)

    started = time.perf_counter()
    backend = _normalise_execution_backend(execution_backend)
    ctx = _spawn_context_for_backend(backend)
    request_queue: Any = (
        ctx.Queue(maxsize=max(8, envs * 4))
        if ctx is not None
        else queue.Queue(maxsize=max(8, envs * 4))
    )
    reply_queues: list[Any] = [
        ctx.Queue(maxsize=4) if ctx is not None else queue.Queue(maxsize=4)
        for _index in range(envs)
    ]
    seeds = [int(value) for value in list(generation_seeds or [])] or [int(seed)]
    processes: list[Any] = []
    for worker_index in range(envs):
        worker_seed = int(seeds[worker_index % len(seeds)]) + worker_index * 1009
        worker_args = (
            worker_index,
            request_queue,
            reply_queues[worker_index],
            request_queue,
            {
                "runId": str(run_id),
                "actorPolicyId": actor_id,
                "seed": int(worker_seed),
                "targetSteps": steps,
                "actionSetMaxActions": int(action_set_max_actions),
                "maxGameActions": int(max_game_actions),
                "maxGames": int(max_games_per_env),
                "envCount": int(envs),
                "selfplayGamesPerPool": int(selfplay_games_per_pool),
                "originalGamesPerPool": int(original_games_per_pool),
                "originalOpponentPolicyIds": [str(value) for value in list(original_opponent_policy_ids or [])],
                "trainingPoolSchedule": _normalise_training_pool_schedule(training_pool_schedule),
                "trainingPoolScheduleCycleIndex": int(training_pool_schedule_cycle_index),
                "maxBridgeDecisions": int(max_bridge_decisions_per_env),
                "drainToTerminal": bool(drain_to_terminal),
                "originalDrainToTerminal": bool(original_drain_to_terminal),
                "selfplayDrainToTerminal": bool(selfplay_drain_to_terminal),
                "compactActionRows": bool(compact_action_rows),
                "selectionMode": str(current_policy_rollout_selection_mode or "sampled_from_logits"),
                "temperature": float(current_policy_rollout_temperature),
                "gateTaskSpecs": [dict(task) for task in list(gate_task_specs or [])],
                "gateDeckPoolPayloads": _copy_gate_deck_pool_payloads(gate_deck_pool_payloads),
                "rollingEnvState": bool(rolling_env_state),
            },
        )
        process = (
            ctx.Process(target=_worker_main, args=worker_args)
            if ctx is not None
            else threading.Thread(target=_worker_main, args=worker_args, daemon=True)
        )
        process.start()
        processes.append(process)

    active_workers = envs
    trajectory_rows: list[dict[str, Any]] = []
    bridge_rows: list[dict[str, Any]] = []
    game_rows: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    worker_games = 0
    worker_decisions = 0
    pool_games: Counter[str] = Counter()
    pool_trajectory_rows: Counter[str] = Counter()
    batch_sizes: list[int] = []
    scorer_rng = random.Random(int(seed) ^ 0x5EED_BA7C)
    try:
        while active_workers > 0:
            item = request_queue.get(timeout=30.0)
            if not isinstance(item, Mapping):
                continue
            kind = str(item.get("kind") or "")
            if kind == "decision":
                pending = [item]
                deadline = time.perf_counter() + max(0.0, float(inference_timeout_ms) / 1000.0)
                while len(pending) < max(1, int(inference_batch_size)) and time.perf_counter() < deadline:
                    try:
                        next_item = request_queue.get(timeout=max(0.0, deadline - time.perf_counter()))
                    except queue.Empty:
                        break
                    if isinstance(next_item, Mapping) and str(next_item.get("kind") or "") == "decision":
                        pending.append(next_item)
                    elif isinstance(next_item, Mapping) and str(next_item.get("kind") or "") == "value":
                        request_queue.put(next_item)
                        break
                    elif isinstance(next_item, Mapping):
                        next_kind = str(next_item.get("kind") or "")
                        if next_kind == "worker_rows":
                            _append_worker_result_rows(
                                next_item,
                                trajectory_rows=trajectory_rows,
                                bridge_rows=bridge_rows,
                                game_rows=game_rows,
                                errors=errors,
                            )
                        elif next_kind in {"worker_done", "worker_error"}:
                            active_workers -= 1
                            if next_kind == "worker_done":
                                _append_mapping_rows(trajectory_rows, next_item.get("trajectoryRows"))
                                _append_mapping_rows(bridge_rows, next_item.get("bridgeRows"))
                                _append_mapping_rows(game_rows, next_item.get("gameRows"))
                                worker_games += int(next_item.get("games", 0) or 0)
                                worker_decisions += int(next_item.get("decisions", 0) or 0)
                                pool_games.update(_counter_mapping(next_item.get("poolGames")))
                                pool_trajectory_rows.update(_counter_mapping(next_item.get("poolTrajectoryRows")))
                            else:
                                errors.append(dict(next_item))
                replies, stats = score_decision_batch(
                    pending,
                    scorer=scorer,
                    actor_policy_id=actor_id,
                    rng=scorer_rng,
                    temperature=float(current_policy_rollout_temperature),
                    scorer_batch_size=max(1, int(inference_batch_size)),
                    selection_mode=str(current_policy_rollout_selection_mode or "sampled_from_logits"),
                )
                batch_sizes.append(int(stats["maxInferenceBatchSize"]))
                for request, reply in zip(pending, replies, strict=True):
                    worker_index = int(request.get("workerIndex", 0) or 0)
                    reply_queues[worker_index].put({"kind": "decision_result", **reply})
                continue
            if kind == "value":
                pending = [item]
                deadline = time.perf_counter() + max(0.0, float(inference_timeout_ms) / 1000.0)
                while len(pending) < max(1, int(inference_batch_size)) and time.perf_counter() < deadline:
                    try:
                        next_item = request_queue.get(timeout=max(0.0, deadline - time.perf_counter()))
                    except queue.Empty:
                        break
                    if isinstance(next_item, Mapping) and str(next_item.get("kind") or "") == "value":
                        pending.append(next_item)
                    elif isinstance(next_item, Mapping) and str(next_item.get("kind") or "") == "decision":
                        request_queue.put(next_item)
                        break
                    elif isinstance(next_item, Mapping):
                        next_kind = str(next_item.get("kind") or "")
                        if next_kind == "worker_rows":
                            _append_worker_result_rows(
                                next_item,
                                trajectory_rows=trajectory_rows,
                                bridge_rows=bridge_rows,
                                game_rows=game_rows,
                                errors=errors,
                            )
                        elif next_kind in {"worker_done", "worker_error"}:
                            active_workers -= 1
                            if next_kind == "worker_done":
                                _append_mapping_rows(trajectory_rows, next_item.get("trajectoryRows"))
                                _append_mapping_rows(bridge_rows, next_item.get("bridgeRows"))
                                _append_mapping_rows(game_rows, next_item.get("gameRows"))
                                worker_games += int(next_item.get("games", 0) or 0)
                                worker_decisions += int(next_item.get("decisions", 0) or 0)
                                pool_games.update(_counter_mapping(next_item.get("poolGames")))
                                pool_trajectory_rows.update(_counter_mapping(next_item.get("poolTrajectoryRows")))
                            else:
                                errors.append(dict(next_item))
                replies, stats = score_value_batch(pending, scorer=scorer)
                batch_sizes.append(int(stats["maxInferenceBatchSize"]))
                for request, reply in zip(pending, replies, strict=True):
                    worker_index = int(request.get("workerIndex", 0) or 0)
                    reply_queues[worker_index].put({"kind": "value_result", **reply})
                continue
            if kind == "worker_done":
                active_workers -= 1
                _append_mapping_rows(trajectory_rows, item.get("trajectoryRows"))
                _append_mapping_rows(bridge_rows, item.get("bridgeRows"))
                _append_mapping_rows(game_rows, item.get("gameRows"))
                _append_mapping_rows(errors, item.get("errors"))
                worker_games += int(item.get("games", 0) or 0)
                worker_decisions += int(item.get("decisions", 0) or 0)
                pool_games.update(_counter_mapping(item.get("poolGames")))
                pool_trajectory_rows.update(_counter_mapping(item.get("poolTrajectoryRows")))
                continue
            if kind == "worker_rows":
                _append_worker_result_rows(
                    item,
                    trajectory_rows=trajectory_rows,
                    bridge_rows=bridge_rows,
                    game_rows=game_rows,
                    errors=errors,
                )
                continue
            if kind == "worker_error":
                active_workers -= 1
                errors.append(dict(item))
    finally:
        for process in processes:
            process.join(timeout=5.0)
            if getattr(process, "is_alive", lambda: False)() and hasattr(process, "terminate"):
                process.terminate()
                process.join(timeout=2.0)

    elapsed = max(0.000001, time.perf_counter() - started)
    decision_rows = int(len(trajectory_rows))
    bridge_count = int(len(bridge_rows))
    report = {
        "kind": VECTOR_ACTOR_ROLLOUT_VERSION,
        "createdAt": _utc_now(),
        "runId": str(run_id),
        "outDir": str(out_path),
        "fixedGateSeed": None if fixed_gate_seed is None else int(fixed_gate_seed),
        "generationSeeds": seeds,
        "currentPolicyId": actor_id,
        "currentPolicyActorPolicyId": actor_id,
        "currentPolicyActorModelPath": str(Path(current_policy_model_path)),
        "rolloutBackend": VECTOR_ROLLOUT_BACKEND,
        "centralBatchedInference": True,
        "farmStatus": "completed" if not errors else "completed_with_worker_failures",
        "executionErrors": errors[:20],
        "workerFailures": int(len(errors)),
        "taskFailures": 0,
        "identityFailures": 0,
        "overrideFailures": 0,
        "dirtyBranchRows": 0,
        "timeoutCancelledTasks": 0,
        "timeoutTerminatedWorkers": 0,
        "stoppedByMaxElapsedSeconds": False,
        "trainableActionValueRows": bridge_count,
        "runtimeReadyTrainableActionValueRows": bridge_count,
        "trainableTrajectoryRows": decision_rows,
        "branchRows": 0,
        "actionValueRows": bridge_count,
        "workerGames": int(worker_games),
        "gateTaskSpecs": {
            "enabled": bool(gate_task_specs),
            "tasks": int(len(list(gate_task_specs or []))),
            "gameRows": int(len(game_rows)),
        },
        "workerDecisions": int(worker_decisions or decision_rows),
        "envCount": envs,
        "executionBackend": backend,
        "compactActionRows": bool(compact_action_rows),
        "numSteps": steps,
        "fixedStepTargetRows": int(envs * steps),
        "rolloutPool": {
            "selfplayGamesPerPool": int(selfplay_games_per_pool),
            "originalGamesPerPool": int(original_games_per_pool),
            "originalOpponentPolicyIds": [str(value) for value in list(original_opponent_policy_ids or [])],
            "trainingPoolSchedule": _normalise_training_pool_schedule(training_pool_schedule),
            "trainingPoolScheduleCycleIndex": int(training_pool_schedule_cycle_index),
            "trainingRows": "current_actor_controlled_actions_only",
            "originalIsOpponentOnly": True,
            "teacherScoreImitation": False,
            "poolGames": dict(pool_games),
            "poolTrajectoryRows": dict(pool_trajectory_rows),
        },
        "drainToTerminal": bool(drain_to_terminal),
        "originalDrainToTerminal": bool(original_drain_to_terminal),
        "selfplayDrainToTerminal": bool(selfplay_drain_to_terminal),
        "fixedStepTruncation": not bool(drain_to_terminal),
        "terminalSignal": _trajectory_terminal_signal_report(trajectory_rows),
        "bridgeDecisionLimitPerEnv": int(max_bridge_decisions_per_env),
        "selectionMode": str(current_policy_rollout_selection_mode or "sampled_from_logits"),
        "temperature": float(current_policy_rollout_temperature),
        "throughput": {
            "elapsedSeconds": float(elapsed),
            "decisionRows": decision_rows,
            "decisionRowsPerSecond": float(decision_rows) / elapsed,
            "bridgeRows": bridge_count,
            "bridgeRowsPerSecond": float(bridge_count) / elapsed,
        },
        "inference": {
            **_batch_stats(batch_sizes),
            "inferenceBatchSize": int(inference_batch_size),
            "inferenceTimeoutMs": int(inference_timeout_ms),
        },
        "onlineTransitionBuffer": {
            "enabled": True,
            "trajectoryRows": decision_rows,
            "bridgeRows": bridge_count,
            "jsonReportCarriesRows": False,
            "sqliteHotPath": bool(sqlite_debug_log),
        },
        "trainingRowsSource": {
            "kind": "in_memory_transition_buffer",
            "schema": CURRENT_POLICY_TRAJECTORY_ROWS_SCHEMA,
            "rowSchema": CURRENT_POLICY_TRAJECTORY_ROWS_SCHEMA,
            "sqliteHotPath": bool(sqlite_debug_log),
            "jsonHotPath": False,
        },
        "storage": {
            "kind": "in_memory_transition_buffer",
            "dbPath": None,
            "jsonGzipInMainLoop": False,
            "inMemoryTrajectoryBufferEnabled": True,
            "sqliteHotPath": bool(sqlite_debug_log),
        },
        "skipped": {},
        "trainingLaunched": False,
        "scratchTraining": False,
        "gateLaunched": False,
        "promotionApproved": False,
        "_trajectoryRows": trajectory_rows,
        "_bridgeRows": bridge_rows,
        "_gameRows": game_rows,
    }
    report_path = out_path / "ygo_vector_actor_rollout_report.json"
    persisted = {key: value for key, value in report.items() if key not in {"_trajectoryRows", "_bridgeRows", "_gameRows"}}
    report_path.write_text(json.dumps(persisted, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    report["reportPath"] = str(report_path)
    return report


class PersistentYgoWorkerLocalVectorRolloutPool:
    """Persistent worker pool for worker-local vectorized rollout batches."""

    def __init__(
        self,
        *,
        worker_count: int,
        worker_env_slots: int,
        num_steps: int,
        inference_batch_size: int = 512,
        inference_timeout_ms: int = 2,
        worker_idle_timeout_seconds: float = DEFAULT_WORKER_IDLE_TIMEOUT_SECONDS,
        action_set_max_actions: int = 128,
        max_game_actions: int = 500,
        max_games_per_env: int = 32,
        selfplay_games_per_pool: int = DEFAULT_SELFPLAY_GAMES_PER_POOL,
        original_games_per_pool: int = DEFAULT_ORIGINAL_GAMES_PER_POOL,
        original_opponent_policy_ids: Sequence[str] = DEFAULT_ORIGINAL_OPPONENT_POLICY_IDS,
        training_pool_schedule: str = DEFAULT_TRAINING_POOL_SCHEDULE,
        max_bridge_decisions_per_env: int = 16,
        drain_to_terminal: bool = False,
        original_drain_to_terminal: bool = False,
        selfplay_drain_to_terminal: bool = False,
        execution_backend: str = "process",
        compact_action_rows: bool = True,
        current_policy_rollout_selection_mode: str | None = "sampled_from_logits",
        current_policy_rollout_temperature: float = 1.0,
        sqlite_debug_log: bool = False,
        gate_task_specs: Sequence[Mapping[str, Any]] | None = None,
        gate_deck_pool_payloads: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
        rolling_env_state: bool = False,
    ) -> None:
        self.worker_count = max(1, int(worker_count))
        if self.worker_count > DEFAULT_WORKER_LOCAL_VECTOR_PROCESS_CAP:
            raise ValueError(
                "persistent worker-local vector rollout would start "
                f"{self.worker_count} worker processes; the current cap is {DEFAULT_WORKER_LOCAL_VECTOR_PROCESS_CAP}."
            )
        self.worker_env_slots = max(1, int(worker_env_slots))
        self.num_steps = max(1, int(num_steps))
        self.execution_backend = _normalise_execution_backend(execution_backend)
        self.ctx = _spawn_context_for_backend(self.execution_backend)
        self.output_queue: Any = (
            self.ctx.Queue(maxsize=max(8, self.worker_count * 2))
            if self.ctx is not None
            else queue.Queue(maxsize=max(8, self.worker_count * 2))
        )
        self.command_queues: list[Any] = []
        self.processes: list[Any] = []
        self._closed = False
        self._rollout_index = 0
        self.base_config = {
            "targetSteps": int(self.num_steps),
            "workerEnvSlots": int(self.worker_env_slots),
            "totalEnvSlots": int(self.worker_count * self.worker_env_slots),
            "actionSetMaxActions": int(action_set_max_actions),
            "maxGameActions": int(max_game_actions),
            "maxGames": int(max_games_per_env),
            "selfplayGamesPerPool": int(selfplay_games_per_pool),
            "originalGamesPerPool": int(original_games_per_pool),
            "originalOpponentPolicyIds": [str(value) for value in list(original_opponent_policy_ids or [])],
            "trainingPoolSchedule": _normalise_training_pool_schedule(training_pool_schedule),
            "trainingPoolScheduleCycleIndex": 0,
            "maxBridgeDecisions": int(max_bridge_decisions_per_env),
            "drainToTerminal": bool(drain_to_terminal),
            "originalDrainToTerminal": bool(original_drain_to_terminal),
            "selfplayDrainToTerminal": bool(selfplay_drain_to_terminal),
            "compactActionRows": bool(compact_action_rows),
            "selectionMode": str(current_policy_rollout_selection_mode or "sampled_from_logits"),
            "temperature": float(current_policy_rollout_temperature),
            "inferenceBatchSize": int(inference_batch_size),
            "inferenceTimeoutMs": int(inference_timeout_ms),
            "workerIdleTimeoutSeconds": float(worker_idle_timeout_seconds),
            "gateTaskSpecs": [dict(task) for task in list(gate_task_specs or []) if isinstance(task, Mapping)],
            "gateDeckPoolPayloads": _copy_gate_deck_pool_payloads(gate_deck_pool_payloads),
            "rollingEnvState": bool(rolling_env_state),
        }
        for worker_index in range(self.worker_count):
            command_queue: Any = (
                self.ctx.Queue(maxsize=4)
                if self.ctx is not None
                else queue.Queue(maxsize=4)
            )
            args = (worker_index, command_queue, self.output_queue, dict(self.base_config))
            process = (
                self.ctx.Process(target=_persistent_worker_local_vectorized_main, args=args)
                if self.ctx is not None
                else threading.Thread(target=_persistent_worker_local_vectorized_main, args=args, daemon=True)
            )
            process.start()
            self.command_queues.append(command_queue)
            self.processes.append(process)

    def __enter__(self) -> "PersistentYgoWorkerLocalVectorRolloutPool":
        return self

    def __exit__(self, _exc_type: Any, _exc: Any, _tb: Any) -> None:
        self.close()

    @property
    def total_env_slots(self) -> int:
        return int(self.worker_count * self.worker_env_slots)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        for command_queue in self.command_queues:
            try:
                command_queue.put({"kind": "shutdown"}, timeout=1.0)
            except Exception:
                pass
        join_deadline = time.perf_counter() + 5.0
        for process in self.processes:
            timeout = max(0.0, min(0.5, join_deadline - time.perf_counter()))
            process.join(timeout=timeout)
        for process in self.processes:
            if getattr(process, "is_alive", lambda: False)() and hasattr(process, "terminate"):
                process.terminate()
        for process in self.processes:
            process.join(timeout=1.0)
        for process in self.processes:
            if getattr(process, "is_alive", lambda: False)() and hasattr(process, "kill"):
                process.kill()
                process.join(timeout=2.0)

    def rollout(
        self,
        *,
        out_dir: str | Path,
        run_id: str,
        actor_id: str,
        current_policy_model_path: str | Path,
        seed: int,
        generation_seeds: Sequence[int] | None = None,
        fixed_gate_seed: int | None = None,
        training_pool_schedule_cycle_index: int = 0,
    ) -> dict[str, Any]:
        if self._closed:
            raise RuntimeError("persistent rollout pool is closed")
        actor_id = str(actor_id or "").strip()
        if not actor_id:
            raise ValueError("actor_id must be non-empty")
        out_path = Path(out_dir)
        out_path.mkdir(parents=True, exist_ok=True)
        started = time.perf_counter()
        self._rollout_index += 1
        batch_id = f"{run_id}:batch-{self._rollout_index}"
        seeds = [int(value) for value in list(generation_seeds or [])] or [int(seed)]
        for worker_index, command_queue in enumerate(self.command_queues):
            worker_seed = int(seeds[worker_index % len(seeds)]) + worker_index * 1009
            config = {
                **self.base_config,
                "runId": str(run_id),
                "actorPolicyId": str(actor_id),
                "actorModelPath": str(Path(current_policy_model_path)),
                "seed": int(worker_seed),
                "globalSlotOffset": int(worker_index * self.worker_env_slots),
                "trainingPoolScheduleCycleIndex": int(training_pool_schedule_cycle_index),
            }
            try:
                command_queue.put_nowait({"kind": "rollout", "batchId": batch_id, "config": config})
            except queue.Full as exc:
                self.close()
                raise TimeoutError(
                    f"persistent vector rollout timed out dispatching worker {worker_index}"
                ) from exc

        trajectory_rows: list[dict[str, Any]] = []
        bridge_rows: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        worker_games = 0
        worker_decisions = 0
        pool_games: Counter[str] = Counter()
        pool_trajectory_rows: Counter[str] = Counter()
        inference_batch_calls = 0
        inference_decisions = 0
        max_inference_batch_size = 0
        model_load_count = 0
        model_reload_count = 0
        worker_profile: Counter[str] = Counter()
        rolling_continued_games = 0
        rolling_carried_games = 0
        fixed_step_carried_rows = 0
        hard_max_action_truncated_games = 0
        hard_max_action_truncated_rows = 0
        hard_max_action_rows_with_bootstrap = 0
        hard_max_action_truncated_by_pool: Counter[str] = Counter()
        hard_max_action_truncated_by_deck_pair: Counter[str] = Counter()
        rolling_active_slots = 0
        active_workers = int(self.worker_count)
        pending_workers = set(range(int(self.worker_count)))
        while active_workers > 0:
            try:
                item = self.output_queue.get(timeout=_worker_idle_timeout_seconds(self.base_config))
            except queue.Empty as exc:
                self.close()
                raise TimeoutError(
                    "persistent vector rollout timed out waiting for "
                    f"{active_workers} worker(s): {sorted(pending_workers)}"
                ) from exc
            if not isinstance(item, Mapping) or str(item.get("batchId") or "") != batch_id:
                continue
            kind = str(item.get("kind") or "")
            if kind == "worker_rows":
                _append_worker_result_rows(
                    item,
                    trajectory_rows=trajectory_rows,
                    bridge_rows=bridge_rows,
                    errors=errors,
                )
                continue
            if kind == "worker_done":
                active_workers -= 1
                pending_workers.discard(int(item.get("workerIndex", -1) or -1))
                _append_mapping_rows(trajectory_rows, item.get("trajectoryRows"))
                _append_mapping_rows(bridge_rows, item.get("bridgeRows"))
                worker_games += int(item.get("games", 0) or 0)
                worker_decisions += int(item.get("decisions", 0) or 0)
                pool_games.update(_counter_mapping(item.get("poolGames")))
                pool_trajectory_rows.update(_counter_mapping(item.get("poolTrajectoryRows")))
                inference = item.get("inference") if isinstance(item.get("inference"), Mapping) else {}
                inference_batch_calls += int(inference.get("inferenceBatchCalls") or 0)
                inference_decisions += int(inference.get("decisionRequests") or 0)
                max_inference_batch_size = max(max_inference_batch_size, int(inference.get("maxInferenceBatchSize") or 0))
                model_load_count += int(item.get("modelLoadCount") or 0)
                model_reload_count += int(item.get("modelReloadCount") or 0)
                worker_profile.update(_float_counter_mapping(item.get("profile")))
                rolling_continued_games += int(item.get("rollingContinuedGames", 0) or 0)
                rolling_carried_games += int(item.get("rollingCarriedGames", 0) or 0)
                fixed_step_carried_rows += int(item.get("fixedStepCarriedRows", 0) or 0)
                hard_max_action_truncated_games += int(item.get("hardMaxActionTruncatedGames", 0) or 0)
                hard_max_action_truncated_rows += int(item.get("hardMaxActionTruncatedRows", 0) or 0)
                hard_max_action_rows_with_bootstrap += int(item.get("hardMaxActionRowsWithBootstrap", 0) or 0)
                hard_max_action_truncated_by_pool.update(_counter_mapping(item.get("hardMaxActionTruncatedByPool")))
                hard_max_action_truncated_by_deck_pair.update(_counter_mapping(item.get("hardMaxActionTruncatedByDeckPair")))
                rolling_active_slots += int(item.get("rollingActiveSlots", 0) or 0)
            elif kind == "worker_error":
                if _worker_error_is_retryable_idle_timeout(item):
                    worker_index = int(item.get("workerIndex", -1) or -1)
                    self.close()
                    raise TimeoutError(
                        f"persistent vector rollout worker {worker_index} timed out internally"
                    )
                active_workers -= 1
                pending_workers.discard(int(item.get("workerIndex", -1) or -1))
                errors.append(dict(item))

        elapsed = max(0.000001, time.perf_counter() - started)
        decision_rows = int(len(trajectory_rows))
        bridge_count = int(len(bridge_rows))
        inference_timeout_ms = self.base_config.get("inferenceTimeoutMs", 2)
        if inference_timeout_ms is None:
            inference_timeout_ms = 2
        report = {
            "kind": VECTOR_ACTOR_ROLLOUT_VERSION,
            "createdAt": _utc_now(),
            "runId": str(run_id),
            "outDir": str(out_path),
            "fixedGateSeed": None if fixed_gate_seed is None else int(fixed_gate_seed),
            "generationSeeds": seeds,
            "currentPolicyId": actor_id,
            "currentPolicyActorPolicyId": actor_id,
            "currentPolicyActorModelPath": str(Path(current_policy_model_path)),
            "rolloutBackend": WORKER_LOCAL_VECTOR_ROLLOUT_BACKEND,
            "persistentWorkerPool": True,
            "centralBatchedInference": False,
            "workerLocalBatchedInference": True,
            "farmStatus": "completed" if not errors else "completed_with_worker_failures",
            "executionErrors": errors[:20],
            "workerFailures": int(len(errors)),
            "taskFailures": 0,
            "identityFailures": 0,
            "overrideFailures": 0,
            "dirtyBranchRows": 0,
            "timeoutCancelledTasks": 0,
            "timeoutTerminatedWorkers": 0,
            "trainableActionValueRows": bridge_count,
            "runtimeReadyTrainableActionValueRows": bridge_count,
            "trainableTrajectoryRows": decision_rows,
            "branchRows": 0,
            "actionValueRows": bridge_count,
            "workerGames": int(worker_games),
            "workerDecisions": int(worker_decisions or decision_rows),
            "workerCount": int(self.worker_count),
            "envSlotsPerWorker": int(self.worker_env_slots),
            "envCount": int(self.total_env_slots),
            "executionBackend": self.execution_backend,
            "compactActionRows": bool(self.base_config.get("compactActionRows", True)),
            "numSteps": int(self.num_steps),
            "fixedStepTargetRows": int(self.total_env_slots * self.num_steps),
            "modelLoadCount": int(model_load_count),
            "modelReloadCount": int(model_reload_count),
            "modelBroadcastCount": 1,
            "drainToTerminal": bool(self.base_config.get("drainToTerminal", False)),
            "originalDrainToTerminal": bool(self.base_config.get("originalDrainToTerminal", False)),
            "rollingEnvState": bool(self.base_config.get("rollingEnvState", False)),
            "rollingContinuedGames": int(rolling_continued_games),
            "rollingCarriedGames": int(rolling_carried_games),
            "fixedStepCarriedRows": int(fixed_step_carried_rows),
            "rollingActiveSlots": int(rolling_active_slots),
            "hardMaxActionTruncatedGames": int(hard_max_action_truncated_games),
            "hardMaxActionTruncatedRows": int(hard_max_action_truncated_rows),
            "hardMaxActionRowsWithBootstrap": int(hard_max_action_rows_with_bootstrap),
            "hardMaxActionTruncatedByPool": dict(hard_max_action_truncated_by_pool),
            "hardMaxActionTruncatedByDeckPair": dict(hard_max_action_truncated_by_deck_pair),
            "fixedStepTruncation": not bool(self.base_config.get("drainToTerminal", False)),
            "terminalSignal": _trajectory_terminal_signal_report(trajectory_rows),
            "bridgeDecisionLimitPerEnv": int(self.base_config.get("maxBridgeDecisions", 0) or 0),
            "selectionMode": str(self.base_config.get("selectionMode") or "sampled_from_logits"),
            "temperature": float(self.base_config.get("temperature", 1.0) or 1.0),
            "rolloutPool": {
                "selfplayGamesPerPool": int(self.base_config.get("selfplayGamesPerPool", 0) or 0),
                "originalGamesPerPool": int(self.base_config.get("originalGamesPerPool", 0) or 0),
                "originalOpponentPolicyIds": [str(value) for value in list(self.base_config.get("originalOpponentPolicyIds") or [])],
                "trainingPoolSchedule": _normalise_training_pool_schedule(str(self.base_config.get("trainingPoolSchedule") or DEFAULT_TRAINING_POOL_SCHEDULE)),
                "trainingPoolScheduleCycleIndex": int(training_pool_schedule_cycle_index),
                "trainingRows": "current_actor_controlled_actions_only",
                "originalIsOpponentOnly": True,
                "teacherScoreImitation": False,
                "poolGames": dict(pool_games),
                "poolTrajectoryRows": dict(pool_trajectory_rows),
            },
            "throughput": {
                "elapsedSeconds": float(elapsed),
                "decisionRows": decision_rows,
                "transitionsPerSecond": float(decision_rows) / elapsed,
                "decisionRowsPerSecond": float(decision_rows) / elapsed,
                "gamesCompleted": int(worker_games),
                "gamesCompletedPerSecond": float(worker_games) / elapsed,
                "actorInferenceBatchesPerSecond": float(inference_batch_calls) / elapsed,
                "avgEnvStepSeconds": elapsed / float(max(1, decision_rows)),
                "bridgeRows": bridge_count,
                "bridgeRowsPerSecond": float(bridge_count) / elapsed,
            },
            "inference": {
                "decisionRequests": int(inference_decisions),
                "inferenceBatchCalls": int(inference_batch_calls),
                "meanInferenceBatchSize": float(inference_decisions) / float(inference_batch_calls) if inference_batch_calls else 0.0,
                "maxInferenceBatchSize": int(max_inference_batch_size),
                "inferenceBatchSize": int(self.base_config.get("inferenceBatchSize", 512) or 512),
                "inferenceTimeoutMs": int(inference_timeout_ms),
            },
            "workerProfile": dict(worker_profile),
            "onlineTransitionBuffer": {
                "enabled": True,
                "trajectoryRows": decision_rows,
                "bridgeRows": bridge_count,
                "jsonReportCarriesRows": False,
                "sqliteHotPath": False,
            },
            "trainingRowsSource": {
                "kind": "in_memory_transition_buffer",
                "schema": CURRENT_POLICY_TRAJECTORY_ROWS_SCHEMA,
                "rowSchema": CURRENT_POLICY_TRAJECTORY_ROWS_SCHEMA,
                "sqliteHotPath": False,
                "jsonHotPath": False,
            },
            "storage": {
                "kind": "in_memory_transition_buffer",
                "dbPath": None,
                "jsonGzipInMainLoop": False,
                "inMemoryTrajectoryBufferEnabled": True,
                "sqliteHotPath": False,
            },
            "skipped": {},
            "trainingLaunched": False,
            "scratchTraining": False,
            "gateLaunched": False,
            "promotionApproved": False,
            "_trajectoryRows": trajectory_rows,
            "_bridgeRows": bridge_rows,
        }
        report_path = out_path / "ygo_vector_actor_rollout_report.json"
        persisted = {key: value for key, value in report.items() if key not in {"_trajectoryRows", "_bridgeRows"}}
        report_path.write_text(json.dumps(persisted, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        report["reportPath"] = str(report_path)
        return report


def _run_ygo_worker_local_vectorized_rollout(
    *,
    out_path: Path,
    run_id: str,
    actor_id: str,
    current_policy_model_path: str | Path,
    seed: int,
    generation_seeds: Sequence[int] | None,
    fixed_gate_seed: int | None,
    worker_count: int,
    worker_env_slots: int,
    num_steps: int,
    inference_batch_size: int,
    inference_timeout_ms: int,
    worker_idle_timeout_seconds: float,
    action_set_max_actions: int,
    max_game_actions: int,
    max_games_per_env: int,
    selfplay_games_per_pool: int,
    original_games_per_pool: int,
    original_opponent_policy_ids: Sequence[str],
    training_pool_schedule: str,
    training_pool_schedule_cycle_index: int,
    max_bridge_decisions_per_env: int,
    drain_to_terminal: bool,
    original_drain_to_terminal: bool,
    selfplay_drain_to_terminal: bool,
    execution_backend: str,
    compact_action_rows: bool,
    current_policy_rollout_selection_mode: str | None,
    current_policy_rollout_temperature: float,
    sqlite_debug_log: bool,
    gate_task_specs: Sequence[Mapping[str, Any]] | None = None,
    actor_model_paths_by_policy_id: Mapping[str, str | Path] | None = None,
    gate_deck_pool_payloads: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
    rolling_env_state: bool = False,
    return_rows: bool = True,
) -> dict[str, Any]:
    started = time.perf_counter()
    workers = max(1, int(worker_count))
    slots = max(1, int(worker_env_slots))
    steps = max(1, int(num_steps))
    backend = _normalise_execution_backend(execution_backend)
    ctx = _spawn_context_for_backend(backend)
    output_queue: Any = ctx.Queue(maxsize=max(8, workers * 2)) if ctx is not None else queue.Queue(maxsize=max(8, workers * 2))
    seeds = [int(value) for value in list(generation_seeds or [])] or [int(seed)]
    processes: list[Any] = []
    for worker_index in range(workers):
        worker_seed = int(seeds[worker_index % len(seeds)]) + worker_index * 1009
        config = {
            "runId": str(run_id),
            "actorPolicyId": str(actor_id),
            "actorModelPath": str(Path(current_policy_model_path)),
            "seed": int(worker_seed),
            "targetSteps": steps,
            "workerEnvSlots": slots,
            "totalEnvSlots": workers * slots,
            "globalSlotOffset": worker_index * slots,
            "actionSetMaxActions": int(action_set_max_actions),
            "maxGameActions": int(max_game_actions),
            "maxGames": int(max_games_per_env),
            "selfplayGamesPerPool": int(selfplay_games_per_pool),
            "originalGamesPerPool": int(original_games_per_pool),
            "originalOpponentPolicyIds": [str(value) for value in list(original_opponent_policy_ids or [])],
            "trainingPoolSchedule": _normalise_training_pool_schedule(training_pool_schedule),
            "trainingPoolScheduleCycleIndex": int(training_pool_schedule_cycle_index),
            "maxBridgeDecisions": int(max_bridge_decisions_per_env),
            "drainToTerminal": bool(drain_to_terminal),
            "originalDrainToTerminal": bool(original_drain_to_terminal),
            "selfplayDrainToTerminal": bool(selfplay_drain_to_terminal),
            "compactActionRows": bool(compact_action_rows),
            "selectionMode": str(current_policy_rollout_selection_mode or "sampled_from_logits"),
            "temperature": float(current_policy_rollout_temperature),
            "inferenceBatchSize": int(inference_batch_size),
            "inferenceTimeoutMs": int(inference_timeout_ms),
            "workerIdleTimeoutSeconds": float(worker_idle_timeout_seconds),
            "gateTaskSpecs": [dict(task) for task in list(gate_task_specs or [])],
            "gateDeckPoolPayloads": _copy_gate_deck_pool_payloads(gate_deck_pool_payloads),
            "rollingEnvState": False,
            "actorModelPathsByPolicyId": {
                str(policy_id): str(Path(path))
                for policy_id, path in dict(actor_model_paths_by_policy_id or {}).items()
                if str(policy_id).strip() and str(path).strip()
            },
        }
        args = (worker_index, output_queue, config)
        process = (
            ctx.Process(target=_worker_local_vectorized_main, args=args)
            if ctx is not None
            else threading.Thread(target=_worker_local_vectorized_main, args=args, daemon=True)
        )
        process.start()
        processes.append(process)

    trajectory_rows: list[dict[str, Any]] = []
    bridge_rows: list[dict[str, Any]] = []
    game_rows: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    worker_games = 0
    worker_decisions = 0
    pool_games: Counter[str] = Counter()
    pool_trajectory_rows: Counter[str] = Counter()
    inference_batch_calls = 0
    inference_decisions = 0
    max_inference_batch_size = 0
    model_load_count = 0
    worker_profile: Counter[str] = Counter()
    active_workers = workers
    worker_idle_timeout_seconds = _worker_idle_timeout_seconds(config)
    try:
        while active_workers > 0:
            item = output_queue.get(timeout=worker_idle_timeout_seconds)
            if not isinstance(item, Mapping):
                continue
            kind = str(item.get("kind") or "")
            if kind == "worker_rows":
                _append_worker_result_rows(
                    item,
                    trajectory_rows=trajectory_rows,
                    bridge_rows=bridge_rows,
                    game_rows=game_rows,
                    errors=errors,
                )
                continue
            if kind == "worker_done":
                active_workers -= 1
                _append_mapping_rows(trajectory_rows, item.get("trajectoryRows"))
                _append_mapping_rows(bridge_rows, item.get("bridgeRows"))
                _append_mapping_rows(game_rows, item.get("gameRows"))
                _append_mapping_rows(errors, item.get("errors"))
                worker_games += int(item.get("games", 0) or 0)
                worker_decisions += int(item.get("decisions", 0) or 0)
                pool_games.update(_counter_mapping(item.get("poolGames")))
                pool_trajectory_rows.update(_counter_mapping(item.get("poolTrajectoryRows")))
                inference = item.get("inference") if isinstance(item.get("inference"), Mapping) else {}
                inference_batch_calls += int(inference.get("inferenceBatchCalls") or 0)
                inference_decisions += int(inference.get("decisionRequests") or 0)
                max_inference_batch_size = max(max_inference_batch_size, int(inference.get("maxInferenceBatchSize") or 0))
                model_load_count += int(item.get("modelLoadCount") or 0)
                worker_profile.update(_float_counter_mapping(item.get("profile")))
            elif kind == "worker_error":
                active_workers -= 1
                errors.append(dict(item))
    finally:
        for process in processes:
            process.join(timeout=5.0)
            if getattr(process, "is_alive", lambda: False)() and hasattr(process, "terminate"):
                process.terminate()
                process.join(timeout=2.0)

    elapsed = max(0.000001, time.perf_counter() - started)
    decision_rows = int(len(trajectory_rows))
    bridge_count = int(len(bridge_rows))
    total_env_slots = workers * slots
    report = {
        "kind": VECTOR_ACTOR_ROLLOUT_VERSION,
        "createdAt": _utc_now(),
        "runId": str(run_id),
        "outDir": str(out_path),
        "fixedGateSeed": None if fixed_gate_seed is None else int(fixed_gate_seed),
        "generationSeeds": seeds,
        "currentPolicyId": actor_id,
        "currentPolicyActorPolicyId": actor_id,
        "currentPolicyActorModelPath": str(Path(current_policy_model_path)),
        "rolloutBackend": WORKER_LOCAL_VECTOR_ROLLOUT_BACKEND,
        "centralBatchedInference": False,
        "workerLocalBatchedInference": True,
        "farmStatus": "completed" if not errors else "completed_with_worker_failures",
        "executionErrors": errors[:20],
        "workerFailures": int(len(errors)),
        "taskFailures": 0,
        "identityFailures": 0,
        "overrideFailures": 0,
        "dirtyBranchRows": 0,
        "timeoutCancelledTasks": 0,
        "timeoutTerminatedWorkers": 0,
        "trainableActionValueRows": bridge_count,
        "runtimeReadyTrainableActionValueRows": bridge_count,
        "trainableTrajectoryRows": decision_rows,
        "branchRows": 0,
        "actionValueRows": bridge_count,
        "workerGames": int(worker_games),
        "gateTaskSpecs": {
            "enabled": bool(gate_task_specs),
            "tasks": int(len(list(gate_task_specs or []))),
            "gameRows": int(len(game_rows)),
        },
        "workerDecisions": int(worker_decisions or decision_rows),
        "workerCount": workers,
        "envSlotsPerWorker": slots,
        "envCount": total_env_slots,
        "executionBackend": backend,
        "compactActionRows": bool(compact_action_rows),
        "numSteps": steps,
        "fixedStepTargetRows": int(total_env_slots * steps),
        "modelLoadCount": int(model_load_count),
        "modelReloadCount": 0,
        "modelBroadcastCount": 1,
        "drainToTerminal": bool(drain_to_terminal),
        "originalDrainToTerminal": bool(original_drain_to_terminal),
        "selfplayDrainToTerminal": bool(selfplay_drain_to_terminal),
        "rollingEnvState": False,
        "fixedStepTruncation": not bool(drain_to_terminal),
        "terminalSignal": _trajectory_terminal_signal_report(trajectory_rows),
        "bridgeDecisionLimitPerEnv": int(max_bridge_decisions_per_env),
        "selectionMode": str(current_policy_rollout_selection_mode or "sampled_from_logits"),
        "temperature": float(current_policy_rollout_temperature),
        "rolloutPool": {
            "selfplayGamesPerPool": int(selfplay_games_per_pool),
            "originalGamesPerPool": int(original_games_per_pool),
            "originalOpponentPolicyIds": [str(value) for value in list(original_opponent_policy_ids or [])],
            "trainingPoolSchedule": _normalise_training_pool_schedule(training_pool_schedule),
            "trainingPoolScheduleCycleIndex": int(training_pool_schedule_cycle_index),
            "trainingRows": "current_actor_controlled_actions_only",
            "originalIsOpponentOnly": True,
            "teacherScoreImitation": False,
            "poolGames": dict(pool_games),
            "poolTrajectoryRows": dict(pool_trajectory_rows),
        },
        "throughput": {
            "elapsedSeconds": float(elapsed),
            "decisionRows": decision_rows,
            "transitionsPerSecond": float(decision_rows) / elapsed,
            "decisionRowsPerSecond": float(decision_rows) / elapsed,
            "gamesCompleted": int(worker_games),
            "gamesCompletedPerSecond": float(worker_games) / elapsed,
            "actorInferenceBatchesPerSecond": float(inference_batch_calls) / elapsed,
            "avgEnvStepSeconds": elapsed / float(max(1, decision_rows)),
            "bridgeRows": bridge_count,
            "bridgeRowsPerSecond": float(bridge_count) / elapsed,
        },
            "inference": {
            "decisionRequests": int(inference_decisions),
            "inferenceBatchCalls": int(inference_batch_calls),
            "meanInferenceBatchSize": float(inference_decisions) / float(inference_batch_calls) if inference_batch_calls else 0.0,
            "maxInferenceBatchSize": int(max_inference_batch_size),
            "inferenceBatchSize": int(inference_batch_size),
                "inferenceTimeoutMs": int(inference_timeout_ms),
            },
            "workerProfile": dict(worker_profile),
            "onlineTransitionBuffer": {
            "enabled": True,
            "trajectoryRows": decision_rows,
            "bridgeRows": bridge_count,
            "jsonReportCarriesRows": False,
            "sqliteHotPath": bool(sqlite_debug_log),
        },
        "trainingRowsSource": {
            "kind": "in_memory_transition_buffer",
            "schema": CURRENT_POLICY_TRAJECTORY_ROWS_SCHEMA,
            "rowSchema": CURRENT_POLICY_TRAJECTORY_ROWS_SCHEMA,
            "sqliteHotPath": bool(sqlite_debug_log),
            "jsonHotPath": False,
        },
        "storage": {
            "kind": "in_memory_transition_buffer",
            "dbPath": None,
            "jsonGzipInMainLoop": False,
            "inMemoryTrajectoryBufferEnabled": True,
            "sqliteHotPath": bool(sqlite_debug_log),
        },
        "skipped": {},
        "trainingLaunched": False,
        "scratchTraining": False,
        "gateLaunched": False,
        "promotionApproved": False,
        "returnRows": bool(return_rows),
        "_trajectoryRows": trajectory_rows if return_rows else [],
        "_bridgeRows": bridge_rows if return_rows else [],
        "_gameRows": game_rows if return_rows else [],
    }
    report_path = out_path / "ygo_vector_actor_rollout_report.json"
    persisted = {key: value for key, value in report.items() if key not in {"_trajectoryRows", "_bridgeRows", "_gameRows"}}
    report_path.write_text(json.dumps(persisted, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    report["reportPath"] = str(report_path)
    return report


def _worker_local_vectorized_main(worker_index: int, output_queue: Any, config: Mapping[str, Any]) -> None:
    try:
        result = _run_worker_local_vectorized(worker_index, config)
        _put_worker_result_chunks(
            output_queue,
            batch_id="",
            worker_index=int(worker_index),
            result=result,
            model_load_count=int(result.get("modelLoadCount", 0) or 0),
            model_reload_count=0,
            include_game_rows=True,
        )
    except Exception as exc:  # pragma: no cover - process failures vary.
        output_queue.put(
            {
                "kind": "worker_error",
                "workerIndex": int(worker_index),
                "error": str(exc),
                "traceback": traceback.format_exc(limit=20),
            }
        )


def _persistent_worker_local_vectorized_main(
    worker_index: int,
    command_queue: Any,
    output_queue: Any,
    base_config: Mapping[str, Any],
) -> None:
    scorer: Any | None = None
    loaded_actor_id: str | None = None
    loaded_model_path: str | None = None
    rolling_slot_states: dict[int, Mapping[str, Any]] = {}
    while True:
        command: Any = {}
        try:
            command = command_queue.get()
            if not isinstance(command, Mapping):
                continue
            kind = str(command.get("kind") or "")
            if kind == "shutdown":
                return
            if kind != "rollout":
                continue
            batch_id = str(command.get("batchId") or "")
            config = dict(base_config)
            config.update(dict(command.get("config") or {}))
            actor_id = str(config.get("actorPolicyId") or "").strip()
            model_path = str(Path(str(config.get("actorModelPath") or "")))
            model_load_count = 0
            model_reload_count = 0
            if scorer is None or actor_id != loaded_actor_id or model_path != loaded_model_path:
                had_model = scorer is not None
                scorer = _load_actor_scorer(model_path, actor_policy_id=actor_id)
                loaded_actor_id = actor_id
                loaded_model_path = model_path
                model_load_count = 1
                model_reload_count = 1 if had_model else 0
            if not bool(config.get("rollingEnvState", False)):
                rolling_slot_states.clear()
            result = _run_worker_local_vectorized(
                worker_index,
                config,
                scorer=scorer,
                rolling_slot_states=rolling_slot_states if bool(config.get("rollingEnvState", False)) else None,
            )
            _put_worker_result_chunks(
                output_queue,
                batch_id=batch_id,
                worker_index=int(worker_index),
                result=result,
                model_load_count=int(model_load_count),
                model_reload_count=int(model_reload_count),
            )
        except Exception as exc:  # pragma: no cover - process failures vary.
            output_queue.put(
                {
                    "kind": "worker_error",
                    "batchId": str(command.get("batchId") or "") if isinstance(command, Mapping) else "",
                    "workerIndex": int(worker_index),
                    "error": str(exc),
                    "traceback": traceback.format_exc(limit=20),
                }
            )


def _run_worker_local_vectorized(
    worker_index: int,
    config: Mapping[str, Any],
    *,
    scorer: Any | None = None,
    rolling_slot_states: dict[int, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    actor_id = str(config.get("actorPolicyId") or "").strip()
    scorer_by_actor_id, model_load_count = _worker_local_actor_scorers(
        config,
        actor_id=actor_id,
        scorer=scorer,
    )
    slots = max(1, int(config.get("workerEnvSlots", 1) or 1))
    local_request_queue: queue.Queue = queue.Queue(maxsize=max(16, slots * 8))
    reply_queues: list[queue.Queue] = [queue.Queue(maxsize=4) for _ in range(slots)]
    slot_threads: list[threading.Thread] = []
    use_rolling_state = bool(config.get("rollingEnvState", False)) and rolling_slot_states is not None
    for slot_index in range(slots):
        slot_config = dict(config)
        slot_config["seed"] = int(config.get("seed", 0) or 0) + slot_index * 1009
        slot_config["envCount"] = int(config.get("totalEnvSlots", slots) or slots)
        slot_config["globalSlotOffset"] = int(config.get("globalSlotOffset", 0) or 0)
        rolling_state = rolling_slot_states.get(int(slot_index)) if use_rolling_state else None
        thread = threading.Thread(
            target=_local_env_slot_main,
            args=(slot_index, local_request_queue, reply_queues[slot_index], slot_config, rolling_state),
            daemon=True,
        )
        thread.start()
        slot_threads.append(thread)

    active_slots = slots
    trajectory_rows: list[dict[str, Any]] = []
    bridge_rows: list[dict[str, Any]] = []
    game_rows: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    games = 0
    decisions = 0
    pool_games: Counter[str] = Counter()
    pool_trajectory_rows: Counter[str] = Counter()
    batch_sizes: list[int] = []
    profile: Counter[str] = Counter()
    rolling_continued_games = 0
    rolling_carried_games = 0
    fixed_step_carried_rows = 0
    hard_max_action_truncated_games = 0
    hard_max_action_truncated_rows = 0
    hard_max_action_rows_with_bootstrap = 0
    hard_max_action_truncated_by_pool: Counter[str] = Counter()
    hard_max_action_truncated_by_deck_pair: Counter[str] = Counter()
    scorer_rng = random.Random(int(config.get("seed", 0) or 0) ^ 0x5EED_BA7C)
    worker_idle_timeout_seconds = _worker_idle_timeout_seconds(config)
    while active_slots > 0:
        item = local_request_queue.get(timeout=worker_idle_timeout_seconds)
        if not isinstance(item, Mapping):
            continue
        kind = str(item.get("kind") or "")
        if kind == "decision":
            pending = [item]
            deadline = time.perf_counter() + max(0.0, float(config.get("inferenceTimeoutMs", 2)) / 1000.0)
            while len(pending) < max(1, int(config.get("inferenceBatchSize", 512))) and time.perf_counter() < deadline:
                try:
                    next_item = local_request_queue.get(timeout=max(0.0, deadline - time.perf_counter()))
                except queue.Empty:
                    break
                next_kind = str(next_item.get("kind") or "") if isinstance(next_item, Mapping) else ""
                if next_kind == "decision":
                    pending.append(next_item)
                elif next_kind == "value":
                    local_request_queue.put(next_item)
                    break
                else:
                    _handle_local_slot_control_item(
                        next_item,
                        trajectory_rows=trajectory_rows,
                        bridge_rows=bridge_rows,
                        game_rows=game_rows,
                        errors=errors,
                        pool_games=pool_games,
                        pool_trajectory_rows=pool_trajectory_rows,
                        profile=profile,
                    )
                    if next_kind in {"slot_done", "slot_error"}:
                        active_slots -= 1
            inference_started = time.perf_counter()
            replies, stats = _score_decision_requests_by_actor(
                pending,
                scorer_by_actor_id=scorer_by_actor_id,
                default_actor_policy_id=actor_id,
                rng=scorer_rng,
                temperature=float(config.get("temperature", 1.0) or 1.0),
                scorer_batch_size=max(1, int(config.get("inferenceBatchSize", 512))),
                selection_mode=str(config.get("selectionMode") or "sampled_from_logits"),
            )
            profile["actorInferenceSeconds"] += time.perf_counter() - inference_started
            batch_sizes.append(int(stats["maxInferenceBatchSize"]))
            for request, reply in zip(pending, replies, strict=True):
                reply_queues[int(request.get("workerIndex", 0) or 0)].put({"kind": "decision_result", **reply})
            continue
        if kind == "value":
            inference_started = time.perf_counter()
            value_actor_id = _request_actor_policy_id(item, default_actor_policy_id=actor_id)
            replies, stats = score_value_batch(
                [item],
                scorer=scorer_by_actor_id[_require_actor_scorer_key(value_actor_id, scorer_by_actor_id)],
            )
            profile["valueInferenceSeconds"] += time.perf_counter() - inference_started
            batch_sizes.append(int(stats["maxInferenceBatchSize"]))
            reply_queues[int(item.get("workerIndex", 0) or 0)].put({"kind": "value_result", **replies[0]})
            continue
        if kind in {"slot_done", "slot_error"}:
            active_slots -= 1
            if kind == "slot_done" and use_rolling_state:
                slot_key = int(item.get("slotIndex", -1) or -1)
                next_state = item.get("rollingState")
                if isinstance(next_state, Mapping):
                    rolling_slot_states[slot_key] = next_state
                else:
                    rolling_slot_states.pop(slot_key, None)
                rolling_continued_games += int(item.get("rollingContinuedGames", 0) or 0)
                rolling_carried_games += int(item.get("rollingCarriedGames", 0) or 0)
                fixed_step_carried_rows += int(item.get("fixedStepCarriedRows", 0) or 0)
                hard_max_action_truncated_games += int(item.get("hardMaxActionTruncatedGames", 0) or 0)
                hard_max_action_truncated_rows += int(item.get("hardMaxActionTruncatedRows", 0) or 0)
                hard_max_action_rows_with_bootstrap += int(item.get("hardMaxActionRowsWithBootstrap", 0) or 0)
                hard_max_action_truncated_by_pool.update(_counter_mapping(item.get("hardMaxActionTruncatedByPool")))
                hard_max_action_truncated_by_deck_pair.update(_counter_mapping(item.get("hardMaxActionTruncatedByDeckPair")))
            _handle_local_slot_control_item(
                item,
                trajectory_rows=trajectory_rows,
                bridge_rows=bridge_rows,
                game_rows=game_rows,
                errors=errors,
                pool_games=pool_games,
                pool_trajectory_rows=pool_trajectory_rows,
                profile=profile,
            )
    for thread in slot_threads:
        thread.join(timeout=1.0)
    games = sum(int(value) for value in _counter_mapping(pool_games).values())
    decisions = len(trajectory_rows)
    return {
        "trajectoryRows": trajectory_rows,
        "bridgeRows": bridge_rows,
        "gameRows": game_rows,
        "games": int(games),
        "decisions": int(decisions),
        "poolGames": dict(pool_games),
        "poolTrajectoryRows": dict(pool_trajectory_rows),
        "inference": _batch_stats(batch_sizes),
        "errors": errors,
        "modelLoadCount": int(model_load_count),
        "profile": dict(profile),
        "rollingContinuedGames": int(rolling_continued_games),
        "rollingCarriedGames": int(rolling_carried_games),
        "fixedStepCarriedRows": int(fixed_step_carried_rows),
        "rollingActiveSlots": int(len(rolling_slot_states or {})),
        "hardMaxActionTruncatedGames": int(hard_max_action_truncated_games),
        "hardMaxActionTruncatedRows": int(hard_max_action_truncated_rows),
        "hardMaxActionRowsWithBootstrap": int(hard_max_action_rows_with_bootstrap),
        "hardMaxActionTruncatedByPool": dict(hard_max_action_truncated_by_pool),
        "hardMaxActionTruncatedByDeckPair": dict(hard_max_action_truncated_by_deck_pair),
    }


def _local_env_slot_main(
    slot_index: int,
    request_queue: Any,
    reply_queue: Any,
    config: Mapping[str, Any],
    rolling_state: Mapping[str, Any] | None = None,
) -> None:
    try:
        result = _run_worker(slot_index, request_queue, reply_queue, config, rolling_state=rolling_state)
        request_queue.put({"kind": "slot_done", "slotIndex": int(slot_index), **result})
    except Exception as exc:
        request_queue.put(
            {
                "kind": "slot_error",
                "slotIndex": int(slot_index),
                "error": str(exc),
                "traceback": traceback.format_exc(limit=10),
            }
        )


def _handle_local_slot_control_item(
    item: Any,
    *,
    trajectory_rows: list[dict[str, Any]],
    bridge_rows: list[dict[str, Any]],
    game_rows: list[dict[str, Any]],
    errors: list[dict[str, Any]],
    pool_games: Counter[str],
    pool_trajectory_rows: Counter[str],
    profile: Counter[str] | None = None,
) -> None:
    if not isinstance(item, Mapping):
        return
    kind = str(item.get("kind") or "")
    if kind == "slot_done":
        _append_mapping_rows(trajectory_rows, item.get("trajectoryRows"))
        _append_mapping_rows(bridge_rows, item.get("bridgeRows"))
        _append_mapping_rows(game_rows, item.get("gameRows"))
        pool_games.update(_counter_mapping(item.get("poolGames")))
        pool_trajectory_rows.update(_counter_mapping(item.get("poolTrajectoryRows")))
        if profile is not None:
            profile.update(_float_counter_mapping(item.get("profile")))
    elif kind == "slot_error":
        errors.append(dict(item))


def _continued_pool_plan(pool_plan: Mapping[str, Any], *, actor_policy_id: str) -> dict[str, Any]:
    out = dict(pool_plan)
    actor_id = str(actor_policy_id)
    sides = tuple(str(side) for side in list(out.get("currentActorSides") or []) if str(side) in {"P1", "P2"})
    if "P1" in sides:
        out["p1PolicyId"] = actor_id
    if "P2" in sides:
        out["p2PolicyId"] = actor_id
    if str(out.get("poolKind") or "") == "current_selfplay":
        out["opponentPolicyId"] = actor_id
    return out


def _prepare_continued_batched_policy(
    policy: Any,
    *,
    request_queue: Any,
    reply_queue: Any,
    run_id: str,
    pool_plan: Mapping[str, Any],
) -> None:
    if not isinstance(policy, _BatchedActorPolicy):
        return
    side = str(policy.side)
    opponent_side = "P2" if side == "P1" else "P1"
    policy_id = str(pool_plan.get(f"{side.lower()}PolicyId") or policy.actor_policy_id)
    opponent_id = str(pool_plan.get(f"{opponent_side.lower()}PolicyId") or policy.runtime_opponent_policy_id)
    policy.begin_rollout_segment(
        request_queue=request_queue,
        reply_queue=reply_queue,
        run_id=str(run_id),
        actor_policy_id=policy_id,
        runtime_opponent_policy_id=opponent_id,
        p1_policy_id=str(pool_plan.get("p1PolicyId") or policy.p1_policy_id),
        p2_policy_id=str(pool_plan.get("p2PolicyId") or policy.p2_policy_id),
    )


def _worker_main(
    worker_index: int,
    request_queue: Any,
    reply_queue: Any,
    output_queue: Any,
    config: Mapping[str, Any],
) -> None:
    try:
        result = _run_worker(worker_index, request_queue, reply_queue, config)
        _put_worker_result_chunks(
            output_queue,
            batch_id="",
            worker_index=int(worker_index),
            result=result,
            model_load_count=int(result.get("modelLoadCount", 0) or 0),
            model_reload_count=0,
            include_game_rows=True,
        )
    except Exception as exc:  # pragma: no cover - exercised through integration smoke, exact failures vary.
        output_queue.put(
            {
                "kind": "worker_error",
                "workerIndex": int(worker_index),
                "error": str(exc),
                "traceback": traceback.format_exc(limit=20),
            }
        )


def _run_worker(
    worker_index: int,
    request_queue: Any,
    reply_queue: Any,
    config: Mapping[str, Any],
    rolling_state: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    seed = int(config.get("seed", 0) or 0)
    target_steps = max(1, int(config.get("targetSteps", 1) or 1))
    max_games = max(1, int(config.get("maxGames", 1) or 1))
    max_game_actions = max(1, int(config.get("maxGameActions", 500) or 500))
    max_bridge_decisions = max(0, int(config.get("maxBridgeDecisions", 16) or 0))
    drain_to_terminal = bool(config.get("drainToTerminal", False))
    original_drain_to_terminal = bool(config.get("originalDrainToTerminal", False))
    selfplay_drain_to_terminal = bool(config.get("selfplayDrainToTerminal", False))
    actor_id = str(config.get("actorPolicyId") or "").strip()
    run_id = str(config.get("runId") or "vector-rollout")
    trajectory_rows: list[dict[str, Any]] = []
    bridge_rows: list[dict[str, Any]] = []
    games = 0
    decisions = 0
    bridge_decisions = 0
    rng = random.Random(seed)
    policy_cache: dict[str, Any] = {}
    env_count = max(1, int(config.get("envCount", 1) or 1))
    gate_task_specs = [dict(task) for task in list(config.get("gateTaskSpecs") or []) if isinstance(task, Mapping)]
    selfplay_games_per_pool = max(0, int(config.get("selfplayGamesPerPool", DEFAULT_SELFPLAY_GAMES_PER_POOL) or 0))
    original_games_per_pool = max(0, int(config.get("originalGamesPerPool", DEFAULT_ORIGINAL_GAMES_PER_POOL) or 0))
    training_pool_schedule = _normalise_training_pool_schedule(
        str(config.get("trainingPoolSchedule") or DEFAULT_TRAINING_POOL_SCHEDULE)
    )
    training_pool_schedule_cycle_index = int(config.get("trainingPoolScheduleCycleIndex", 0) or 0)
    original_opponents = tuple(
        str(value).strip()
        for value in list(config.get("originalOpponentPolicyIds") or [])
        if str(value).strip()
    )
    gate_deck_pool_payloads = _normalise_gate_deck_pool_payloads(config.get("gateDeckPoolPayloads"))
    if not gate_deck_pool_payloads:
        gate_deck_pool_payloads = _default_gate_deck_pool_payloads()
    pool_games: Counter[str] = Counter()
    pool_trajectory_rows: Counter[str] = Counter()
    profile: Counter[str] = Counter()
    game_rows: list[dict[str, Any]] = []
    use_rolling_state = bool(config.get("rollingEnvState", False))
    state_in = dict(rolling_state or {}) if isinstance(rolling_state, Mapping) else {}
    next_game_index = int(state_in.get("nextGameIndex", 0) or 0)
    continued_state: dict[str, Any] | None = (
        state_in
        if use_rolling_state and state_in.get("engine") is not None
        else None
    )
    next_rolling_state: dict[str, Any] | None = None
    rolling_continued_games = 0
    rolling_carried_games = 0
    fixed_step_carried_rows = 0
    hard_max_action_truncated_games = 0
    hard_max_action_truncated_rows = 0
    hard_max_action_rows_with_bootstrap = 0
    hard_max_action_truncated_by_pool: Counter[str] = Counter()
    hard_max_action_truncated_by_deck_pair: Counter[str] = Counter()
    while decisions < target_steps and games < max_games:
        game_started = time.perf_counter()
        if continued_state is not None:
            game_index = int(continued_state.get("gameIndex", next_game_index) or next_game_index)
            global_game_index = int(continued_state.get("globalGameIndex", 0) or 0)
            gate_task = continued_state.get("gateTask") if isinstance(continued_state.get("gateTask"), Mapping) else None
            task_id = str(continued_state.get("taskId") or _vector_default_task_id(run_id, global_game_index))
            pool_plan = _continued_pool_plan(
                continued_state.get("poolPlan") if isinstance(continued_state.get("poolPlan"), Mapping) else {},
                actor_policy_id=actor_id,
            )
            game_seed = int(continued_state.get("gameSeed", seed + game_index) or seed + game_index)
            p1_policy = continued_state.get("p1Policy")
            p2_policy = continued_state.get("p2Policy")
            engine = continued_state.get("engine")
            actions = int(continued_state.get("actions", 0) or 0)
            if engine is None or p1_policy is None or p2_policy is None:
                continued_state = None
                continue
            _prepare_continued_batched_policy(
                p1_policy,
                request_queue=request_queue,
                reply_queue=reply_queue,
                run_id=run_id,
                pool_plan=pool_plan,
            )
            _prepare_continued_batched_policy(
                p2_policy,
                request_queue=request_queue,
                reply_queue=reply_queue,
                run_id=run_id,
                pool_plan=pool_plan,
            )
            drain_this_game = _should_drain_rollout_pool_to_terminal(
                str(pool_plan["poolKind"]),
                drain_to_terminal=drain_to_terminal,
                original_drain_to_terminal=original_drain_to_terminal,
                selfplay_drain_to_terminal=selfplay_drain_to_terminal,
            )
            begin_turn = False
            rolling_continued_games += 1
            continued_state = None
        else:
            game_index = next_game_index
            global_game_index = game_index * env_count + int(config.get("globalSlotOffset", 0) or 0) + int(worker_index)
            gate_task = gate_task_specs[int(global_game_index)] if int(global_game_index) < len(gate_task_specs) else None
            if gate_task_specs and gate_task is None:
                break
            task_id = str((gate_task or {}).get("taskId") or _vector_default_task_id(run_id, global_game_index))
            pool_plan = (
                _rollout_pool_game_plan_from_gate_task(gate_task, actor_policy_id=actor_id)
                if gate_task is not None
                else _rollout_pool_game_plan(
                    global_game_index=global_game_index,
                    actor_policy_id=actor_id,
                    original_opponent_policy_ids=original_opponents,
                    selfplay_games_per_pool=selfplay_games_per_pool,
                    original_games_per_pool=original_games_per_pool,
                    gate_deck_pool_payloads=gate_deck_pool_payloads,
                    training_pool_schedule=training_pool_schedule,
                    training_pool_schedule_cycle_index=training_pool_schedule_cycle_index,
                )
            )
            game_seed = int((gate_task or {}).get("seed", seed + game_index)) if gate_task is not None else seed + game_index
            drain_this_game = _should_drain_rollout_pool_to_terminal(
                str(pool_plan["poolKind"]),
                drain_to_terminal=drain_to_terminal,
                original_drain_to_terminal=original_drain_to_terminal,
                selfplay_drain_to_terminal=selfplay_drain_to_terminal,
            )
            batched_actor_ids = _batched_actor_policy_ids_from_config(config, default_actor_policy_id=actor_id)
            actor_sides = _batched_actor_sides_for_pool_plan(pool_plan, batched_actor_ids=batched_actor_ids)
            batched_kwargs = {
                "worker_index": worker_index,
                "run_id": run_id,
                "task_id": task_id,
                "request_queue": request_queue,
                "reply_queue": reply_queue,
                "action_set_max_actions": int(config.get("actionSetMaxActions", 128) or 128),
                "compact_action_rows": bool(config.get("compactActionRows", True)),
                "selection_mode": str(config.get("selectionMode") or "sampled_from_logits"),
                "temperature": float(config.get("temperature", 1.0) or 1.0),
                "source_suite_kind": str(pool_plan["sourceSuiteKind"]),
                "difficulty": str(pool_plan["difficulty"]),
                "rollout_pool_kind": str(pool_plan["poolKind"]),
                "p1_policy_id": str(pool_plan["p1PolicyId"]),
                "p2_policy_id": str(pool_plan["p2PolicyId"]),
                "p1_deck_id": str(pool_plan["p1DeckId"]),
                "p2_deck_id": str(pool_plan["p2DeckId"]),
                "p1_deck_source": str(pool_plan["p1DeckSource"]),
                "p2_deck_source": str(pool_plan["p2DeckSource"]),
            }
            p1_policy = (
                _BatchedActorPolicy(
                    **batched_kwargs,
                    side="P1",
                    actor_policy_id=str(pool_plan["p1PolicyId"]),
                    runtime_opponent_policy_id=str(pool_plan["p2PolicyId"]),
                    rng=random.Random(game_seed + 11),
                )
                if "P1" in actor_sides
                else create_rollout_policy(
                    policy_id=str(pool_plan["p1PolicyId"]),
                    seed=game_seed + 11,
                    cache=policy_cache,
                )
            )
            p2_policy = (
                _BatchedActorPolicy(
                    **batched_kwargs,
                    side="P2",
                    actor_policy_id=str(pool_plan["p2PolicyId"]),
                    runtime_opponent_policy_id=str(pool_plan["p1PolicyId"]),
                    rng=random.Random(game_seed + 29),
                )
                if "P2" in actor_sides
                else create_rollout_policy(
                    policy_id=str(pool_plan["p2PolicyId"]),
                    seed=game_seed + 29,
                    cache=policy_cache,
                )
            )
            engine, _p1 = _setup_game(
                game_seed,
                p1_policy=p1_policy,
                p2_policy=p2_policy,
                p1_recipe=_deck_payload_recipe(pool_plan.get("p1Deck")),
                p2_recipe=_deck_payload_recipe(pool_plan.get("p2Deck")),
                p1_forces=_deck_payload_forces(pool_plan.get("p1Deck")),
                p2_forces=_deck_payload_forces(pool_plan.get("p2Deck")),
            )
            actions = 0
            begin_turn = True
        winner = "tie"
        terminal = False
        truncated_episode = False
        carry_episode = False
        hard_max_action_truncated_episode = False
        boundary_bootstrap_values: dict[str, float | None] = {}
        try:
            loop_started = time.perf_counter()
            if begin_turn:
                engine.begin_turn()
            while actions < max_game_actions:
                active_player = getattr(engine.state, "active", None)
                policy = engine.policy_for(active_player)
                local_reward_before = _local_reward_snapshot(engine, active_player)
                local_reward_row_index = len(policy.rows) if isinstance(policy, _BatchedActorPolicy) else None
                action = policy.choose(engine)
                try:
                    engine.apply(action)
                except GameOver:
                    _annotate_local_step_reward(
                        policy,
                        row_index=local_reward_row_index,
                        reward=_local_step_reward(
                            before=local_reward_before,
                            engine=engine,
                            player=active_player,
                            action=action,
                        ),
                    )
                    raise
                _annotate_local_step_reward(
                    policy,
                    row_index=local_reward_row_index,
                    reward=_local_step_reward(
                        before=local_reward_before,
                        engine=engine,
                        player=active_player,
                        action=action,
                    ),
                )
                actions += 1
                current_rows_so_far = sum(len(policy.rows) for policy in _batched_policies(p1_policy, p2_policy))
                if not drain_this_game and decisions + current_rows_so_far >= target_steps:
                    winner = "truncated"
                    truncated_episode = True
                    carry_episode = bool(use_rolling_state)
                    break
            profile["gameLoopSeconds"] += time.perf_counter() - loop_started
        except GameOver as game_over:
            profile["gameLoopSeconds"] += time.perf_counter() - loop_started
            winner = game_over.winner.name if game_over.winner else "tie"
            terminal = True
        if not terminal and not truncated_episode and actions >= max_game_actions:
            winner = "truncated"
            truncated_episode = True
            hard_max_action_truncated_episode = True
        if truncated_episode:
            boundary_bootstrap_values = _boundary_bootstrap_values(
                engine,
                policies=_batched_policies(p1_policy, p2_policy),
            )
        rows = [row for policy in _batched_policies(p1_policy, p2_policy) for row in policy.rows]
        if carry_episode:
            fixed_step_carried_rows += len(rows)
        if hard_max_action_truncated_episode:
            hard_max_action_truncated_games += 1
            hard_max_action_truncated_rows += len(rows)
            hard_max_action_truncated_by_pool.update([str(pool_plan["poolKind"])])
            hard_max_action_truncated_by_deck_pair.update(
                [f"{pool_plan['p1DeckId']}->{pool_plan['p2DeckId']}"]
            )
        row_started = time.perf_counter()
        rows_by_side: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            rows_by_side.setdefault(_actor_side_from_row(row), []).append(row)
        for actor_side, side_rows in rows_by_side.items():
            last_side_index = len(side_rows) - 1
            for side_index, row in enumerate(side_rows):
                is_last = side_index == last_side_index
                truncated = bool(truncated_episode and is_last)
                if hard_max_action_truncated_episode and truncated and boundary_bootstrap_values.get(str(actor_side)) is not None:
                    hard_max_action_rows_with_bootstrap += 1
                done = bool(terminal and is_last)
                trajectory_rows.append(
                    _trajectory_row_from_actor_row(
                        row,
                        current_policy_id=str(row.get("actorPolicyId") or actor_id),
                        winner=winner,
                        task_id=task_id,
                        episode_index=game_index,
                        decision_index=side_index,
                        source_index=side_index,
                        done=done,
                        truncated=truncated,
                        bootstrap_state_value=(
                            boundary_bootstrap_values.get(str(actor_side))
                            if truncated
                            else None
                        ),
                    )
                )
                if bridge_decisions < max_bridge_decisions:
                    bridge_rows.extend(_bridge_rows_from_actor_row(row))
                    bridge_decisions += 1
        decisions += len(rows)
        if carry_episode:
            next_rolling_state = {
                "nextGameIndex": int(game_index),
                "engine": engine,
                "p1Policy": p1_policy,
                "p2Policy": p2_policy,
                "poolPlan": dict(pool_plan),
                "gateTask": dict(gate_task) if isinstance(gate_task, Mapping) else None,
                "taskId": task_id,
                "gameSeed": int(game_seed),
                "gameIndex": int(game_index),
                "globalGameIndex": int(global_game_index),
                "actions": int(actions),
            }
            for policy in _batched_policies(p1_policy, p2_policy):
                policy.rows.clear()
            rolling_carried_games += 1
        else:
            games += 1
            next_game_index = int(game_index) + 1
            game_rows.append(
                _gate_game_row_from_vector_game(
                    task=gate_task,
                    task_id=task_id,
                    run_id=run_id,
                    seed=game_seed,
                    worker_index=worker_index,
                    game_index=game_index,
                    winner=winner,
                    actions=actions,
                    pool_plan=pool_plan,
                    actor_row_count=len(rows),
                )
            )
            pool_games.update([str(pool_plan["poolKind"])])
        pool_trajectory_rows.update({str(pool_plan["poolKind"]): len(rows)})
        profile["rowBuildSeconds"] += time.perf_counter() - row_started
        profile["gameTotalSeconds"] += time.perf_counter() - game_started
        if carry_episode:
            break
    if use_rolling_state and next_rolling_state is None:
        next_rolling_state = {"nextGameIndex": int(next_game_index)}
    return {
        "trajectoryRows": trajectory_rows,
        "bridgeRows": bridge_rows,
        "gameRows": game_rows,
        "games": int(games),
        "decisions": int(decisions),
        "poolGames": dict(pool_games),
        "poolTrajectoryRows": dict(pool_trajectory_rows),
        "profile": dict(profile),
        "rollingState": next_rolling_state,
        "rollingContinuedGames": int(rolling_continued_games),
        "rollingCarriedGames": int(rolling_carried_games),
        "fixedStepCarriedRows": int(fixed_step_carried_rows),
        "hardMaxActionTruncatedGames": int(hard_max_action_truncated_games),
        "hardMaxActionTruncatedRows": int(hard_max_action_truncated_rows),
        "hardMaxActionRowsWithBootstrap": int(hard_max_action_rows_with_bootstrap),
        "hardMaxActionTruncatedByPool": dict(hard_max_action_truncated_by_pool),
        "hardMaxActionTruncatedByDeckPair": dict(hard_max_action_truncated_by_deck_pair),
    }


def _vector_default_task_id(run_id: str, global_game_index: int) -> str:
    return f"{run_id}:game-{int(global_game_index)}"


class _BatchedActorPolicy:
    def __init__(
        self,
        *,
        worker_index: int,
        side: str,
        run_id: str,
        task_id: str,
        actor_policy_id: str,
        request_queue: Any,
        reply_queue: Any,
        rng: random.Random,
        action_set_max_actions: int,
        compact_action_rows: bool,
        selection_mode: str,
        temperature: float,
        runtime_opponent_policy_id: str,
        source_suite_kind: str,
        difficulty: str,
        rollout_pool_kind: str,
        p1_policy_id: str,
        p2_policy_id: str,
        p1_deck_id: str,
        p2_deck_id: str,
        p1_deck_source: str,
        p2_deck_source: str,
    ) -> None:
        self.worker_index = int(worker_index)
        self.side = str(side)
        self.run_id = str(run_id)
        self.task_id = str(task_id)
        self.actor_policy_id = str(actor_policy_id)
        self.request_queue = request_queue
        self.reply_queue = reply_queue
        self.rng = rng
        self.action_set_max_actions = int(action_set_max_actions)
        self.compact_action_rows = bool(compact_action_rows)
        self.selection_mode = str(selection_mode)
        self.temperature = float(temperature)
        self.runtime_opponent_policy_id = str(runtime_opponent_policy_id)
        self.source_suite_kind = str(source_suite_kind)
        self.difficulty = str(difficulty)
        self.rollout_pool_kind = str(rollout_pool_kind)
        self.p1_policy_id = str(p1_policy_id)
        self.p2_policy_id = str(p2_policy_id)
        self.p1_deck_id = str(p1_deck_id)
        self.p2_deck_id = str(p2_deck_id)
        self.p1_deck_source = str(p1_deck_source)
        self.p2_deck_source = str(p2_deck_source)
        self.rows: list[dict[str, Any]] = []
        self._request_index = 0
        self._action_set_direct_history: list[dict[str, Any]] = []

    def begin_rollout_segment(
        self,
        *,
        request_queue: Any,
        reply_queue: Any,
        run_id: str,
        actor_policy_id: str,
        runtime_opponent_policy_id: str,
        p1_policy_id: str,
        p2_policy_id: str,
    ) -> None:
        self.request_queue = request_queue
        self.reply_queue = reply_queue
        self.run_id = str(run_id)
        self.actor_policy_id = str(actor_policy_id)
        self.runtime_opponent_policy_id = str(runtime_opponent_policy_id)
        self.p1_policy_id = str(p1_policy_id)
        self.p2_policy_id = str(p2_policy_id)
        self.rows.clear()

    def choose(self, engine: Any) -> Action:
        legal = engine.legal_actions()
        if not legal:
            raise RuntimeError("no legal action")
        return self._choose_action(engine, self._player_for_side(engine), legal, decision_kind="main")

    def choose_flash(self, engine: Any, legal: list[Action]) -> Action:
        if not legal:
            raise RuntimeError("no legal flash action")
        return self._choose_action(engine, self._player_for_side(engine), legal, decision_kind="flash")

    def choose_blocker(self, engine: Any, attacker: Any, blockers: list[Any]):
        if not blockers:
            return None
        player = self._player_for_side(engine)
        choices = [None] + list(blockers)
        actions = [
            Action(kind="choose_blocker", payload=_choice_payload(choice, extra={"attacker": _choice_payload(attacker)}))
            for choice in choices
        ]
        slot = self._choose_slot(engine, player, actions, decision_kind="blocker")
        return choices[int(slot)]

    def choose_attack_target(self, engine: Any, attacker: Any, targets: list[Any]) -> Any:
        player = getattr(attacker, "owner", self._player_for_side(engine))
        actions = [
            Action(
                kind="choose_attack_target",
                payload=_choice_payload(target, extra={"attacker": _choice_payload(attacker)}),
            )
            for target in targets
        ]
        slot = self._choose_slot(engine, player, actions, decision_kind="attack_target")
        return targets[int(slot)]

    def choose_target(self, engine: Any, kind: str, min_n: int, max_n: int, eligible: list[Any]) -> list[Any]:
        if not eligible or int(max_n) <= 0:
            return []
        player = target_selection_player_for_context(engine)
        remaining = list(eligible)
        selected: list[Any] = []
        count = max(int(min_n), min(int(max_n), len(remaining)))
        while remaining and len(selected) < count:
            actions = [
                Action(
                    kind="choose_target",
                    payload=_choice_payload(target, extra={"target_kind": str(kind)}),
                )
                for target in remaining
            ]
            slot = self._choose_slot(engine, player, actions, decision_kind="generic_target")
            selected.append(remaining.pop(int(slot)))
        return selected

    def choose_mulligan(self, engine: Any, player: Any) -> list[Any]:
        return [card for card in list(getattr(player, "hand", []) or []) if self.rng.random() < 0.3]

    def _choose_action(self, engine: Any, player: Any, actions: list[Action], *, decision_kind: str) -> Action:
        slot = self._choose_slot(engine, player, actions, decision_kind=decision_kind)
        return actions[int(slot)]

    def _choose_slot(self, engine: Any, player: Any, actions: list[Action], *, decision_kind: str) -> int:
        original_action_count = len(actions)
        if original_action_count > self.action_set_max_actions:
            actions = actions[: self.action_set_max_actions]
        row_max_actions = len(actions) if self.compact_action_rows else self.action_set_max_actions
        request_index = int(self._request_index)
        request_id = f"{self.task_id}:d{request_index}"
        self._request_index += 1
        metadata = self._metadata(engine, player, decision_kind=decision_kind)
        if original_action_count > len(actions):
            metadata["actionSetOriginalLegalCount"] = int(original_action_count)
            metadata["actionSetCappedToMaxActions"] = int(len(actions))
        row = build_action_set_teacher_row(
            engine,
            player,
            list(actions),
            teacher_scores=[0.0 for _action in actions],
            selected_action_slot=0,
            max_actions=row_max_actions,
            decision_kind=decision_kind,
            raw_scores=[0.0 for _action in actions],
            metadata=metadata,
            history_context=self._direct_action_set_history_context(metadata),
        )
        row["runId"] = self.run_id
        row["sourceLabelRunId"] = self.run_id
        row["taskId"] = self.task_id
        row["actorDecisionId"] = request_id
        row["bridgeDecisionId"] = request_id
        metadata = dict(row.get("metadata") if isinstance(row.get("metadata"), Mapping) else {})
        recurrent_aliases = self._recurrent_aliases(player, step_index=request_index)
        row.update(recurrent_aliases)
        metadata["actorDecisionId"] = request_id
        metadata["bridgeDecisionId"] = request_id
        metadata.update(recurrent_aliases)
        row["metadata"] = metadata
        self.request_queue.put(
            {
                "kind": "decision",
                "workerIndex": self.worker_index,
                "requestId": request_id,
                "actorPolicyId": self.actor_policy_id,
                "row": _scoring_request_row(row),
            }
        )
        reply = self.reply_queue.get(timeout=30.0)
        if str(reply.get("kind") or "") != "decision_result":
            raise RuntimeError(f"unexpected decision reply: {reply}")
        selected = int(reply["slot"])
        selected_row = _apply_selection_to_row(
            row,
            reply,
            actor_policy_id=self.actor_policy_id,
            selection_mode=self.selection_mode,
            temperature=self.temperature,
        )
        self.rows.append(selected_row)
        self._append_direct_action_history(actions[selected], decision_kind=str(row.get("decisionKind") or decision_kind))
        return selected

    def boundary_state_value(self, engine: Any) -> float | None:
        player = self._player_for_side(engine)
        actions = list(engine.legal_actions()) if getattr(getattr(engine, "state", None), "active", None) is player else [Action(kind="end_turn")]
        if not actions:
            actions = [Action(kind="end_turn")]
        if len(actions) > self.action_set_max_actions:
            actions = actions[: self.action_set_max_actions]
        row = build_action_set_teacher_row(
            engine,
            player,
            list(actions),
            teacher_scores=[0.0 for _action in actions],
            selected_action_slot=0,
            max_actions=(len(actions) if self.compact_action_rows else self.action_set_max_actions),
            decision_kind="bootstrap_value",
            raw_scores=[0.0 for _action in actions],
            metadata=self._metadata(engine, player, decision_kind="bootstrap_value"),
            history_context=self._direct_action_set_history_context(
                self._metadata(engine, player, decision_kind="bootstrap_value")
            ),
        )
        request_id = f"{self.task_id}:bootstrap:{self.side}:{self._request_index}"
        recurrent_aliases = self._recurrent_aliases(player, step_index=int(self._request_index))
        self._request_index += 1
        metadata = dict(row.get("metadata") if isinstance(row.get("metadata"), Mapping) else {})
        row.update(recurrent_aliases)
        metadata.update(recurrent_aliases)
        row["metadata"] = metadata
        self.request_queue.put(
            {
                "kind": "value",
                "workerIndex": self.worker_index,
                "requestId": request_id,
                "actorPolicyId": self.actor_policy_id,
                "row": _scoring_request_row(row),
            }
        )
        reply = self.reply_queue.get(timeout=30.0)
        if str(reply.get("kind") or "") != "value_result":
            raise RuntimeError(f"unexpected value reply: {reply}")
        return float(reply["stateValue"])

    def _recurrent_aliases(self, player: Any, *, step_index: int) -> dict[str, Any]:
        side = _side_name(player) or self.side
        runtime_key = f"slot:{self.worker_index}:{side}"
        return {
            "sequenceId": f"{self.task_id}:{side}",
            "episodeId": self.task_id,
            "runtimeRecurrentKey": runtime_key,
            "episodeStepIndex": int(step_index),
            "resetHiddenState": int(step_index) == 0,
            "lossMask": True,
        }

    def _metadata(self, engine: Any, player: Any, *, decision_kind: str) -> dict[str, Any]:
        side = _side_name(player) or self.side
        player_deck_id = self.p1_deck_id if side == "P1" else self.p2_deck_id
        opponent_deck_id = self.p2_deck_id if side == "P1" else self.p1_deck_id
        player_deck_source = self.p1_deck_source if side == "P1" else self.p2_deck_source
        opponent_deck_source = self.p2_deck_source if side == "P1" else self.p1_deck_source
        state = getattr(engine, "state", None)
        active_side = _side_name(getattr(state, "active", None))
        turn_value = getattr(state, "turn", None)
        turn_index = _optional_int(turn_value)
        phase_value = _enum_value_text(getattr(state, "phase", None))
        step_value = _enum_value_text(getattr(state, "step", None))
        return {
            "runId": self.run_id,
            "taskId": self.task_id,
            "rolloutBackend": VECTOR_ROLLOUT_BACKEND,
            "workerIndex": self.worker_index,
            "decisionKind": str(decision_kind),
            "sourceSuiteKind": self.source_suite_kind,
            "suiteKind": self.source_suite_kind,
            "difficulty": self.difficulty,
            "rolloutPoolKind": self.rollout_pool_kind,
            "sequenceId": f"{self.task_id}:{side}",
            "runtimeRecurrentKey": f"slot:{self.worker_index}:{side}",
            "episodeId": self.task_id,
            "gameId": self.task_id,
            "trueTurnOrder": "first" if side == "P1" else "second",
            "turnIndex": turn_index,
            "gameTurn": turn_index,
            "gamePhase": phase_value,
            "gameStep": step_value,
            "activeSide": active_side,
            "turnPhaseWindow": f"turn:{turn_index}|phase:{phase_value}|step:{step_value}|active:{active_side}",
            "teacherScoreMode": "direct_action_set_scorer",
            "directActionSetPolicy": True,
            "actorPolicyId": self.actor_policy_id,
            "oldPolicyId": self.actor_policy_id,
            "sourceActorPolicyId": self.actor_policy_id,
            "currentPolicySourceActorPolicyId": self.actor_policy_id,
            "runtimeCandidatePolicyId": self.actor_policy_id,
            "currentPolicyCandidatePolicyId": self.actor_policy_id,
            "runtimePolicyId": self.actor_policy_id,
            "policyId": self.actor_policy_id,
            "subjectPolicyId": self.actor_policy_id,
            "runtimeActorSide": side,
            "modelSide": side,
            "subjectModelSide": side,
            "p1PolicyId": self.p1_policy_id,
            "p2PolicyId": self.p2_policy_id,
            "p1DeckId": self.p1_deck_id,
            "p2DeckId": self.p2_deck_id,
            "p1DeckSource": self.p1_deck_source,
            "p2DeckSource": self.p2_deck_source,
            "playerDeckId": player_deck_id,
            "modelDeckId": player_deck_id,
            "opponentDeckId": opponent_deck_id,
            "playerDeckSource": player_deck_source,
            "opponentDeckSource": opponent_deck_source,
            "deckSource": player_deck_source,
            "deckDomainSource": _combined_deck_domain_source(player_deck_source, opponent_deck_source),
            "opponentPolicyId": self.runtime_opponent_policy_id,
            "runtimeOpponentPolicyId": self.runtime_opponent_policy_id,
            "subjectOpponentPolicyId": self.runtime_opponent_policy_id,
            "actorSelectionMode": self.selection_mode,
            "actorSelectionTemperature": float(self.temperature),
        }

    def _direct_action_set_history_context(self, metadata: Mapping[str, Any]) -> dict[str, Any]:
        context = _action_set_scorer_json_mapping(dict(metadata or {}))
        context["recentActions"] = [dict(item) for item in self._action_set_direct_history[-8:]]
        return context

    def _append_direct_action_history(self, action: Action, *, decision_kind: str) -> None:
        self._action_set_direct_history.append(
            {
                "kind": str(getattr(action, "kind", "unknown") or "unknown"),
                "decisionKind": str(decision_kind or "unknown"),
            }
        )
        if len(self._action_set_direct_history) > 8:
            del self._action_set_direct_history[:-8]

    def _player_for_side(self, engine: Any) -> Player:
        for player in list(getattr(getattr(engine, "state", None), "players", []) or []):
            if _side_name(player) == self.side:
                return player
        return getattr(getattr(engine, "state", None), "active", None)


def _apply_selection_to_row(
    row: Mapping[str, Any],
    reply: Mapping[str, Any],
    *,
    actor_policy_id: str,
    selection_mode: str,
    temperature: float,
) -> dict[str, Any]:
    out = dict(row)
    metadata = dict(row.get("metadata") if isinstance(row.get("metadata"), Mapping) else {})
    logits = [float(value) for value in list(reply.get("actorLogits") or [])]
    selected_slot = int(reply["slot"])
    action_identities = action_identities_from_row(_row_with_actor_logits(out, actor_policy_id=actor_policy_id, logits=logits))
    selected_identity = str(reply.get("actorActionIdentity") or action_identities[selected_slot])
    top_slot = int(reply.get("actorTopSlot", selected_slot))
    top_identity = str(reply.get("actorTopActionIdentity") or action_identities[top_slot])
    updates = {
        "actorPolicyId": str(actor_policy_id),
        "sourceActorPolicyId": str(actor_policy_id),
        "currentPolicySourceActorPolicyId": str(actor_policy_id),
        "runtimeCandidatePolicyId": str(actor_policy_id),
        "currentPolicyCandidatePolicyId": str(actor_policy_id),
        "runtimePolicyId": str(actor_policy_id),
        "policyId": str(actor_policy_id),
        "subjectPolicyId": str(actor_policy_id),
        "actorSelectionMode": str(selection_mode),
        "actorSelectionTemperature": float(temperature),
        "actorActionSlot": int(selected_slot),
        "actorActionIdentity": selected_identity,
        "actorActionLogProb": float(reply["actorActionLogProb"]),
        "actorLogits": logits,
        "actorTopSlot": int(top_slot),
        "actorTopActionIdentity": top_identity,
        "teacherScoreMode": "direct_action_set_scorer",
        "directActionSetPolicy": True,
    }
    old_value = reply.get("oldPolicyStateValue")
    if old_value is not None:
        updates["oldPolicyStateValue"] = float(old_value)
        updates["actorStateValue"] = float(old_value)
    for key in (
        "runtimeRecurrentSequenceKey",
        "runtimeRecurrentRowKey",
        "runtimeRecurrentHiddenStateSource",
        "runtimeRecurrentInitialHiddenState",
        "runtimeRecurrentHiddenState",
    ):
        value = reply.get(key)
        if value is None:
            continue
        if key.endswith("HiddenState"):
            if not isinstance(value, list | tuple):
                continue
            vector: list[float] = []
            for item in value:
                parsed = _finite_float_or_none(item)
                if parsed is not None:
                    vector.append(float(parsed))
            if vector:
                updates[key] = vector
        else:
            text = str(value).strip()
            if text:
                updates[key] = text
    out.update(updates)
    metadata.update(updates)
    side = str(metadata.get("runtimeActorSide") or metadata.get("modelSide") or "").strip()
    if side in {"P1", "P2"}:
        metadata[f"{side.lower()}PolicyId"] = str(actor_policy_id)
    out["metadata"] = metadata
    out["selectedActionSlot"] = int(selected_slot)
    out["teacherTopSlot"] = int(top_slot)
    out["teacherScores"] = list(logits)
    out["rawScores"] = list(logits)
    if "legalMask" not in out:
        out["legalMask"] = [bool(value) for value in list(out.get("mask_") or [])]
    if "actionIdentities" not in out:
        out["actionIdentities"] = action_identities
    return out


def _trajectory_row_from_actor_row(
    row: Mapping[str, Any],
    *,
    current_policy_id: str,
    winner: str,
    task_id: str,
    episode_index: int,
    decision_index: int,
    source_index: int,
    done: bool,
    truncated: bool,
    bootstrap_state_value: float | None = None,
) -> dict[str, Any]:
    metadata = dict(row.get("metadata") if isinstance(row.get("metadata"), Mapping) else {})
    selected_slot = int(row.get("actorActionSlot", metadata.get("actorActionSlot", row.get("selectedActionSlot", 0))) or 0)
    log_prob = float(row.get("actorActionLogProb", metadata.get("actorActionLogProb", 0.0)) or 0.0)
    actor_side = str(metadata.get("runtimeActorSide") or metadata.get("modelSide") or row.get("modelSide") or "")
    run_id = str(row.get("runId") or metadata.get("runId") or "")
    episode_id = str(metadata.get("episodeId") or row.get("episodeId") or task_id)
    sequence_id = str(
        metadata.get("sequenceId")
        or row.get("sequenceId")
        or (f"{run_id}:{task_id}:{int(episode_index)}:{actor_side}" if run_id else f"{task_id}:{int(episode_index)}:{actor_side}")
    )
    episode_step_index = int(metadata.get("episodeStepIndex", row.get("episodeStepIndex", decision_index)) or 0)
    reset_hidden_state = bool(metadata.get("resetHiddenState", row.get("resetHiddenState", episode_step_index == 0)))
    terminal_reward = _reward_for_winner(winner=winner, actor_side=actor_side)
    step_reward = float(terminal_reward) if bool(done) else 0.0
    local_step_reward = _finite_float_or_none(
        row.get("trajectoryLocalStepReward", metadata.get("trajectoryLocalStepReward"))
    )
    if local_step_reward is None:
        local_step_reward = 0.0
    out = dict(row)
    out.update(
        {
            "schema": CURRENT_POLICY_TRAJECTORY_ROWS_SCHEMA,
            "rowSchema": CURRENT_POLICY_TRAJECTORY_ROWS_SCHEMA,
            "taskKind": "current_policy_sampled_rollout_trajectory",
            "labelKind": "trajectory_advantage",
            "teacherId": str(current_policy_id),
            "actorPolicyId": str(current_policy_id),
            "actionSlot": int(selected_slot),
            "selectedActionSlot": int(selected_slot),
            "episodeIndex": int(episode_index),
            "episodeId": episode_id,
            "sequenceId": sequence_id,
            "episodeStepIndex": int(episode_step_index),
            "resetHiddenState": bool(reset_hidden_state),
            "lossMask": True,
            "actionSetDecisionIndex": int(episode_step_index),
            "trajectoryDone": bool(done),
            "trajectoryTruncated": bool(truncated),
            "trajectoryStepReward": float(step_reward),
            "trajectoryLocalStepReward": float(local_step_reward),
            "trainingWeight": float(out.get("trainingWeight") or 1.0),
            "rowId": f"{task_id}:{out.get('stateKey')}:{int(source_index)}:{int(selected_slot)}",
            "trajectoryReturn": float(step_reward),
            "trajectoryAdvantage": float(step_reward),
        }
    )
    metadata.update(
        {
            "labelSource": "current_policy_sampled_episode_return",
            "actorPolicyId": str(current_policy_id),
            "sourceActorPolicyId": str(current_policy_id),
            "runtimePolicyId": str(current_policy_id),
            "runtimeCandidatePolicyId": str(current_policy_id),
            "actorSelectionMode": str(metadata.get("actorSelectionMode") or "sampled_from_logits"),
            "actorActionSlot": int(selected_slot),
            "actorActionLogProb": float(log_prob),
            "episodeIndex": int(episode_index),
            "episodeId": episode_id,
            "sequenceId": sequence_id,
            "episodeStepIndex": int(episode_step_index),
            "resetHiddenState": bool(reset_hidden_state),
            "lossMask": True,
            "actionSetDecisionIndex": int(episode_step_index),
            "trajectoryDone": bool(done),
            "trajectoryTruncated": bool(truncated),
            "trajectoryStepReward": float(step_reward),
            "trajectoryLocalStepReward": float(local_step_reward),
            "trajectoryRewardSource": "game_winner",
            "trajectoryWinner": str(winner),
            "trajectoryActorSide": actor_side,
        }
    )
    old_value = metadata.get("oldPolicyStateValue", metadata.get("actorStateValue"))
    label = {
        "labelVersion": CURRENT_POLICY_TRAJECTORY_ROWS_SCHEMA,
        "labelSource": "current_policy_sampled_episode_return",
        "selectedSlot": int(selected_slot),
        "returnValue": float(step_reward),
        "advantage": float(step_reward),
        "stepReward": float(step_reward),
        "localStepReward": float(local_step_reward),
        "terminalReturnValue": float(terminal_reward),
        "done": bool(done),
        "truncated": bool(truncated),
        "advantageMode": "episode_step_reward_pending_gae",
        "oldPolicyActionLogProb": float(log_prob),
    }
    if old_value is not None:
        label["oldPolicyStateValue"] = float(old_value)
        metadata["oldPolicyStateValue"] = float(old_value)
        metadata["actorStateValue"] = float(old_value)
    if bootstrap_state_value is not None:
        label["bootstrapStateValue"] = float(bootstrap_state_value)
        metadata["bootstrapStateValue"] = float(bootstrap_state_value)
        metadata["truncatedBootstrapStateValue"] = float(bootstrap_state_value)
    for key in (
        "playerDeckId",
        "modelDeckId",
        "opponentDeckId",
        "playerDeckSource",
        "opponentDeckSource",
        "deckSource",
        "deckDomainSource",
        "p1DeckId",
        "p2DeckId",
        "p1DeckSource",
        "p2DeckSource",
    ):
        if key in metadata:
            out[key] = metadata[key]
    out["metadata"] = metadata
    out["trajectoryPolicyLabel"] = label
    return out


def _bridge_rows_from_actor_row(row: Mapping[str, Any]) -> list[dict[str, Any]]:
    mask = [bool(value) for value in list(row.get("legalMask") or row.get("mask_") or [])]
    legal_slots = [index for index, enabled in enumerate(mask) if enabled]
    group_id = _full_legal_group_id(row)
    values = {str(slot): 0.0 for slot in legal_slots}
    rows: list[dict[str, Any]] = []
    for slot in legal_slots:
        out = dict(row)
        metadata = dict(row.get("metadata") if isinstance(row.get("metadata"), Mapping) else {})
        metadata.update(
            {
                "fullLegalActionSetGroup": True,
                "fullLegalActionSetGroupId": group_id,
                "fullLegalActionSetSize": int(len(legal_slots)),
                "fullLegalKnownSlots": [int(value) for value in legal_slots],
                "fullLegalActionValues": values,
                "fullLegalActionValueSampleCounts": {str(value): 1 for value in legal_slots},
                "fullLegalActionValueWinCounts": {str(value): 0 for value in legal_slots},
                "fullLegalActionValueLossCounts": {str(value): 0 for value in legal_slots},
                "fullLegalActionValueTieCounts": {str(value): 1 for value in legal_slots},
            }
        )
        out.update(
            {
                "schema": FULL_LEGAL_ACTION_VALUE_ROWS_SCHEMA,
                "rowSchema": FULL_LEGAL_ACTION_VALUE_ROWS_SCHEMA,
                "taskKind": "current_policy_full_legal_rollout_value",
                "labelKind": "action_value",
                "teacherId": "vector_batched_actor_rollout",
                "labelSource": "vector_batched_actor_rollout",
                "caseId": group_id,
                "actionSlot": int(slot),
                "action": _action_at_slot(row, slot),
                "label": {
                    "actionSlot": int(slot),
                    "actionValue": 0.0,
                    "fullLegalActionSetGroupId": group_id,
                },
                "metadata": metadata,
                "trainingWeight": 1.0,
            }
        )
        rows.append(out)
    return rows


def _row_with_actor_logits(
    row: Mapping[str, Any],
    *,
    actor_policy_id: str,
    logits: Sequence[float],
) -> dict[str, Any]:
    out = dict(row)
    metadata = dict(row.get("metadata") if isinstance(row.get("metadata"), Mapping) else {})
    out["actorPolicyId"] = str(actor_policy_id)
    out["actorLogits"] = [float(value) for value in logits]
    metadata["actorPolicyId"] = str(actor_policy_id)
    metadata["actorLogits"] = [float(value) for value in logits]
    out["metadata"] = metadata
    if "legalMask" not in out:
        out["legalMask"] = [bool(value) for value in list(out.get("mask_") or [])]
    return out


def _scoring_request_row(row: Mapping[str, Any]) -> dict[str, Any]:
    mask = [bool(value) for value in list(row.get("legalMask") or row.get("mask_") or [])]
    identities = action_identities_from_row(row)
    if len(identities) < len(mask):
        identities = identities + ["" for _index in range(len(mask) - len(identities))]
    actions = [
        {"kind": "slot", "payload": {"slot": int(index)}, "actionIdentity": str(identities[index])}
        for index in range(len(mask))
    ]
    metadata = dict(row.get("metadata") if isinstance(row.get("metadata"), Mapping) else {})
    slim = {
        "stateKey": row.get("stateKey"),
        "decisionKind": row.get("decisionKind"),
        "metadata": metadata,
        "globalFeatureNames": row.get("globalFeatureNames"),
        "historyFeatureNames": row.get("historyFeatureNames"),
        "actionFeatureNames": row.get("actionFeatureNames"),
        "cardFeatureNames": row.get("cardFeatureNames"),
        "global_": row.get("global_"),
        "history_": row.get("history_"),
        "actions_": row.get("actions_"),
        "cards_": row.get("cards_"),
        "mask_": list(mask),
        "legalMask": list(mask),
        "actions": actions,
        "actionIdentities": [str(value) for value in identities[: len(mask)]],
    }
    for key in (
        "sequenceId",
        "episodeId",
        "episodeStepIndex",
        "resetHiddenState",
        "lossMask",
        "sourceSuiteKind",
        "suiteKind",
        "difficulty",
        "rolloutPoolKind",
        "opponentPolicyId",
        "runtimeOpponentPolicyId",
        "runtimeActorSide",
        "trueTurnOrder",
        "playerDeckId",
        "opponentDeckId",
        "playerDeckSource",
        "opponentDeckSource",
        "deckDomainSource",
        "actorPolicyId",
        "oldPolicyId",
        "sourceActorPolicyId",
        "runtimePolicyId",
        "runtimeCandidatePolicyId",
    ):
        value = row.get(key)
        if value is None:
            value = metadata.get(key)
        if value is not None:
            slim[key] = value
    return slim


def _sample_slot_from_logits(
    *,
    logits: Sequence[float],
    legal_mask: Sequence[bool],
    rng: random.Random,
    temperature: float,
) -> tuple[int, float]:
    legal_slots = [index for index, enabled in enumerate(legal_mask) if bool(enabled)]
    if not legal_slots:
        raise ValueError("cannot sample from an empty legal mask")
    if float(temperature) <= 0.0:
        slot = max(legal_slots, key=lambda index: float(logits[index]))
        return int(slot), 0.0
    scaled = [float(logits[index]) / float(temperature) for index in legal_slots]
    max_scaled = max(scaled)
    weights = [math.exp(value - max_scaled) for value in scaled]
    total = sum(weights)
    if total <= 0.0 or not math.isfinite(total):
        raise ValueError("invalid policy softmax weights")
    threshold = rng.random() * total
    cumulative = 0.0
    for slot, weight in zip(legal_slots, weights, strict=True):
        cumulative += weight
        if threshold <= cumulative:
            prob = max(weight / total, 1.0e-300)
            return int(slot), float(math.log(prob))
    slot = legal_slots[-1]
    prob = max(weights[-1] / total, 1.0e-300)
    return int(slot), float(math.log(prob))


def _log_prob_for_slot(*, logits: Sequence[float], legal_mask: Sequence[bool], slot: int) -> float:
    legal_slots = [index for index, enabled in enumerate(legal_mask) if bool(enabled)]
    if int(slot) not in legal_slots:
        raise ValueError("cannot score an illegal selected slot")
    scaled = [float(logits[index]) for index in legal_slots]
    max_scaled = max(scaled)
    weights = [math.exp(value - max_scaled) for value in scaled]
    total = sum(weights)
    if total <= 0.0 or not math.isfinite(total):
        raise ValueError("invalid policy softmax weights")
    selected_weight = weights[legal_slots.index(int(slot))]
    return float(math.log(max(selected_weight / total, 1.0e-300)))


def _load_actor_scorer(path: str | Path, *, actor_policy_id: str) -> YgoStyleActionSetPolicyScorer:
    actor_path = Path(path)
    payload = load_current_policy_actor_artifact(
        actor_path,
        expected_candidate_policy_ids=[str(actor_policy_id)],
        context="vector actor rollout current policy actor",
    )
    return YgoStyleActionSetPolicyScorer.from_dict(payload)


def _batch_stats(batch_sizes: Sequence[int]) -> dict[str, Any]:
    sizes = [int(value) for value in batch_sizes if int(value) > 0]
    calls = len(sizes)
    decisions = sum(sizes)
    return {
        "decisionRequests": int(decisions),
        "inferenceBatchCalls": int(calls),
        "meanInferenceBatchSize": float(decisions) / float(calls) if calls else 0.0,
        "maxInferenceBatchSize": max(sizes) if sizes else 0,
    }


def _normalise_execution_backend(value: str | None) -> str:
    text = str(value or "process").strip().lower().replace("-", "_")
    if text in {"proc", "processes", "multiprocessing"}:
        return "process"
    if text in {"thread", "threads", "threading"}:
        return "thread"
    if text not in {"process", "thread"}:
        raise ValueError(f"unknown vector rollout execution backend: {value!r}")
    return text


def _spawn_context_for_backend(backend: str) -> Any | None:
    if _normalise_execution_backend(backend) != "process":
        return None
    install_hidden_multiprocessing_spawn()
    return mp.get_context("spawn")


def _reward_for_winner(*, winner: str, actor_side: str) -> float:
    if str(winner) not in {"P1", "P2"} or str(actor_side) not in {"P1", "P2"}:
        return 0.0
    return 1.0 if str(winner) == str(actor_side) else -1.0


def _local_reward_snapshot(engine: Any, player: Any) -> StateSnapshot | None:
    try:
        return StateSnapshot.from_engine(engine, player)
    except Exception:
        return None


def _local_step_reward(
    *,
    before: StateSnapshot | None,
    engine: Any,
    player: Any,
    action: Action,
) -> float:
    if before is None:
        return 0.0
    try:
        return float(calculate_step_reward(before, StateSnapshot.from_engine(engine, player), action))
    except Exception:
        return 0.0


def _annotate_local_step_reward(policy: Any, *, row_index: int | None, reward: float) -> None:
    if not isinstance(policy, _BatchedActorPolicy) or row_index is None:
        return
    index = int(row_index)
    if index < 0 or index >= len(policy.rows):
        return
    row = policy.rows[index]
    value = float(reward)
    row["trajectoryLocalStepReward"] = value
    metadata = dict(row.get("metadata") if isinstance(row.get("metadata"), Mapping) else {})
    metadata["trajectoryLocalStepReward"] = value
    row["metadata"] = metadata


def _finite_float_or_none(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _should_drain_rollout_pool_to_terminal(
    pool_kind: str,
    *,
    drain_to_terminal: bool,
    original_drain_to_terminal: bool,
    selfplay_drain_to_terminal: bool = False,
) -> bool:
    if bool(drain_to_terminal):
        return True
    pool = str(pool_kind)
    if bool(original_drain_to_terminal) and pool == "current_vs_original":
        return True
    return bool(selfplay_drain_to_terminal) and pool == "current_selfplay"


def _trajectory_terminal_signal_report(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    complete_rows: Counter[str] = Counter()
    truncated_rows: Counter[str] = Counter()
    bootstrap_rows: Counter[str] = Counter()
    positive_terminal_return_rows: Counter[str] = Counter()
    negative_terminal_return_rows: Counter[str] = Counter()
    zero_terminal_return_rows: Counter[str] = Counter()
    positive_terminal_games: Counter[str] = Counter()
    negative_terminal_games: Counter[str] = Counter()
    terminal_games: Counter[str] = Counter()
    seen_terminal_games: set[tuple[str, str]] = set()
    seen_terminal_return_games: set[tuple[str, str]] = set()
    for row in rows:
        metadata = row.get("metadata") if isinstance(row.get("metadata"), Mapping) else {}
        label = row.get("trajectoryPolicyLabel") if isinstance(row.get("trajectoryPolicyLabel"), Mapping) else {}
        pool = str(metadata.get("rolloutPoolKind") or row.get("rolloutPoolKind") or "unknown")
        suite = str(metadata.get("suiteKind") or row.get("suiteKind") or "unknown")
        domain = f"{pool}|{suite}"
        done = bool(row.get("trajectoryDone") or label.get("done") or metadata.get("trajectoryDone"))
        truncated = bool(
            row.get("trajectoryTruncated")
            or label.get("truncated")
            or metadata.get("trajectoryTruncated")
        )
        has_bootstrap = (
            label.get("bootstrapStateValue") is not None
            or label.get("truncatedBootstrapStateValue") is not None
            or metadata.get("bootstrapStateValue") is not None
            or metadata.get("truncatedBootstrapStateValue") is not None
        )
        terminal_return = _finite_float_or_none(label.get("terminalReturnValue", row.get("terminalReturnValue")))
        if terminal_return is not None:
            if terminal_return > 0.0:
                positive_terminal_return_rows.update([domain])
            elif terminal_return < 0.0:
                negative_terminal_return_rows.update([domain])
            else:
                zero_terminal_return_rows.update([domain])
        if done:
            complete_rows.update([domain])
            episode = str(metadata.get("episodeId") or row.get("episodeId") or row.get("taskId") or row.get("rowId") or "")
            terminal_key = (domain, episode)
            if terminal_key not in seen_terminal_games:
                seen_terminal_games.add(terminal_key)
                terminal_games.update([domain])
            terminal_return_key = (domain, f"{episode}:{metadata.get('runtimeActorSide') or row.get('modelSide') or ''}")
            if terminal_return is not None and terminal_return_key not in seen_terminal_return_games:
                seen_terminal_return_games.add(terminal_return_key)
                if terminal_return > 0.0:
                    positive_terminal_games.update([domain])
                elif terminal_return < 0.0:
                    negative_terminal_games.update([domain])
        if truncated:
            truncated_rows.update([domain])
        if has_bootstrap:
            bootstrap_rows.update([domain])
    return {
        "kind": "trajectory_terminal_signal_report_v1",
        "rowCount": int(len(rows)),
        "completeEpisodeRowsByDomain": dict(complete_rows),
        "truncatedRowsByDomain": dict(truncated_rows),
        "positiveTerminalReturnRowsByDomain": dict(positive_terminal_return_rows),
        "negativeTerminalReturnRowsByDomain": dict(negative_terminal_return_rows),
        "zeroTerminalReturnRowsByDomain": dict(zero_terminal_return_rows),
        "terminalGameCountByDomain": dict(terminal_games),
        "positiveTerminalGameCountByDomain": dict(positive_terminal_games),
        "negativeTerminalGameCountByDomain": dict(negative_terminal_games),
        "bootstrapRowsByDomain": dict(bootstrap_rows),
    }


def _boundary_bootstrap_values(
    engine: Any,
    *,
    policies: Sequence["_BatchedActorPolicy"],
) -> dict[str, float | None]:
    return {
        str(policy.side): policy.boundary_state_value(engine)
        for policy in list(policies)
    }


def _batched_policies(*policies: Any) -> list["_BatchedActorPolicy"]:
    return [policy for policy in list(policies) if isinstance(policy, _BatchedActorPolicy)]


def _rollout_pool_game_plan(
    *,
    global_game_index: int,
    actor_policy_id: str,
    original_opponent_policy_ids: Sequence[str],
    selfplay_games_per_pool: int,
    original_games_per_pool: int,
    gate_deck_pool_payloads: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
    training_pool_schedule: str = DEFAULT_TRAINING_POOL_SCHEDULE,
    training_pool_schedule_cycle_index: int = 0,
) -> dict[str, Any]:
    actor_id = str(actor_policy_id)
    opponents = tuple(str(value) for value in list(original_opponent_policy_ids or []) if str(value))
    schedule = _normalise_training_pool_schedule(training_pool_schedule)
    deck_pools = _normalise_gate_deck_pool_payloads(gate_deck_pool_payloads)
    selfplay_games = max(0, int(selfplay_games_per_pool))
    original_games = max(0, int(original_games_per_pool)) if opponents else 0
    pool_total = selfplay_games + original_games
    if pool_total <= 0:
        selfplay_games = 1
        pool_total = 1
    slot = int(global_game_index) % pool_total
    selfplay_before = (slot * selfplay_games) // pool_total
    selfplay_after = ((slot + 1) * selfplay_games) // pool_total
    is_selfplay_slot = selfplay_after > selfplay_before
    if is_selfplay_slot:
        pool_cycle = int(global_game_index) // pool_total
        selfplay_game_index = pool_cycle * selfplay_games + selfplay_before
        p1_deck, p2_deck = _selfplay_deck_payload_pair(
            selfplay_game_index=int(selfplay_game_index),
            deck_pools=deck_pools,
        )
        return {
            "poolKind": "current_selfplay",
            "sourceSuiteKind": "vector_self_play",
            "difficulty": "self_play",
            "currentActorSides": ("P1", "P2"),
            "p1PolicyId": actor_id,
            "p2PolicyId": actor_id,
            "opponentPolicyId": actor_id,
            "trainingPoolSchedule": schedule,
            "trainingPoolScheduleCycleIndex": int(training_pool_schedule_cycle_index),
            "p1DeckId": _deck_payload_id(p1_deck, default="runtime-p1"),
            "p2DeckId": _deck_payload_id(p2_deck, default="runtime-p2"),
            "p1DeckSource": _deck_payload_source(p1_deck),
            "p2DeckSource": _deck_payload_source(p2_deck),
            "p1Deck": p1_deck,
            "p2Deck": p2_deck,
        }
    original_index = slot - selfplay_before
    if schedule == EASY_TOP10_MATRIX_TRAINING_POOL_SCHEDULE:
        if opponents != (OLD_BASELINE_EASY_POLICY_ID,):
            raise ValueError(
                f"{EASY_TOP10_MATRIX_TRAINING_POOL_SCHEDULE} requires exactly "
                f"{OLD_BASELINE_EASY_POLICY_ID!r} as original opponent policy ids; got {opponents!r}"
            )
        current_side = "P1" if (original_index + int(training_pool_schedule_cycle_index)) % 2 == 0 else "P2"
        opponent_id = OLD_BASELINE_EASY_POLICY_ID
        suite_kind, player_deck, opponent_deck = _easy_top10_matrix_deck_payload_pair(
            original_index=original_index,
            deck_pools=deck_pools,
        )
    else:
        current_side = "P1" if original_index % 2 == 0 else "P2"
        opponent_id = opponents[original_index % len(opponents)]
        suite_kind, player_deck, opponent_deck = _original48_deck_payload_pair(
            original_index=original_index,
            opponent_count=len(opponents),
            deck_pools=deck_pools,
        )
    p1_deck = player_deck if current_side == "P1" else opponent_deck
    p2_deck = opponent_deck if current_side == "P1" else player_deck
    p1_policy_id = actor_id if current_side == "P1" else opponent_id
    p2_policy_id = opponent_id if current_side == "P1" else actor_id
    return {
        "poolKind": "current_vs_original",
        "sourceSuiteKind": suite_kind,
        "difficulty": "original_pool",
        "currentActorSides": (current_side,),
        "p1PolicyId": p1_policy_id,
        "p2PolicyId": p2_policy_id,
        "opponentPolicyId": opponent_id,
        "trainingPoolSchedule": schedule,
        "trainingPoolScheduleCycleIndex": int(training_pool_schedule_cycle_index),
        "playerDeckId": _deck_payload_id(player_deck, default="runtime-p1" if current_side == "P1" else "runtime-p2"),
        "opponentDeckId": _deck_payload_id(opponent_deck, default="runtime-p2" if current_side == "P1" else "runtime-p1"),
        "p1DeckId": _deck_payload_id(p1_deck, default="runtime-p1"),
        "p2DeckId": _deck_payload_id(p2_deck, default="runtime-p2"),
        "p1DeckSource": _deck_payload_source(p1_deck),
        "p2DeckSource": _deck_payload_source(p2_deck),
        "p1Deck": p1_deck,
        "p2Deck": p2_deck,
    }


def _rollout_pool_game_plan_from_gate_task(task: Mapping[str, Any], *, actor_policy_id: str) -> dict[str, Any]:
    spec = dict(task.get("taskSpec") or {})
    actor_id = str(spec.get("policyId") or actor_policy_id)
    opponent_id = str(spec.get("opponentPolicyId") or "")
    current_side = str(task.get("modelSide") or spec.get("modelSide") or "P1")
    if current_side not in {"P1", "P2"}:
        current_side = "P1"
    p1_policy_id = actor_id if current_side == "P1" else opponent_id
    p2_policy_id = opponent_id if current_side == "P1" else actor_id
    pool_kind = str(
        task.get("rolloutPoolKind")
        or spec.get("rolloutPoolKind")
        or spec.get("poolKind")
        or "current_vs_original"
    )
    current_actor_sides = (current_side,)
    if pool_kind == "current_selfplay" or (p1_policy_id == actor_id and p2_policy_id == actor_id):
        current_actor_sides = ("P1", "P2")
    p1_deck = dict(spec.get("p1Deck") or {})
    p2_deck = dict(spec.get("p2Deck") or {})
    player_deck_id = str(task.get("playerDeckId") or spec.get("playerDeckId") or "")
    opponent_deck_id = str(task.get("opponentDeckId") or spec.get("opponentDeckId") or "")
    return {
        "poolKind": pool_kind,
        "sourceSuiteKind": str(spec.get("suiteKind") or "unknown"),
        "difficulty": str(task.get("difficulty") or spec.get("difficulty") or "original_pool"),
        "currentActorSides": current_actor_sides,
        "p1PolicyId": p1_policy_id,
        "p2PolicyId": p2_policy_id,
        "opponentPolicyId": opponent_id,
        "playerDeckId": player_deck_id
        or _deck_payload_id(
            p1_deck if current_side == "P1" else p2_deck,
            default="runtime-p1" if current_side == "P1" else "runtime-p2",
        ),
        "opponentDeckId": opponent_deck_id
        or _deck_payload_id(
            p2_deck if current_side == "P1" else p1_deck,
            default="runtime-p2" if current_side == "P1" else "runtime-p1",
        ),
        "p1DeckId": _deck_payload_id(p1_deck, default="runtime-p1"),
        "p2DeckId": _deck_payload_id(p2_deck, default="runtime-p2"),
        "p1DeckSource": _deck_payload_source(p1_deck) or str(spec.get("playerDeckSource") or "runtime_default"),
        "p2DeckSource": _deck_payload_source(p2_deck) or str(spec.get("opponentDeckSource") or "runtime_default"),
        "p1Deck": p1_deck,
        "p2Deck": p2_deck,
        "gateTask": dict(task),
    }


def _gate_game_row_from_vector_game(
    *,
    task: Mapping[str, Any] | None,
    task_id: str,
    run_id: str,
    seed: int,
    worker_index: int,
    game_index: int,
    winner: str,
    actions: int,
    pool_plan: Mapping[str, Any],
    actor_row_count: int,
) -> dict[str, Any]:
    spec = dict((task or {}).get("taskSpec") or {})
    model_side = str((task or {}).get("modelSide") or spec.get("modelSide") or next(iter(pool_plan.get("currentActorSides") or ("P1",)), "P1"))
    p1_policy_id = str(pool_plan.get("p1PolicyId") or "")
    p2_policy_id = str(pool_plan.get("p2PolicyId") or "")
    winner_policy_id = p1_policy_id if winner == "P1" else p2_policy_id if winner == "P2" else None
    model_policy_won = str(winner) == model_side
    opponent_policy_won = str(winner) in {"P1", "P2"} and str(winner) != model_side
    result = {
        "taskId": str((task or {}).get("taskId") or task_id),
        "seed": int(seed),
        "workerId": f"vector-worker-{int(worker_index):02d}",
        "suiteKind": str(spec.get("suiteKind") or pool_plan.get("sourceSuiteKind") or "unknown"),
        "policyId": str(spec.get("policyId") or pool_plan.get("actorPolicyId") or pool_plan.get("p1PolicyId") or ""),
        "opponentPolicyId": str(spec.get("opponentPolicyId") or pool_plan.get("opponentPolicyId") or ""),
        "opponentBaselineLabel": str(spec.get("opponentBaselineLabel") or pool_plan.get("difficulty") or ""),
        "p1PolicyId": p1_policy_id,
        "p2PolicyId": p2_policy_id,
        "winnerPolicyId": winner_policy_id,
        "modelPolicyWon": bool(model_policy_won),
        "opponentPolicyWon": bool(opponent_policy_won),
        "p1DeckId": str(pool_plan.get("p1DeckId") or ""),
        "p2DeckId": str(pool_plan.get("p2DeckId") or ""),
        "playerDeckId": str((task or {}).get("playerDeckId") or pool_plan.get("playerDeckId") or ""),
        "opponentDeckId": str((task or {}).get("opponentDeckId") or pool_plan.get("opponentDeckId") or ""),
        "modelSide": model_side,
        "trueTurnOrder": str((task or {}).get("trueTurnOrder") or spec.get("trueTurnOrder") or ("first" if model_side == "P1" else "second")),
        "difficulty": str((task or {}).get("difficulty") or spec.get("difficulty") or pool_plan.get("difficulty") or ""),
        "playerDeckSource": str(spec.get("playerDeckSource") or pool_plan.get("p1DeckSource") or "runtime_default"),
        "opponentDeckSource": str(spec.get("opponentDeckSource") or pool_plan.get("p2DeckSource") or "runtime_default"),
        "deckSource": str(spec.get("deckSource") or spec.get("playerDeckSource") or "runtime_default"),
        "trainingPoolSchedule": str(pool_plan.get("trainingPoolSchedule") or DEFAULT_TRAINING_POOL_SCHEDULE),
        "trainingPoolScheduleCycleIndex": int(pool_plan.get("trainingPoolScheduleCycleIndex", 0) or 0),
        "policyMetadata": {"vectorGate": True, "runId": str(run_id), "gameIndex": int(game_index)},
        "actionSetInfluenceRuntime": _vector_gate_action_set_influence_runtime_stats(actor_row_count),
    }
    winner_value = str(winner) if str(winner) in {"P1", "P2", "tie"} else "error"
    error = None if winner_value != "error" else {"type": "VectorGateTruncatedGame", "message": str(winner)}
    return {
        "taskId": str((task or {}).get("taskId") or task_id),
        "gameIndex": int(game_index),
        "winner": winner_value,
        "turns": int(max(1, actions)),
        "error": error,
        "result": result,
    }


def _vector_gate_action_set_influence_runtime_stats(actor_row_count: int) -> dict[str, Any]:
    decisions = max(0, int(actor_row_count))
    return {
        "actionSetScorerDecisions": decisions,
        "actionSetScorerModelTopAgreements": decisions,
        "actionSetScorerModelTopDisagreements": 0,
        "actionSetScorerTopMarginSum": 0.0,
        "actionSetScorerTopMarginMax": 0.0,
        "actionSetScorerTopSelectionOpportunities": decisions,
        "actionSetScorerTopSelected": decisions,
        "actionSetScorerTopFinalScoreTop": decisions,
        "actionSetScorerRouteDecisions": decisions,
        "actionSetScorerRouteHits": decisions,
        "actionSetScorerRouteMisses": 0,
        "actionSetResidualScorerDecisions": 0,
        "actionSetResidualScorerTopMarginSum": 0.0,
        "actionSetResidualScorerTopMarginMax": 0.0,
        "actionSetSkipMctsDecisions": 0,
        "actionSetFastSelectDecisions": decisions,
        "actionSetTakeoverDecisions": decisions,
        "actionSetDirectDecisions": decisions,
        "actionSetDirectFallbacks": 0,
        "actionSetDirectErrors": 0,
    }


def _original48_deck_payload_pair(
    *,
    original_index: int,
    opponent_count: int,
    deck_pools: Mapping[str, Sequence[Mapping[str, Any]]],
) -> tuple[str, Mapping[str, Any] | None, Mapping[str, Any] | None]:
    player_decks = list(deck_pools.get("player") or [])
    top_decks = list(deck_pools.get("top10") or [])
    if not player_decks:
        return "vector_original_pool", None, None
    opponents = max(1, int(opponent_count))
    suites = ("mirror", "top10")
    per_suite = opponents * 2
    suite_index = (int(original_index) // per_suite) % len(suites)
    suite_kind = suites[suite_index]
    side_index = int(original_index) % 2
    repeat_index = int(original_index) // (per_suite * len(suites))
    side_stride = max(1, math.ceil(len(player_decks) / 2.0))
    slice_row_index = repeat_index + side_index * side_stride
    player_deck = player_decks[slice_row_index % len(player_decks)]
    if suite_kind == "mirror" or not top_decks:
        return suite_kind, player_deck, player_deck
    opponent_deck = top_decks[slice_row_index % len(top_decks)]
    return suite_kind, player_deck, opponent_deck


def _easy_top10_matrix_deck_payload_pair(
    *,
    original_index: int,
    deck_pools: Mapping[str, Sequence[Mapping[str, Any]]],
) -> tuple[str, Mapping[str, Any] | None, Mapping[str, Any] | None]:
    player_decks = list(deck_pools.get("player") or [])
    top_decks = list(deck_pools.get("top10") or [])
    if not player_decks:
        return "easy_top10_matrix_v1", None, None
    if not top_decks:
        player_deck = player_decks[int(original_index) % len(player_decks)]
        return "easy_top10_matrix_v1", player_deck, player_deck
    pair_count = len(player_decks) * len(top_decks)
    pair_index = int(original_index) % pair_count
    player_deck = player_decks[pair_index // len(top_decks)]
    opponent_deck = top_decks[pair_index % len(top_decks)]
    return "easy_top10_matrix_v1", player_deck, opponent_deck


def _selfplay_deck_payload_pair(
    *,
    selfplay_game_index: int,
    deck_pools: Mapping[str, Sequence[Mapping[str, Any]]],
) -> tuple[Mapping[str, Any] | None, Mapping[str, Any] | None]:
    player_decks = list(deck_pools.get("player") or [])
    if not player_decks:
        return None, None
    pair_count = len(player_decks) * len(player_decks)
    pair_index = int(selfplay_game_index) % pair_count
    left = player_decks[pair_index // len(player_decks)]
    right = player_decks[pair_index % len(player_decks)]
    return left, right


def _normalise_gate_deck_pool_payloads(value: Any) -> dict[str, tuple[Mapping[str, Any], ...]]:
    if not isinstance(value, Mapping):
        return {}
    out: dict[str, tuple[Mapping[str, Any], ...]] = {}
    for key in ("player", "top10"):
        rows = []
        for item in list(value.get(key) or []):
            if isinstance(item, Mapping):
                rows.append(dict(item))
        if rows:
            out[key] = tuple(rows)
    return out


def _copy_gate_deck_pool_payloads(
    value: Mapping[str, Sequence[Mapping[str, Any]]] | None,
) -> dict[str, list[dict[str, Any]]]:
    return {
        key: [dict(item) for item in list(items or []) if isinstance(item, Mapping)]
        for key, items in dict(value or {}).items()
        if key in {"player", "top10"}
    }


@lru_cache(maxsize=1)
def _default_gate_deck_pool_payloads() -> dict[str, tuple[Mapping[str, Any], ...]]:
    try:
        from zz.ai_deck_analysis import load_saved_decks
        from zz.deck_ai import load_top_suite_decks
        from zz.rollout_task_specs import deck_payload

        player_specs = list(load_saved_decks(None))[:8]
        top_specs = list(load_top_suite_decks("data/ai_training/top_deck_suite_v2_latest.json"))[:10]
    except Exception:
        return {}
    return {
        "player": tuple(_deck_payload_with_source(deck_payload(deck), source="player") for deck in player_specs),
        "top10": tuple(_deck_payload_with_source(deck_payload(deck), source="top_suite") for deck in top_specs),
    }


def _deck_payload_with_source(payload: Mapping[str, Any], *, source: str) -> dict[str, Any]:
    out = dict(payload)
    out["deckSource"] = str(source)
    return out


def _deck_payload_id(payload: Any, *, default: str) -> str:
    if isinstance(payload, Mapping):
        text = str(payload.get("deckId") or payload.get("id") or "").strip()
        if text:
            return text
    return str(default)


def _deck_payload_source(payload: Any) -> str:
    if isinstance(payload, Mapping):
        text = str(payload.get("deckSource") or payload.get("source") or "").strip()
        if text:
            return text
    return "runtime_default"


def _deck_payload_recipe(payload: Any) -> dict[str, int] | None:
    if not isinstance(payload, Mapping):
        return None
    recipe = payload.get("recipe")
    if not isinstance(recipe, Mapping):
        return None
    out: dict[str, int] = {}
    for card_id, count in recipe.items():
        try:
            parsed = int(count)
        except (TypeError, ValueError):
            continue
        if parsed > 0:
            out[str(card_id)] = parsed
    return out or None


def _deck_payload_forces(payload: Any) -> list[str] | None:
    if not isinstance(payload, Mapping):
        return None
    values = payload.get("forces")
    if not isinstance(values, list | tuple):
        return None
    out = [str(value) for value in values if str(value or "").strip()]
    return out or None


def _combined_deck_domain_source(player_source: str, opponent_source: str) -> str:
    player = str(player_source or "unknown")
    opponent = str(opponent_source or "unknown")
    if player == opponent:
        return player
    return f"{player}|{opponent}"


def _counter_mapping(value: Any) -> dict[str, int]:
    if not isinstance(value, Mapping):
        return {}
    out: dict[str, int] = {}
    for key, raw in value.items():
        try:
            out[str(key)] = int(raw)
        except (TypeError, ValueError):
            pass
    return out


def _append_mapping_rows(target: list[dict[str, Any]], rows: Any) -> None:
    if not rows:
        return
    row_iter = (rows,) if isinstance(rows, Mapping) else rows
    for row in row_iter:
        if isinstance(row, dict):
            target.append(row)
        elif isinstance(row, Mapping):
            target.append(dict(row))


def _float_counter_mapping(value: Any) -> dict[str, float]:
    if not isinstance(value, Mapping):
        return {}
    out: dict[str, float] = {}
    for key, raw in value.items():
        try:
            number = float(raw)
        except (TypeError, ValueError):
            continue
        if math.isfinite(number):
            out[str(key)] = number
    return out


def _actor_side_from_row(row: Mapping[str, Any]) -> str:
    metadata = row.get("metadata") if isinstance(row.get("metadata"), Mapping) else {}
    return str(metadata.get("runtimeActorSide") or metadata.get("modelSide") or row.get("modelSide") or "unknown")


def _old_state_value_from_row(row: Mapping[str, Any]) -> float | None:
    metadata = row.get("metadata") if isinstance(row.get("metadata"), Mapping) else {}
    label = row.get("trajectoryPolicyLabel") if isinstance(row.get("trajectoryPolicyLabel"), Mapping) else {}
    value = label.get("oldPolicyStateValue", metadata.get("oldPolicyStateValue", metadata.get("actorStateValue")))
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _choice_payload(choice: Any, *, extra: Mapping[str, Any] | None = None) -> dict[str, Any]:
    payload = dict(extra or {})
    if choice is None:
        payload["block_none"] = True
        return payload
    ref = getattr(choice, "ref", None)
    if ref is not None:
        kind = getattr(getattr(choice, "kind", ""), "name", getattr(choice, "kind", ""))
        payload["attack_target_kind"] = str(kind)
        payload.update(_choice_payload(ref))
        return payload
    card = getattr(choice, "card", None)
    iid = getattr(choice, "iid", None)
    if iid is not None:
        payload["iid"] = int(iid)
    if card is not None:
        payload["card_id"] = str(getattr(card, "id", ""))
        payload["bp"] = int(getattr(choice, "bp", getattr(card, "bp", 0)) or 0)
        payload["dp"] = int(getattr(choice, "dp", getattr(card, "dp", 0)) or 0)
        payload["rested"] = bool(getattr(choice, "rested", False))
    force = getattr(choice, "force", None)
    if force is not None:
        payload["force_id"] = str(getattr(force, "id", ""))
        payload["force_life"] = int(getattr(choice, "life", 0) or 0)
    owner = getattr(choice, "owner", None)
    if owner is not None:
        payload["owner"] = str(getattr(owner, "name", getattr(owner, "side", "")))
    if not payload and hasattr(choice, "name"):
        payload["name"] = str(getattr(choice, "name"))
    return payload


def _side_name(player: Any) -> str:
    side = getattr(player, "side", "")
    return str(getattr(side, "name", side))


def _enum_value_text(value: Any) -> str:
    return str(getattr(value, "value", getattr(value, "name", value)) or "unknown")


def _optional_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _action_at_slot(row: Mapping[str, Any], slot: int) -> Any:
    actions = row.get("actions")
    if isinstance(actions, Sequence) and not isinstance(actions, str | bytes) and 0 <= int(slot) < len(actions):
        return actions[int(slot)]
    return None


def _full_legal_group_id(row: Mapping[str, Any]) -> str:
    payload = {
        "runId": str(row.get("runId") or ""),
        "decisionId": str(row.get("bridgeDecisionId") or row.get("actorDecisionId") or ""),
        "stateKey": str(row.get("stateKey") or ""),
        "decisionKind": str(row.get("decisionKind") or ""),
        "actions": row.get("actions"),
        "mask": row.get("legalMask") or row.get("mask_"),
    }
    encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]


def _handle_worker_message(
    item: Mapping[str, Any],
    *,
    trajectory_rows: list[dict[str, Any]],
    bridge_rows: list[dict[str, Any]],
    errors: list[dict[str, Any]],
    counters: dict[str, int],
) -> None:
    kind = str(item.get("kind") or "")
    if kind == "worker_done":
        _append_mapping_rows(trajectory_rows, item.get("trajectoryRows"))
        _append_mapping_rows(bridge_rows, item.get("bridgeRows"))
        counters["games"] = int(counters.get("games", 0)) + int(item.get("games", 0) or 0)
        counters["decisions"] = int(counters.get("decisions", 0)) + int(item.get("decisions", 0) or 0)
    elif kind == "worker_error":
        errors.append(dict(item))


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
