from __future__ import annotations

import json
import os
import random
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

from zz.ai_registry import (
    DEFAULT_DEEP_MODEL_PATH,
    DEFAULT_NORMAL_MODEL_PATH,
    read_codeman_champion,
    write_codeman_champion,
)
from zz.ai_deck_analysis import DeckSpec
from zz.codeman_memory import CodemanMemoryStore
from zz.engine import GameOver
from zz.greedy_ai import GreedyLegalPolicy
from zz.rl_ai import LinearQModel, LookaheadRLPolicy, _utc_now, run_evaluation
from zz.rl_training import _action_summary, _memory_match_id_from_deck_id, _setup_game
from zz.rollout_task_specs import deck_payload


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CODEMAN_NATIVE_BASE_MODEL_PATH = PROJECT_ROOT / "local_ai_training" / "retained_mainline_20260630" / "cycle470_actor.json"


PRESET_ROUNDS = {
    "quick": 50,
    "standard": 200,
    "overnight": 1000,
}
GATE_MAX_TURNS = 30
GATE_MAX_ACTIONS = 500
CODEMAN_MEMORY_KEEP_AFTER_PROMOTION = 8
CODEMAN_STANDARD_TRAINING_EVAL_INTERVAL = 50
CODEMAN_LONG_TRAINING_EVAL_INTERVAL = 100
CODEMAN_MAX_ROLLOUT_WORKERS = 4
CODEMAN_PROGRESS_WRITE_ATTEMPTS = 5
CODEMAN_PROGRESS_WRITE_RETRY_SECONDS = 0.01
CODEMAN_CORRECTED_TRACE_WEIGHT = 4
CODEMAN_PRIMARY_IMITATION_EPOCHS = 8
CODEMAN_REFINEMENT_IMITATION_EPOCHS = 4
CODEMAN_MEMORY_IMITATION_TARGET = 0.9
CODEMAN_TACTICAL_PREFERENCE_WEIGHT = 2.0
CODEMAN_REFINEMENT_TACTICAL_PREFERENCE_WEIGHT = 3.0
CODEMAN_TACTICAL_PREFERENCE_MARGIN = 0.75
CODEMAN_OPPONENT_BEHAVIOR_PREFERENCE_WEIGHT = 2.0
CODEMAN_OPPONENT_BEHAVIOR_PREFERENCE_MARGIN = 0.75
CODEMAN_OPPONENT_BEHAVIOR_PREFERENCE_LEARNING_RATE = 0.0005
CODEMAN_PRIMARY_OPPONENT_BEHAVIOR_PREFERENCE_EPOCHS = 6
CODEMAN_REFINEMENT_OPPONENT_BEHAVIOR_PREFERENCE_EPOCHS = 4
CODEMAN_DEFAULT_CIRCLES = 10
CODEMAN_CIRCLE_GAMES = 100
CODEMAN_DEFAULT_CHECKPOINT_INTERVAL = 5
CODEMAN_NATIVE_TRAINING_METHODS = {
    "gae_epoch1_local",
    "vtrace_epoch2_native",
}


@dataclass(frozen=True)
class TrainingPreset:
    name: str
    rounds: int
    memory_games: int
    memory_weight: float


@dataclass(frozen=True)
class PromotionDecision:
    promoted: bool
    reasons: list[str]


@dataclass(frozen=True)
class WarmStartResolution:
    path: Path
    source: str


@dataclass(frozen=True)
class TrainingCheckpointSelection:
    path: Path
    report: dict[str, Any]


def expand_training_preset(
    preset: str,
    *,
    memory_games: int,
    rounds: int | None = None,
) -> TrainingPreset:
    name = str(preset or "standard").strip().lower()
    if name not in PRESET_ROUNDS:
        raise ValueError(f"unknown Codeman training preset: {preset!r}")
    return TrainingPreset(
        name=name,
        rounds=int(rounds if rounds is not None else PRESET_ROUNDS[name]),
        memory_games=max(0, int(memory_games)),
        memory_weight=_memory_weight(memory_games),
    )


def evaluate_promotion_gate(metrics: dict[str, Any]) -> PromotionDecision:
    reasons: list[str] = []
    if int(metrics.get("errors", 0)) > 0:
        reasons.append("candidate evaluation had errors")
    if float(metrics.get("greedyWinRate", 0.0)) <= 0.70:
        reasons.append("greedy win rate must be above 0.70")

    current = float(metrics.get("currentChampionWinRate", 0.0))
    candidate = float(metrics.get("candidateChampionWinRate", current))
    direct_champion_win_rate = float(metrics.get("candidateVsCurrentChampionWinRate", 0.0))
    has_direct_champion_check = "candidateVsCurrentChampionWinRate" in metrics
    directly_beats_current = has_direct_champion_check and direct_champion_win_rate > 0.50
    passes_current_champion_replacement = directly_beats_current
    has_current_champion = bool(metrics.get("hasCurrentChampion", has_direct_champion_check))
    first_personal_champion = bool(metrics.get("personalFirstChampion", False)) or (
        not has_current_champion and str(metrics.get("gateDeckSource") or "") == "memory_matchups"
    )
    if candidate < current - 0.03 and not passes_current_champion_replacement:
        reasons.append("candidate regressed more than 0.03 against current champion")

    if has_direct_champion_check and not passes_current_champion_replacement:
        reasons.append("candidate failed current champion replacement check")
    if "normalWinRate" in metrics:
        normal_floor = float(metrics.get("normalWinRateFloor", 0.50))
        if float(metrics.get("normalWinRate", 0.0)) <= normal_floor:
            reasons.append("normal benchmark win rate must be above 0.50")
    if "deepWinRate" in metrics:
        deep_floor = float(metrics.get("deepWinRateFloor", 0.50))
        deep_floor_is_explicit = "deepWinRateFloor" in metrics
        if (
            float(metrics.get("deepWinRate", 0.0)) <= deep_floor
            and not (first_personal_champion and not deep_floor_is_explicit)
        ):
            reasons.append("deep benchmark win rate must be above 0.50")

    target_improvement = float(metrics.get("targetImprovement", 0.0))
    second_player_improvement = float(metrics.get("secondPlayerImprovement", 0.0))
    direct_champion_improvement = float(metrics.get("directChampionImprovement", 0.0))
    if "candidateVsCurrentChampionWinRate" in metrics and "directChampionImprovement" not in metrics:
        direct_champion_improvement = float(metrics.get("candidateVsCurrentChampionWinRate", 0.0)) - 0.50
    if (
        target_improvement < 0.02
        and second_player_improvement < 0.03
        and direct_champion_improvement < 0.03
    ):
        reasons.append("candidate did not improve a target matchup")

    return PromotionDecision(promoted=not reasons, reasons=reasons)


def run_codeman_training(
    codeman_id: str,
    *,
    data_root: str | Path,
    warm_start_model_path: str | Path | None = None,
    normal_model_path: str | Path | None = None,
    deep_model_path: str | Path | None = None,
    preset: str = "standard",
    rounds: int | None = None,
    gate_metrics: dict[str, Any] | None = None,
    run_id: str | None = None,
    seed: int = 20260524,
    training_engine: str = "auto",
    eval_episodes: int | None = None,
    progress_path: str | Path | None = None,
    circles: int | None = None,
    training_method: str = "gae_epoch1_local",
    checkpoint_interval: int = CODEMAN_DEFAULT_CHECKPOINT_INTERVAL,
) -> dict[str, Any]:
    return _run_codeman_native_champion_training(
        codeman_id,
        data_root=data_root,
        warm_start_model_path=warm_start_model_path,
        run_id=run_id,
        seed=seed,
        progress_path=progress_path,
        circles=circles if circles is not None else rounds,
        training_method=training_method,
        checkpoint_interval=checkpoint_interval,
    )


def _run_codeman_native_champion_training(
    codeman_id: str,
    *,
    data_root: str | Path,
    warm_start_model_path: str | Path | None,
    run_id: str | None,
    seed: int,
    progress_path: str | Path | None,
    circles: int | None,
    training_method: str,
    checkpoint_interval: int,
) -> dict[str, Any]:
    data_root_path = Path(data_root)
    memory_store = CodemanMemoryStore(data_root_path)
    memory_rows = memory_store.read_games(codeman_id)
    memory_games = len(memory_rows)
    safe_id = _safe_codeman_id(codeman_id)
    run_name = run_id or _run_id()
    resolved_circles = max(1, int(circles if circles is not None else CODEMAN_DEFAULT_CIRCLES))
    resolved_checkpoint_interval = max(1, int(checkpoint_interval))
    resolved_method = _normalise_codeman_training_method(training_method)
    progress_callback = _codeman_progress_callback(
        progress_path,
        codeman_id=codeman_id,
        run_id=run_name,
        preset=resolved_method,
        total_episodes=resolved_circles,
    )
    _emit_progress(progress_callback, {
        "state": "running",
        "stage": "preparing",
        "episode": 0,
        "episodes": resolved_circles,
        "message": "Preparing Codeman training",
    })
    codeman_root = data_root_path / "codeman_ai" / safe_id
    candidate_dir = codeman_root / "candidates" / run_name
    candidate_dir.mkdir(parents=True, exist_ok=True)
    base_model_path, base_source = _resolve_codeman_native_warm_start(
        safe_id,
        data_root=data_root_path,
        explicit_model_path=warm_start_model_path,
    )
    candidate_path = candidate_dir / "candidate.json"
    deck_pool = _codeman_training_decks(memory_rows, seed=seed)
    deck_payloads = [_deck_payload_with_source(deck, source="codeman_memory") for deck in deck_pool]
    memory_replay_plan = _memory_replay_plan(
        memory_rows,
        config=TrainingPreset(name=resolved_method, rounds=resolved_circles, memory_games=memory_games, memory_weight=0.0),
        deck_pool_size=len(deck_pool),
        deck_matchup_size=len(deck_pool) * len(deck_pool),
        trace_path_count=0,
        opponent_control="codeman_native_selfplay",
    )
    try:
        training_report, training_report_path = _run_codeman_native_loop(
            out_dir=candidate_dir / "training",
            base_model_path=base_model_path,
            codeman_id=safe_id,
            run_id=run_name,
            method=resolved_method,
            circles=resolved_circles,
            checkpoint_interval=resolved_checkpoint_interval,
            seed=seed,
            deck_payloads=deck_payloads,
            progress_callback=progress_callback,
        )
    except Exception as exc:
        _emit_progress(progress_callback, {
            "state": "error",
            "stage": "error",
            "episode": 0,
            "episodes": resolved_circles,
            "percent": 100,
            "message": str(exc),
        })
        raise

    checkpoint_selection = _select_codeman_native_champion_checkpoint(
        training_report,
        baseline_model_path=DEFAULT_CODEMAN_NATIVE_BASE_MODEL_PATH,
        current_champion_path=_codeman_native_champion_path(safe_id, data_root=data_root_path),
        decks=deck_pool,
        replacement_matchups=_memory_deck_matchups(memory_rows, limit=8),
        seed=seed + 500000,
        selection_out_dir=candidate_dir / "selection",
    )
    selected_checkpoint = checkpoint_selection.path
    _materialize_candidate(
        selected_checkpoint,
        candidate_path,
        config=TrainingPreset(name=resolved_method, rounds=resolved_circles, memory_games=memory_games, memory_weight=0.0),
        engine="ygo_native_actor_value",
        codeman_id=safe_id,
        training_report=training_report,
    )
    checkpoint_cleanup = _cleanup_training_checkpoints(
        candidate_dir / "training",
        source_selected_checkpoint=selected_checkpoint,
        candidate_path=candidate_path,
    )
    memory_corrections_applied = 0

    _emit_progress(progress_callback, {
        "state": "running",
        "stage": "evaluating",
        "episode": resolved_circles,
        "episodes": resolved_circles,
        "percent": 95,
        "message": "Evaluating promotion gate",
    })
    resolved_metrics = dict(checkpoint_selection.report.get("replacementGate") or {})
    decision = PromotionDecision(
        promoted=bool(checkpoint_selection.report.get("promoted")),
        reasons=list(checkpoint_selection.report.get("reasons") or []),
    )
    memory_pruned_after_promotion = 0
    memory_games_after_promotion = memory_games
    if decision.promoted:
        write_codeman_champion(
            safe_id,
            checkpoint_path=candidate_path,
            model_kind="ygo_actor_value",
            data_root=data_root_path,
        )
        memory_games_after_promotion = len(memory_store.read_games(safe_id))
    champion_after_decision = read_codeman_champion(safe_id, data_root=data_root_path)
    champion_path_after_decision = _checkpoint_path_from_pointer(champion_after_decision, data_root_path)
    model_retention_cleanup = _cleanup_old_codeman_candidate_models(
        codeman_root,
        keep_candidate_paths=[candidate_dir, champion_path_after_decision],
    )
    training_dir_removed = _remove_tree(candidate_dir / "training")

    report = {
        "schema": 1,
        "kind": "codeman_training_run",
        "createdAt": _utc_now(),
        "codemanId": safe_id,
        "runId": run_name,
        "preset": resolved_method,
        "rounds": resolved_circles,
        "circles": resolved_circles,
        "circleGames": CODEMAN_CIRCLE_GAMES,
        "trainingMethod": resolved_method,
        "checkpointInterval": resolved_checkpoint_interval,
        "memoryGames": memory_games,
        "memoryWeight": 0.0,
        "memoryDeckPoolSize": len(deck_pool),
        "memoryReplayPlan": memory_replay_plan,
        "memoryCorrectionsApplied": memory_corrections_applied,
        "memoryPrunedAfterPromotion": memory_pruned_after_promotion,
        "memoryGamesAfterPromotion": memory_games_after_promotion,
        "trainingEngine": "ygo_native_actor_value",
        "trainingReportKind": training_report.get("kind"),
        "trainingReportPath": str(training_report_path),
        "trainingOutDir": str(candidate_dir / "training"),
        "warmStartSource": base_source,
        "warmStartPath": str(base_model_path),
        "trainingOpponentModelPaths": [],
        "selectedCheckpointPath": str(candidate_path),
        "sourceSelectedCheckpointPath": str(selected_checkpoint),
        "candidatePath": str(candidate_path),
        "checkpointSelection": checkpoint_selection.report,
        "checkpointCleanup": checkpoint_cleanup,
        "trainingDirRemoved": training_dir_removed,
        "modelRetentionCleanup": model_retention_cleanup,
        "gateMetrics": resolved_metrics,
        "promoted": decision.promoted,
        "reasons": list(decision.reasons),
    }
    report_path = codeman_root / "reports" / f"{run_name}.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=True, indent=2), encoding="utf-8")
    if not decision.promoted:
        _remove_tree(candidate_dir)
    _emit_progress(progress_callback, {
        "state": "done",
        "stage": "done",
        "episode": resolved_circles,
        "episodes": resolved_circles,
        "percent": 100,
        "message": "Champion updated" if decision.promoted else "Report saved",
        "promoted": decision.promoted,
        "reportPath": str(report_path),
        "candidatePath": str(candidate_path),
    })
    return report


def resolve_codeman_warm_start(
    codeman_id: str,
    *,
    data_root: str | Path,
    explicit_model_path: str | Path | None = None,
    deep_model_path: str | Path | None = None,
) -> WarmStartResolution:
    data_root_path = Path(data_root)
    if explicit_model_path is not None:
        path = Path(explicit_model_path)
        if not path.exists():
            raise FileNotFoundError(path)
        _require_deep_warm_start(path)
        return WarmStartResolution(path=path, source="explicit")

    champion = read_codeman_champion(codeman_id, data_root=data_root_path)
    champion_path = _checkpoint_path_from_pointer(champion, data_root_path)
    if champion_path is not None and champion_path.exists() and _is_deep_checkpoint(champion_path):
        return WarmStartResolution(path=champion_path, source="codeman")

    deep_path = Path(deep_model_path) if deep_model_path is not None else DEFAULT_DEEP_MODEL_PATH
    if deep_path.exists() and _is_deep_checkpoint(deep_path):
        return WarmStartResolution(path=deep_path, source="deep")

    raise FileNotFoundError(
        "Codeman Deep warm start not found; provide a Deep .pt checkpoint or configure the public Deep baseline."
    )


def list_codeman_training_runs(
    codeman_id: str,
    *,
    data_root: str | Path,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    reports_dir = Path(data_root) / "codeman_ai" / _safe_codeman_id(codeman_id) / "reports"
    if not reports_dir.exists():
        return []
    runs: list[dict[str, Any]] = []
    for report_path in reports_dir.glob("*.json"):
        try:
            report = json.loads(report_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(report, dict):
            continue
        report = dict(report)
        report["reportPath"] = str(report_path)
        runs.append(report)
    runs.sort(key=lambda row: (str(row.get("createdAt") or ""), str(row.get("runId") or "")), reverse=True)
    if limit is not None:
        return runs[:max(0, int(limit))]
    return runs


def apply_training_report_corrections(
    codeman_id: str,
    *,
    data_root: str | Path,
    training_report_path: str | Path,
    run_id: str | None = None,
) -> int:
    path = Path(training_report_path)
    report = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(report, dict):
        return 0
    corrections = _memory_corrections_from_training_report(report)
    if not corrections:
        return 0
    resolved_run_id = run_id or str(report.get("runId") or path.parent.parent.name)
    return _apply_memory_corrections(
        CodemanMemoryStore(data_root),
        codeman_id,
        training_report={"memoryCorrections": corrections},
        run_id=resolved_run_id,
    )


def _codeman_training_opponent_paths(
    codeman_id: str,
    *,
    data_root: Path,
    normal_model_path: str | Path | None,
    deep_model_path: str | Path | None,
) -> list[Path]:
    candidates: list[Path | None] = []
    normal_path = Path(normal_model_path) if normal_model_path is not None else DEFAULT_NORMAL_MODEL_PATH
    deep_path = Path(deep_model_path) if deep_model_path is not None else DEFAULT_DEEP_MODEL_PATH
    candidates.extend([normal_path, deep_path])
    champion = read_codeman_champion(codeman_id, data_root=data_root)
    candidates.append(_checkpoint_path_from_pointer(champion, data_root))

    paths: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        if candidate is None or not candidate.exists():
            continue
        key = str(candidate.resolve()).lower()
        if key in seen:
            continue
        seen.add(key)
        paths.append(candidate)
    return paths


def _memory_weight(memory_games: int) -> float:
    if memory_games < 20:
        return 0.10
    if memory_games <= 100:
        return 0.25
    return 0.40


def _candidate_filename(warm_start_model_path: str | Path) -> str:
    _require_deep_warm_start(warm_start_model_path)
    return "candidate.pt"


def _is_deep_checkpoint(path: str | Path) -> bool:
    return Path(path).suffix.lower() == ".pt"


def _require_deep_warm_start(path: str | Path) -> None:
    if not _is_deep_checkpoint(path):
        raise ValueError(f"Codeman training requires a Deep .pt warm start: {path}")


def _materialize_candidate(
    source_model_path: str | Path,
    candidate_path: Path,
    *,
    config: TrainingPreset,
    engine: str,
    codeman_id: str,
    training_report: dict[str, Any],
) -> None:
    source = Path(source_model_path)
    if not source.exists():
        raise FileNotFoundError(source)
    if engine == "ygo_native_actor_value":
        candidate_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, candidate_path)
        return
    _require_deep_warm_start(source)
    _require_deep_warm_start(candidate_path)
    try:
        from zz.deep_rl import TorchActionValueModel

        model = TorchActionValueModel.load(source)
        metadata = dict(model.metadata)
        metadata.update({
            "codemanId": codeman_id,
            "codemanTrainingEngine": engine,
            "codemanTrainingPreset": config.name,
            "codemanTrainingRounds": config.rounds,
            "codemanMemoryWeight": config.memory_weight,
            "codemanTrainingReportKind": training_report.get("kind"),
        })
        model.save(candidate_path, metadata=metadata)
    except Exception:
        shutil.copyfile(source, candidate_path)


def _model_kind_for_path(path: Path) -> str:
    return "deep"


def _run_id() -> str:
    return _utc_now().replace(":", "").replace("-", "").replace("Z", "z")


def _checkpoint_path_from_pointer(pointer: dict[str, Any] | None, data_root: Path) -> Path | None:
    if not pointer:
        return None
    raw_path = pointer.get("checkpointPath")
    if not raw_path:
        return None
    path = Path(str(raw_path))
    if path.is_absolute() or path.exists():
        return path
    return data_root / path


def _safe_codeman_id(codeman_id: str) -> str:
    safe_id = str(codeman_id or "").strip()
    if not safe_id or "/" in safe_id or "\\" in safe_id or safe_id in {".", ".."}:
        raise ValueError(f"invalid codeman id: {codeman_id!r}")
    return safe_id


def _remove_tree(path: Path) -> bool:
    try:
        shutil.rmtree(path)
        return True
    except FileNotFoundError:
        return False
    except OSError:
        return False


def _normalise_codeman_training_method(value: str) -> str:
    method = str(value or "gae_epoch1_local").strip().lower()
    if method not in CODEMAN_NATIVE_TRAINING_METHODS:
        raise ValueError(f"unknown Codeman training method: {value!r}")
    return method


def _resolve_codeman_native_warm_start(
    codeman_id: str,
    *,
    data_root: Path,
    explicit_model_path: str | Path | None,
) -> tuple[Path, str]:
    if explicit_model_path is not None:
        path = Path(explicit_model_path)
        if not path.exists():
            raise FileNotFoundError(path)
        _require_native_actor_json(path)
        return path, "explicit"
    champion_path = _codeman_native_champion_path(codeman_id, data_root=data_root)
    if champion_path is not None:
        _require_native_actor_json(champion_path)
        return champion_path, "codeman"
    if DEFAULT_CODEMAN_NATIVE_BASE_MODEL_PATH.exists():
        _require_native_actor_json(DEFAULT_CODEMAN_NATIVE_BASE_MODEL_PATH)
        return DEFAULT_CODEMAN_NATIVE_BASE_MODEL_PATH, "global_native_best"
    raise FileNotFoundError(f"Codeman native base model missing: {DEFAULT_CODEMAN_NATIVE_BASE_MODEL_PATH}")


def _codeman_native_champion_path(codeman_id: str, *, data_root: Path) -> Path | None:
    champion = read_codeman_champion(codeman_id, data_root=data_root)
    if not champion or str(champion.get("modelKind") or "") != "ygo_actor_value":
        return None
    path = _checkpoint_path_from_pointer(champion, data_root)
    if path is None or not path.exists():
        return None
    return path


def _require_native_actor_json(path: str | Path) -> None:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not bool(data.get("runtimeLaunchableActor")):
        raise ValueError(f"Codeman champion training requires a native actor/value JSON checkpoint: {path}")


def _actor_id_from_actor_json(path: str | Path) -> str:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    actor_id = str(data.get("actorPolicyId") or data.get("candidatePolicyId") or data.get("modelId") or "").strip()
    if not actor_id:
        raise ValueError(f"native actor checkpoint missing actorPolicyId: {path}")
    return actor_id


def _codeman_training_decks(memory_rows: list[dict[str, Any]], *, seed: int) -> list[DeckSpec]:
    decks = _memory_deck_pool(memory_rows, limit=1000)
    if not decks:
        raise ValueError("Codeman native training needs at least one remembered deck")
    if len(decks) <= 8:
        return decks
    return random.Random(seed).sample(decks, 8)


def _deck_payload_with_source(deck: DeckSpec, *, source: str) -> dict[str, Any]:
    payload = deck_payload(deck)
    payload["deckSource"] = source
    return payload


def _run_codeman_native_loop(
    *,
    out_dir: Path,
    base_model_path: Path,
    codeman_id: str,
    run_id: str,
    method: str,
    circles: int,
    checkpoint_interval: int,
    seed: int,
    deck_payloads: list[dict[str, Any]],
    progress_callback: Callable[[dict[str, Any]], None] | None,
) -> tuple[dict[str, Any], Path]:
    _emit_progress(progress_callback, {
        "state": "running",
        "stage": "training",
        "episode": 0,
        "episodes": int(circles),
        "message": "Training Codeman champion",
    })
    gate_decks = {"player": list(deck_payloads)}
    actor_id = _actor_id_from_actor_json(base_model_path)
    candidate_id = f"codeman_{_safe_codeman_id(codeman_id)}_{_safe_memory_match_key(run_id)}"
    if method == "vtrace_epoch2_native":
        from tools.run_ygo_native_loop import run_ygo_native_loop

        report = run_ygo_native_loop(
            out_dir=out_dir,
            base_model_path=base_model_path,
            current_policy_id=actor_id,
            candidate_policy_id=candidate_id,
            seed=seed,
            cycles=int(circles),
            worker_count=4,
            worker_env_slots=4,
            num_steps=64,
            selfplay_games_per_pool=CODEMAN_CIRCLE_GAMES,
            original_games_per_pool=0,
            update_epochs=2,
            num_minibatches=16,
            reward_shaping_mode="value_potential",
            potential_reward_weight=0.25,
            potential_reward_clip=0.25,
            potential_value_model_path=base_model_path,
            gate_deck_pool_payloads=gate_decks,
        )
    else:
        from tools.run_ygo_current_policy_loop import run_ygo_current_policy_loop

        report = run_ygo_current_policy_loop(
            out_dir=out_dir,
            current_policy_id=actor_id,
            base_model_path=base_model_path,
            candidate_policy_id=candidate_id,
            seed=seed,
            cycles=int(circles),
            tasks_per_cycle=CODEMAN_CIRCLE_GAMES,
            max_workers=4,
            update_epochs=1,
            current_policy_actor_advantage_mode="gae",
            actor_advantage_source="gae",
            current_policy_local_step_reward_weight=0.25,
            post_training_diagnostics="skip",
            online_transition_buffer=True,
            rollout_backend="persistent_vector_batched",
            vector_worker_count=4,
            vector_worker_env_slots=4,
            vector_steps=64,
            vector_max_game_actions=500,
            vector_selfplay_games_per_pool=CODEMAN_CIRCLE_GAMES,
            vector_original_games_per_pool=0,
            vector_gate_deck_pool_payloads=gate_decks,
            vector_rolling_env_state=True,
            allow_unpromoted_launch_actor=True,
            route_profile="legacy",
        )
    checkpoints = _codeman_checkpoint_candidates_from_loop(report, checkpoint_interval=checkpoint_interval)
    report = dict(report)
    report.update({
        "kind": "codeman_native_champion_loop_report",
        "codemanId": codeman_id,
        "runId": run_id,
        "trainingMethod": method,
        "circleGames": CODEMAN_CIRCLE_GAMES,
        "checkpointInterval": int(checkpoint_interval),
        "checkpointCandidates": checkpoints,
    })
    report_path = out_dir / "codeman_native_training_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=True, indent=2), encoding="utf-8")
    return report, report_path


def _codeman_checkpoint_candidates_from_loop(report: Mapping[str, Any], *, checkpoint_interval: int) -> list[dict[str, Any]]:
    interval = max(1, int(checkpoint_interval))
    cycles = list(report.get("cycles") or [])
    out: list[dict[str, Any]] = []
    total = len(cycles)
    for index, cycle in enumerate(cycles, start=1):
        if index % interval != 0 and index != total:
            continue
        if not isinstance(cycle, Mapping):
            continue
        path = str(cycle.get("candidateModelPath") or "").strip()
        if path:
            out.append({
                "cycle": index,
                "candidatePolicyId": str(cycle.get("candidatePolicyId") or ""),
                "candidateModelPath": path,
            })
    return out


def _select_codeman_native_champion_checkpoint(
    training_report: Mapping[str, Any],
    *,
    baseline_model_path: Path,
    current_champion_path: Path | None,
    decks: list[DeckSpec],
    seed: int,
    replacement_matchups: list[tuple[DeckSpec, DeckSpec]] | None = None,
    selection_out_dir: Path | None = None,
) -> TrainingCheckpointSelection:
    candidates = [
        row
        for row in list(training_report.get("checkpointCandidates") or [])
        if isinstance(row, Mapping) and Path(str(row.get("candidateModelPath") or "")).exists()
    ]
    if not candidates:
        raise FileNotFoundError("Codeman native training produced no checkpoint candidates")
    control_path = current_champion_path or baseline_model_path
    control_role = "current_champion" if current_champion_path is not None else "global_baseline"
    control_result = _evaluate_codeman_actor_memory_matrix(
        candidate_path=control_path,
        reference_path=baseline_model_path,
        decks=decks,
        seed=seed,
        out_dir=None if selection_out_dir is None else selection_out_dir / "reference_control",
    )
    reference_control = {
        "role": control_role,
        "path": str(control_path),
        **control_result,
    }
    control_wins = int(reference_control["candidateWins"])
    control_errors = int(reference_control["errors"])

    baseline_rows: list[dict[str, Any]] = []
    for row in candidates:
        path = Path(str(row["candidateModelPath"]))
        result = _evaluate_codeman_actor_memory_matrix(
            candidate_path=path,
            reference_path=baseline_model_path,
            decks=decks,
            seed=seed,
            out_dir=None if selection_out_dir is None else selection_out_dir / f"baseline_cycle_{int(row['cycle']):04d}",
        )
        baseline_rows.append({
            "cycle": int(row["cycle"]),
            "path": str(path),
            "compareReferencePath": str(control_path),
            "compareReferenceRole": control_role,
            "compareReferenceCandidateWins": control_wins,
            **result,
        })
    baseline_pass = [
        row
        for row in baseline_rows
        if control_errors == 0 and int(row["candidateWins"]) >= control_wins and int(row["errors"]) == 0
    ]
    replacement_rows: list[dict[str, Any]] = []
    if replacement_matchups:
        for row in baseline_pass:
            path = Path(str(row["path"]))
            result = _evaluate_codeman_actor_memory_matrix(
                candidate_path=path,
                reference_path=control_path,
                decks=decks,
                matchups=replacement_matchups,
                seed=seed,
                out_dir=None if selection_out_dir is None else selection_out_dir / f"replacement_cycle_{int(row['cycle']):04d}",
            )
            replacement_rows.append({"cycle": int(row["cycle"]), "path": str(path), **result})

    ranked = replacement_rows or baseline_pass or baseline_rows
    selected = max(
        ranked,
        key=lambda row: (
            -int(row["errors"]),
            int(row["candidateWins"]),
            int(row["cycle"]),
        ),
    )
    if replacement_rows:
        promoted = int(selected["candidateWins"]) >= int(selected["referenceWins"]) and int(selected["errors"]) == 0
    else:
        promoted = current_champion_path is None and control_errors == 0 and int(selected["candidateWins"]) >= control_wins and int(selected["errors"]) == 0
    reasons = [] if promoted else ["no checkpoint matched reference control and player-matchup replacement gate"]
    return TrainingCheckpointSelection(
        path=Path(str(selected["path"])),
        report={
            "kind": "codeman_native_champion_checkpoint_selection_v1",
            "strategy": "same_opponent_reference_control_then_current_champion_128gate",
            "baselinePath": str(baseline_model_path),
            "currentChampionPath": None if current_champion_path is None else str(current_champion_path),
            "referenceControl": reference_control,
            "baselineRows": baseline_rows,
            "baselinePassRows": baseline_pass,
            "replacementRows": replacement_rows,
            "selectedCycle": int(selected["cycle"]),
            "selectedPath": str(selected["path"]),
            "replacementGate": selected,
            "promoted": promoted,
            "reasons": reasons,
        },
    )


def _evaluate_codeman_actor_memory_matrix(
    *,
    candidate_path: Path,
    reference_path: Path,
    decks: list[DeckSpec],
    matchups: list[tuple[DeckSpec, DeckSpec]] | None = None,
    seed: int,
    out_dir: Path | None = None,
) -> dict[str, Any]:
    task_rows = (
        [(left, right, seat) for left, right in matchups for seat in ("P1", "P2")]
        if matchups
        else [(left, right, seat) for left in decks for right in decks for seat in ("P1", "P2")]
    )
    if not task_rows:
        raise ValueError("Codeman memory matrix has no deck tasks")
    if len(task_rows) >= 128:
        selected_tasks = random.Random(seed).sample(task_rows, 128)
    else:
        selected_tasks = [task_rows[index % len(task_rows)] for index in range(128)]
    from zz.ygo_vector_actor_rollout import run_ygo_vector_actor_rollout

    candidate_id = _actor_id_from_actor_json(candidate_path)
    reference_id = _actor_id_from_actor_json(reference_path)
    run_id = f"codeman-memory-matrix128-{seed}"
    gate_tasks = _build_codeman_memory_matrix_tasks(
        run_id=run_id,
        suite_id=f"{run_id}-suite",
        candidate_id=candidate_id,
        reference_id=reference_id,
        selected_tasks=selected_tasks,
        seed=seed,
    )
    gate_out_dir = out_dir or (Path(candidate_path).parent / f"codeman_memory_matrix128_seed{seed}")
    report = run_ygo_vector_actor_rollout(
        out_dir=gate_out_dir / "vector_rollout",
        run_id=run_id,
        current_policy_id=candidate_id,
        current_policy_model_path=candidate_path,
        seed=seed,
        fixed_gate_seed=seed,
        env_count=len(gate_tasks),
        worker_env_slots=max(1, (len(gate_tasks) + 7) // 8),
        worker_local_inference=True,
        num_steps=max(1, len(gate_tasks) * GATE_MAX_ACTIONS),
        worker_idle_timeout_seconds=300.0,
        max_game_actions=GATE_MAX_ACTIONS,
        max_games_per_env=1,
        selfplay_games_per_pool=0,
        original_games_per_pool=0,
        original_opponent_policy_ids=(),
        max_bridge_decisions_per_env=0,
        drain_to_terminal=True,
        original_drain_to_terminal=False,
        execution_backend="process",
        compact_action_rows=True,
        current_policy_rollout_selection_mode="masked_argmax_action",
        current_policy_rollout_temperature=1.0,
        sqlite_debug_log=False,
        gate_task_specs=gate_tasks,
        actor_model_paths_by_policy_id={
            candidate_id: candidate_path,
            reference_id: reference_path,
        },
    )
    rows = list(report.get("_gameRows") or [])
    errors = sum(1 for row in rows if row.get("error") is not None or row.get("winner") == "error")
    played_rows = [row for row in rows if row.get("error") is None and row.get("winner") != "error"]
    wins = sum(1 for row in played_rows if bool((row.get("result") or {}).get("modelPolicyWon")))
    reference_wins = sum(1 for row in played_rows if bool((row.get("result") or {}).get("opponentPolicyWon")))
    return {
        "candidateWins": int(wins),
        "referenceWins": int(reference_wins),
        "games": int(len(played_rows)),
        "errors": int(errors),
        "winRate": float(wins) / float(max(1, len(played_rows))),
        "deckCount": int(len(decks)),
        "matchupCount": int(len(matchups or [])),
        "deckSurface": "player_memory_matchups" if matchups else "memory_deck_matrix",
        "sampledTasks": int(len(selected_tasks)),
        "evaluationBackend": "worker_local_vector_gate",
        "throughput": report.get("throughput"),
        "workerFailures": report.get("workerFailures"),
        "executionErrors": report.get("executionErrors"),
        "rolloutReportPath": str(report.get("reportPath") or ""),
        "rows": rows,
    }


def _build_codeman_memory_matrix_tasks(
    *,
    run_id: str,
    suite_id: str,
    candidate_id: str,
    reference_id: str,
    selected_tasks: list[tuple[DeckSpec, DeckSpec, str]],
    seed: int,
) -> list[dict[str, Any]]:
    from zz.rollout_store import deterministic_rollout_task_id

    tasks: list[dict[str, Any]] = []
    for index, (learner_deck, opponent_deck, model_side) in enumerate(selected_tasks):
        candidate_first = model_side == "P1"
        p1_deck = learner_deck if candidate_first else opponent_deck
        p2_deck = opponent_deck if candidate_first else learner_deck
        task_seed = int(seed) + index
        task_id = deterministic_rollout_task_id(
            run_id=run_id,
            player_deck_id=str(_deck_id_or_none(learner_deck) or f"learner-{index}"),
            opponent_deck_id=str(_deck_id_or_none(opponent_deck) or f"opponent-{index}"),
            model_side=model_side,
            true_turn_order="first" if candidate_first else "second",
            difficulty="codeman_memory_matrix128",
            seed=task_seed,
        )
        tasks.append({
            "taskId": task_id,
            "runId": run_id,
            "playerDeckId": str(_deck_id_or_none(learner_deck) or ""),
            "opponentDeckId": str(_deck_id_or_none(opponent_deck) or ""),
            "modelSide": model_side,
            "trueTurnOrder": "first" if candidate_first else "second",
            "difficulty": "codeman_memory_matrix128",
            "seed": task_seed,
            "status": "pending",
            "taskSpec": {
                "games": 1,
                "suiteId": suite_id,
                "suiteKind": "codeman_memory_matrix128",
                "policyId": candidate_id,
                "opponentPolicyId": reference_id,
                "opponentBaselineLabel": "current_champion",
                "playerDeckName": str(_deck_name_or_none(learner_deck) or ""),
                "opponentDeckName": str(_deck_name_or_none(opponent_deck) or ""),
                "modelSide": model_side,
                "trueTurnOrder": "first" if candidate_first else "second",
                "difficulty": "codeman_memory_matrix128",
                "seed": task_seed,
                "taskIndex": index,
                "playerDeckSource": "codeman_memory",
                "opponentDeckSource": "codeman_memory",
                "deckSource": "codeman_memory_matrix",
                "p1Deck": deck_payload(p1_deck),
                "p2Deck": deck_payload(p2_deck),
            },
        })
    return tasks


def _resolve_training_engine(training_engine: str) -> str:
    requested = str(training_engine or "auto").strip().lower()
    if requested in {"auto", "deep"}:
        return "deep"
    if requested == "linear":
        raise ValueError("Codeman personal training no longer supports the linear training engine")
    if requested not in {"linear", "deep"}:
        raise ValueError(f"unknown Codeman training engine: {training_engine!r}")
    return "deep"


def _run_training_engine(
    engine: str,
    *,
    warm_start_model_path: str | Path,
    opponent_model_paths: list[Path],
    out_dir: Path,
    config: TrainingPreset,
    seed: int,
    eval_episodes: int | None,
    deck_pool: list[DeckSpec],
    deck_matchups: list[tuple[DeckSpec, DeckSpec]],
    imitation_trace_paths: list[Path] | None = None,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> tuple[dict[str, Any], Path]:
    if engine != "deep":
        raise ValueError("Codeman personal training only supports the Deep training engine")
    imitation_trace_paths = list(imitation_trace_paths or [])
    eval_games = _evaluation_games(config.rounds, eval_episodes)
    training_opponent = "self" if deck_matchups else "checkpoint_pool"
    from zz.deep_rl import run_deep_training
    rollout_workers = _default_rollout_workers()
    refinement_rounds = (
        _codeman_replay_refinement_rounds(config.rounds)
        if _should_run_codeman_replay_refinement(
            rollout_workers=rollout_workers,
            rounds=config.rounds,
            deck_matchups=deck_matchups,
            imitation_trace_paths=imitation_trace_paths,
        )
        else 0
    )
    total_progress_episodes = config.rounds + refinement_rounds

    primary_out_dir = out_dir / "parallel_primary" if refinement_rounds > 0 else out_dir
    primary_report = run_deep_training(
        episodes=config.rounds,
        seed=seed,
        out_dir=primary_out_dir,
        device="auto",
        require_cuda=True,
        train_scope="head",
        eval_interval=_codeman_eval_interval(config.rounds),
        eval_episodes=eval_games,
        opponent=training_opponent,
        opponent_model_paths=opponent_model_paths,
        learner_side="alternate",
        initial_model_path=warm_start_model_path,
        tactical_preference_weight=CODEMAN_TACTICAL_PREFERENCE_WEIGHT,
        tactical_preference_margin=CODEMAN_TACTICAL_PREFERENCE_MARGIN,
        opponent_behavior_preference_weight=CODEMAN_OPPONENT_BEHAVIOR_PREFERENCE_WEIGHT,
        opponent_behavior_preference_margin=CODEMAN_OPPONENT_BEHAVIOR_PREFERENCE_MARGIN,
        opponent_behavior_preference_epochs=CODEMAN_PRIMARY_OPPONENT_BEHAVIOR_PREFERENCE_EPOCHS,
        opponent_behavior_preference_learning_rate=CODEMAN_OPPONENT_BEHAVIOR_PREFERENCE_LEARNING_RATE,
        opponent_behavior_preference_reapply_after_anchor=True,
        loss_replay_decisions=3,
        loss_replay_alternatives=2,
        loss_replay_max_branches=6,
        imitation_trace_paths=imitation_trace_paths,
        imitation_epochs=CODEMAN_PRIMARY_IMITATION_EPOCHS if imitation_trace_paths else 0,
        imitation_batch_size=128,
        imitation_target=CODEMAN_MEMORY_IMITATION_TARGET,
        deck_pool=deck_pool,
        deck_matchups=deck_matchups,
        deck_matrix_eval_episodes=1 if deck_pool and config.rounds > 0 else 0,
        rollout_workers=rollout_workers,
        rollout_batch_size=max(1, rollout_workers * 2),
        rollout_actor_device="cpu",
        progress_callback=_codeman_stage_progress_callback(
            progress_callback,
            offset=0,
            total_episodes=total_progress_episodes,
            message_prefix="Parallel rollout",
        ) if refinement_rounds > 0 else progress_callback,
    )
    if refinement_rounds <= 0:
        return primary_report, out_dir / "training_report.json"

    primary_checkpoint = _select_training_checkpoint(engine, primary_report)
    refinement_out_dir = out_dir / "replay_refinement"
    refinement_report = run_deep_training(
        episodes=refinement_rounds,
        seed=seed + 770000,
        out_dir=refinement_out_dir,
        device="auto",
        require_cuda=True,
        train_scope="head",
        eval_interval=_codeman_eval_interval(refinement_rounds),
        eval_episodes=eval_games,
        opponent=training_opponent,
        opponent_model_paths=opponent_model_paths,
        learner_side="alternate",
        initial_model_path=primary_checkpoint,
        training_max_lookahead_actions=6,
        training_beam_lookahead_width=6,
        training_beam_lookahead_depth=2,
        training_beam_lookahead_key_decisions_only=True,
        tactical_preference_weight=CODEMAN_REFINEMENT_TACTICAL_PREFERENCE_WEIGHT,
        tactical_preference_margin=CODEMAN_TACTICAL_PREFERENCE_MARGIN,
        opponent_behavior_preference_weight=CODEMAN_OPPONENT_BEHAVIOR_PREFERENCE_WEIGHT,
        opponent_behavior_preference_margin=CODEMAN_OPPONENT_BEHAVIOR_PREFERENCE_MARGIN,
        opponent_behavior_preference_epochs=CODEMAN_REFINEMENT_OPPONENT_BEHAVIOR_PREFERENCE_EPOCHS,
        opponent_behavior_preference_learning_rate=CODEMAN_OPPONENT_BEHAVIOR_PREFERENCE_LEARNING_RATE,
        opponent_behavior_preference_reapply_after_anchor=True,
        loss_replay_decisions=3,
        loss_replay_alternatives=2,
        loss_replay_max_branches=6,
        imitation_trace_paths=imitation_trace_paths,
        imitation_epochs=CODEMAN_REFINEMENT_IMITATION_EPOCHS if imitation_trace_paths else 0,
        imitation_batch_size=128,
        imitation_target=CODEMAN_MEMORY_IMITATION_TARGET,
        deck_pool=deck_pool,
        deck_matchups=deck_matchups,
        deck_matrix_eval_episodes=1 if deck_pool else 0,
        rollout_workers=1,
        rollout_batch_size=1,
        rollout_actor_device="cpu",
        deep_anchor_model_path=warm_start_model_path,
        deep_anchor_episodes=_codeman_deep_anchor_episodes(refinement_rounds),
        deep_anchor_epochs=1,
        deep_anchor_batch_size=128,
        deep_anchor_interval=_codeman_deep_anchor_interval(refinement_rounds),
        deep_anchor_opponent=training_opponent,
        progress_callback=_codeman_stage_progress_callback(
            progress_callback,
            offset=config.rounds,
            total_episodes=total_progress_episodes,
            message_prefix="Replay refinement",
        ),
    )
    report = _combined_codeman_deep_training_report(
        primary_report=primary_report,
        refinement_report=refinement_report,
        primary_report_path=primary_out_dir / "training_report.json",
        refinement_report_path=refinement_out_dir / "training_report.json",
        primary_checkpoint=primary_checkpoint,
        refinement_rounds=refinement_rounds,
        rollout_workers=rollout_workers,
        warm_start_model_path=warm_start_model_path,
    )
    report_path = out_dir / "training_report.json"
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=True, indent=2), encoding="utf-8")
    return report, report_path


def _should_run_codeman_replay_refinement(
    *,
    rollout_workers: int,
    rounds: int,
    deck_matchups: list[tuple[DeckSpec, DeckSpec]],
    imitation_trace_paths: list[Path],
) -> bool:
    return (
        int(rollout_workers) > 1
        and int(rounds) > 0
        and (bool(deck_matchups) or bool(imitation_trace_paths))
    )


def _codeman_replay_refinement_rounds(rounds: int) -> int:
    rounds = max(0, int(rounds))
    if rounds <= 0:
        return 0
    return min(50, max(10, rounds // 4))


def _codeman_deep_anchor_episodes(rounds: int) -> int:
    rounds = max(1, int(rounds))
    return max(1, min(5, rounds // 5))


def _codeman_deep_anchor_interval(rounds: int) -> int:
    rounds = max(1, int(rounds))
    return max(1, min(10, rounds // 2))


def _codeman_stage_progress_callback(
    callback: Callable[[dict[str, Any]], None] | None,
    *,
    offset: int,
    total_episodes: int,
    message_prefix: str,
) -> Callable[[dict[str, Any]], None] | None:
    if callback is None:
        return None

    def wrapped(event: dict[str, Any]) -> None:
        payload = dict(event)
        episode = int(payload.get("episode", payload.get("completedEpisodes", 0)) or 0)
        payload["episode"] = max(0, int(offset)) + max(0, episode)
        payload["episodes"] = max(0, int(total_episodes))
        message = payload.get("message")
        payload["message"] = f"{message_prefix}: {message}" if message else message_prefix
        callback(payload)

    return wrapped


def _combined_codeman_deep_training_report(
    *,
    primary_report: dict[str, Any],
    refinement_report: dict[str, Any],
    primary_report_path: Path,
    refinement_report_path: Path,
    primary_checkpoint: Path,
    refinement_rounds: int,
    rollout_workers: int,
    warm_start_model_path: str | Path,
) -> dict[str, Any]:
    report = dict(refinement_report)
    report["kind"] = "codeman_deep_training_report"
    report["trainingStrategy"] = "parallel_primary_then_single_worker_replay_refinement"
    report["primaryTrainingReportPath"] = str(primary_report_path)
    report["refinementTrainingReportPath"] = str(refinement_report_path)
    report["primarySelectedCheckpointPath"] = str(primary_checkpoint)
    report["refinementRounds"] = int(refinement_rounds)
    report["primaryReportKind"] = primary_report.get("kind")
    report["refinementReportKind"] = refinement_report.get("kind")
    report["primaryConfig"] = dict(primary_report.get("config", {}))
    report["refinementConfig"] = dict(refinement_report.get("config", {}))
    config = dict(refinement_report.get("config", {}))
    config.update({
        "codemanTrainingStrategy": report["trainingStrategy"],
        "primaryRolloutWorkers": int(rollout_workers),
        "refinementRolloutWorkers": 1,
        "refinementRounds": int(refinement_rounds),
        "refinementInitialModelPath": str(primary_checkpoint),
        "refinementDeepAnchorModelPath": str(Path(warm_start_model_path)),
    })
    report["config"] = config
    return report


def _default_rollout_workers() -> int:
    cpu_count = os.cpu_count() or 1
    return max(1, min(CODEMAN_MAX_ROLLOUT_WORKERS, cpu_count - 1))


def _codeman_eval_interval(rounds: int) -> int:
    rounds = max(1, int(rounds))
    if rounds > 200:
        return CODEMAN_LONG_TRAINING_EVAL_INTERVAL
    if rounds > CODEMAN_STANDARD_TRAINING_EVAL_INTERVAL:
        return CODEMAN_STANDARD_TRAINING_EVAL_INTERVAL
    return rounds


def _cleanup_training_checkpoints(
    training_dir: Path,
    *,
    source_selected_checkpoint: Path,
    candidate_path: Path,
) -> dict[str, Any]:
    if not training_dir.exists():
        return {"removed": [], "kept": [str(candidate_path)]}
    source_selected = source_selected_checkpoint.resolve()
    candidate = candidate_path.resolve()
    removed: list[str] = []
    try:
        training_root = training_dir.resolve()
    except OSError:
        training_root = training_dir
    for pattern in ("latest.json", "latest.pt", "best_*.json", "best_*.pt", "rollout_actor_latest.pt"):
        for path in training_dir.rglob(pattern):
            try:
                resolved = path.resolve()
            except OSError:
                continue
            if resolved != training_root and training_root not in resolved.parents:
                continue
            if resolved == candidate:
                continue
            try:
                path.unlink()
            except OSError:
                continue
            removed.append(str(path))
    return {
        "removed": sorted(removed),
        "kept": [str(candidate_path)],
        "sourceSelectedCheckpointPath": str(source_selected),
    }


def _cleanup_old_codeman_candidate_models(
    codeman_root: Path,
    *,
    keep_candidate_paths: list[Path | None],
) -> dict[str, Any]:
    candidates_root = codeman_root / "candidates"
    if not candidates_root.exists():
        return {
            "policy": "keep_current_run_and_current_champion",
            "candidateRoot": str(candidates_root),
            "keptCandidateDirs": [],
            "removed": [],
        }
    try:
        root = candidates_root.resolve()
    except OSError:
        return {
            "policy": "keep_current_run_and_current_champion",
            "candidateRoot": str(candidates_root),
            "keptCandidateDirs": [],
            "removed": [],
        }

    keep_dirs: set[str] = set()
    keep_display: list[str] = []
    for path in keep_candidate_paths:
        keep_dir = _candidate_run_dir_for_path(path, root)
        if keep_dir is None:
            continue
        marker = _path_marker(keep_dir)
        if marker in keep_dirs:
            continue
        keep_dirs.add(marker)
        keep_display.append(str(keep_dir))

    removed: list[str] = []
    try:
        candidate_dirs = list(candidates_root.iterdir())
    except OSError:
        candidate_dirs = []
    for candidate_dir in candidate_dirs:
        if not candidate_dir.is_dir():
            continue
        try:
            resolved_dir = candidate_dir.resolve()
        except OSError:
            continue
        if resolved_dir == root or root not in resolved_dir.parents:
            continue
        if _path_marker(resolved_dir) in keep_dirs:
            continue
        for model_path in candidate_dir.rglob("*.pt"):
            try:
                resolved_model = model_path.resolve()
            except OSError:
                continue
            if resolved_model == root or root not in resolved_model.parents:
                continue
            try:
                model_path.unlink()
            except OSError:
                continue
            removed.append(str(model_path))

    return {
        "policy": "keep_current_run_and_current_champion",
        "candidateRoot": str(candidates_root),
        "keptCandidateDirs": sorted(keep_display),
        "removed": sorted(removed),
    }


def _candidate_run_dir_for_path(path: Path | None, candidates_root: Path) -> Path | None:
    if path is None:
        return None
    try:
        resolved = Path(path).resolve()
    except OSError:
        return None
    if resolved == candidates_root or candidates_root not in resolved.parents:
        return None
    current = resolved if resolved.is_dir() else resolved.parent
    while current.parent != candidates_root:
        if current.parent == current:
            return None
        current = current.parent
    return current


def _path_marker(path: Path) -> str:
    return os.path.normcase(str(path.resolve()))


def _codeman_progress_callback(
    progress_path: str | Path | None,
    *,
    codeman_id: str,
    run_id: str,
    preset: str,
    total_episodes: int,
) -> Callable[[dict[str, Any]], None] | None:
    if progress_path is None:
        return None
    path = Path(progress_path)

    def callback(event: dict[str, Any]) -> None:
        episode = int(event.get("episode", event.get("completedEpisodes", 0)) or 0)
        episodes = int(event.get("episodes", event.get("totalEpisodes", total_episodes)) or total_episodes)
        state = str(event.get("state") or "running")
        stage = str(event.get("stage") or "training")
        percent = int(event["percent"]) if "percent" in event else _progress_percent(stage, episode, episodes, state)
        payload = {
            "schema": 1,
            "kind": "codeman_training_progress",
            "updatedAt": _utc_now(),
            "codemanId": codeman_id,
            "runId": run_id,
            "preset": preset,
            "state": state,
            "stage": stage,
            "percent": max(0, min(100, percent)),
            "completedEpisodes": max(0, episode),
            "totalEpisodes": max(0, episodes),
            "message": event.get("message") or _progress_message(stage, episode, episodes, state),
        }
        for key in ("promoted", "reportPath", "candidatePath", "evaluation"):
            if key in event:
                payload[key] = event[key]
        _write_progress_payload(path, payload)

    return callback


def _write_progress_payload(path: Path, payload: dict[str, Any]) -> bool:
    text = json.dumps(payload, ensure_ascii=True, indent=2)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        return False
    for attempt in range(CODEMAN_PROGRESS_WRITE_ATTEMPTS):
        tmp = path.with_name(f"{path.name}.{os.getpid()}.{time.monotonic_ns()}.tmp")
        try:
            tmp.write_text(text, encoding="utf-8")
            tmp.replace(path)
            return True
        except PermissionError:
            _unlink_best_effort(tmp)
            if attempt + 1 >= CODEMAN_PROGRESS_WRITE_ATTEMPTS:
                return False
            time.sleep(CODEMAN_PROGRESS_WRITE_RETRY_SECONDS * (attempt + 1))
        except OSError:
            _unlink_best_effort(tmp)
            return False
    return False


def _unlink_best_effort(path: Path) -> None:
    try:
        path.unlink()
    except OSError:
        pass


def _emit_progress(callback: Callable[[dict[str, Any]], None] | None, event: dict[str, Any]) -> None:
    if callback is not None:
        callback(event)


def _progress_percent(stage: str, episode: int, episodes: int, state: str) -> int:
    if state == "done":
        return 100
    if state == "error":
        return 100
    if stage == "preparing":
        return 0
    if stage == "evaluating":
        return 95
    if episodes <= 0:
        return 90
    return int(min(90, round((max(0, episode) / max(1, episodes)) * 90)))


def _progress_message(stage: str, episode: int, episodes: int, state: str) -> str:
    if state == "done":
        return "Training complete"
    if state == "error":
        return "Training failed"
    if stage == "evaluating":
        return "Evaluating promotion gate"
    if stage == "preparing":
        return "Preparing Codeman training"
    return f"Training {max(0, episode)}/{max(0, episodes)}"


def _evaluation_games(rounds: int, override: int | None) -> int:
    if override is not None:
        return max(1, int(override))
    if rounds <= 5:
        return 1
    return min(10, max(1, rounds // 10))


def _select_training_checkpoint(engine: str, report: dict[str, Any]) -> Path:
    if engine != "deep":
        raise ValueError("Codeman personal training only supports Deep checkpoints")
    for key in ("bestDeckMatrixFloorModelPath", "bestDeckMatrixAverageModelPath", "bestGreedyModelPath", "latestModelPath"):
        value = report.get(key)
        if value and Path(value).exists():
            return Path(value)
    raise FileNotFoundError(f"training did not produce a checkpoint for {engine!r}")


_TRAINING_CHECKPOINT_PATH_KEYS = (
    "imitationWarmStartModelPath",
    "bestPlayerGateFloorModelPath",
    "bestPlayerGateAverageModelPath",
    "bestDeckMatrixFloorModelPath",
    "bestDeckMatrixAverageModelPath",
    "bestGreedyModelPath",
    "latestModelPath",
    "primarySelectedCheckpointPath",
)

_TRAINING_REPORT_PATH_KEYS = (
    "primaryTrainingReportPath",
    "refinementTrainingReportPath",
)


def _select_training_checkpoint_for_codeman(
    engine: str,
    report: dict[str, Any],
    *,
    warm_start_model_path: str | Path,
    codeman_id: str,
    data_root: str | Path,
    deck_matchups: list[tuple[DeckSpec, DeckSpec]],
    seed: int,
    episodes: int,
) -> TrainingCheckpointSelection:
    candidates = _training_checkpoint_candidates(report)
    if not candidates:
        path = _select_training_checkpoint(engine, report)
        return TrainingCheckpointSelection(path=path, report={
            "kind": "codeman_checkpoint_selection_gate",
            "strategy": "fallback_report_order",
            "selectedKey": None,
            "selectedPath": str(path),
            "candidates": [],
        })

    baseline_path = _codeman_selection_baseline_path(
        codeman_id,
        data_root=data_root,
        warm_start_model_path=warm_start_model_path,
    )
    baseline = _evaluate_checkpoint_against_greedy_random_seats(
        baseline_path,
        episodes=episodes,
        seed=seed + 200000,
        deck_matchups=deck_matchups,
    )
    rows: list[dict[str, Any]] = []
    for key, path in candidates:
        evaluation = _evaluate_checkpoint_against_greedy_random_seats(
            path,
            episodes=episodes,
            seed=seed + 10000,
            deck_matchups=deck_matchups,
        )
        row = {
            "key": key,
            "path": str(path),
            "winRate": float(evaluation.get("winRate", 0.0)),
            "p1WinRate": float(evaluation.get("p1WinRate", 0.0)),
            "p2WinRate": float(evaluation.get("p2WinRate", 0.0)),
            "errors": int(evaluation.get("errors", 0)),
        }
        rows.append(row)
    selected = max(
        rows,
        key=lambda row: (
            -int(row["errors"]),
            float(row["winRate"]),
            float(row["p2WinRate"]),
            float(row["p1WinRate"]),
            -rows.index(row),
        ),
    )
    selected_path = Path(selected["path"])
    baseline_win_rate = float(baseline.get("winRate", 0.0))
    selected_win_rate = float(selected["winRate"])
    return TrainingCheckpointSelection(path=selected_path, report={
        "kind": "codeman_checkpoint_selection_gate",
        "strategy": "memory_greedy_gate",
        "seed": int(seed),
        "candidateSeed": int(seed + 10000),
        "baselineSeed": int(seed + 200000),
        "gateDeckSource": "memory_matchups" if deck_matchups else "default",
        "gateDeckMatchupCount": len(deck_matchups or []),
        "episodesPerSeat": int(episodes),
        "baselinePath": str(baseline_path),
        "baselineWinRate": baseline_win_rate,
        "baselineP1WinRate": float(baseline.get("p1WinRate", 0.0)),
        "baselineP2WinRate": float(baseline.get("p2WinRate", 0.0)),
        "baselineErrors": int(baseline.get("errors", 0)),
        "selectedKey": selected["key"],
        "selectedPath": str(selected_path),
        "selectedWinRate": selected_win_rate,
        "selectedP1WinRate": float(selected["p1WinRate"]),
        "selectedP2WinRate": float(selected["p2WinRate"]),
        "selectedErrors": int(selected["errors"]),
        "selectedBeatsBaseline": selected_win_rate > baseline_win_rate,
        "targetImprovement": selected_win_rate - baseline_win_rate,
        "candidates": rows,
    })


def _training_checkpoint_candidates(report: dict[str, Any]) -> list[tuple[str, Path]]:
    candidates: list[tuple[str, Path]] = []
    seen_paths: set[str] = set()
    seen_reports: set[str] = set()

    def add_report(source: dict[str, Any], *, prefix: str = "") -> None:
        for key in _TRAINING_CHECKPOINT_PATH_KEYS:
            value = source.get(key)
            if not value:
                continue
            path = Path(value)
            if not path.exists():
                continue
            try:
                marker = str(path.resolve()).lower()
            except OSError:
                marker = str(path).lower()
            if marker in seen_paths:
                continue
            seen_paths.add(marker)
            candidates.append((f"{prefix}{key}", path))
        for key in _TRAINING_REPORT_PATH_KEYS:
            value = source.get(key)
            if not value:
                continue
            report_path = Path(value)
            if not report_path.exists():
                continue
            try:
                report_marker = str(report_path.resolve()).lower()
            except OSError:
                report_marker = str(report_path).lower()
            if report_marker in seen_reports:
                continue
            seen_reports.add(report_marker)
            try:
                nested = json.loads(report_path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if isinstance(nested, dict):
                add_report(nested, prefix=f"{key}.")

    add_report(report)
    return candidates


def _codeman_selection_baseline_path(
    codeman_id: str,
    *,
    data_root: str | Path,
    warm_start_model_path: str | Path,
) -> Path:
    data_root_path = Path(data_root)
    champion = read_codeman_champion(codeman_id, data_root=data_root_path)
    champion_path = _checkpoint_path_from_pointer(champion, data_root_path)
    if champion_path is not None and champion_path.exists():
        return champion_path
    return Path(warm_start_model_path)


def _memory_deck_pool(memory_rows: list[dict[str, Any]], *, limit: int = 6) -> list[DeckSpec]:
    decks: list[DeckSpec] = []
    seen: set[str] = set()
    for row in _memory_rows_for_training(memory_rows):
        for prefix in ("player", "opponent"):
            recipe = _normalise_recipe(row.get(f"{prefix}_deck_recipe"))
            forces = _normalise_forces(row.get(f"{prefix}_forces"))
            if not recipe or len(forces) != 2:
                continue
            key = json.dumps({"recipe": recipe, "forces": forces}, sort_keys=True)
            if key in seen:
                continue
            seen.add(key)
            decks.append(DeckSpec(
                id=f"memory-{len(decks) + 1}",
                name=f"Codeman Memory {len(decks) + 1}",
                recipe=recipe,
                forces=forces,
            ))
            if len(decks) >= limit:
                return decks
    return decks


def _memory_replay_plan(
    memory_rows: list[dict[str, Any]],
    *,
    config: TrainingPreset,
    deck_pool_size: int,
    deck_matchup_size: int,
    trace_path_count: int,
    opponent_control: str,
) -> dict[str, Any]:
    return {
        "sourceGames": len(memory_rows),
        "lossGames": len(_memory_loss_rows(memory_rows)),
        "deckPoolSize": deck_pool_size,
        "deckMatchupSize": deck_matchup_size,
        "tracePathCount": max(0, int(trace_path_count)),
        "opponentControl": opponent_control,
        "simulationRounds": config.rounds,
        "pruneOnPromotionKeep": CODEMAN_MEMORY_KEEP_AFTER_PROMOTION,
    }


def _apply_memory_corrections(
    memory_store: CodemanMemoryStore,
    codeman_id: str,
    *,
    training_report: dict[str, Any],
    run_id: str,
) -> int:
    raw_corrections = training_report.get("memoryCorrections")
    if not isinstance(raw_corrections, list):
        return 0
    memory_rows = {
        str(row.get("match_id") or ""): row
        for row in memory_store.read_games(codeman_id)
    }
    applied = 0
    for raw in raw_corrections:
        if not isinstance(raw, dict):
            continue
        match_id = raw.get("matchId") or raw.get("match_id")
        if not match_id:
            continue
        memory_row = memory_rows.get(str(match_id))
        if not _memory_row_is_player_loss(memory_row):
            continue
        payload = dict(raw)
        payload.setdefault("playerController", "codeman_self")
        payload.setdefault("opponentController", "codeman_self")
        payload.setdefault("replayControl", "codeman_self_vs_self")
        try:
            memory_store.write_corrected_replay(codeman_id, str(match_id), payload, run_id=run_id)
        except (FileNotFoundError, OSError, TypeError, ValueError):
            continue
        applied += 1
    return applied


def _memory_row_is_player_loss(row: dict[str, Any] | None) -> bool:
    if not isinstance(row, dict):
        return False
    player_side = str(row.get("player_side") or row.get("playerSide") or "")
    winner_side = str(row.get("winner_side") or row.get("winnerSide") or "")
    return bool(player_side and winner_side and winner_side != player_side)


def _memory_corrections_from_training_report(report: dict[str, Any]) -> list[dict[str, Any]]:
    raw_corrections = report.get("memoryCorrections")
    if isinstance(raw_corrections, list) and raw_corrections:
        return [dict(row) for row in raw_corrections if isinstance(row, dict)]
    return _backfill_memory_corrections_from_counterfactual_rows(report)


def _backfill_memory_corrections_from_counterfactual_rows(report: dict[str, Any]) -> list[dict[str, Any]]:
    episode_rows = {
        int(row.get("episode", -1)): row
        for row in report.get("rows", [])
        if isinstance(row, dict)
    }
    replay_rows = report.get("counterfactualReplay", {}).get("rows", [])
    if not isinstance(replay_rows, list):
        return []
    corrections: list[dict[str, Any]] = []
    seen_matches: set[str] = set()
    for replay_row in replay_rows:
        if not isinstance(replay_row, dict):
            continue
        episode_no = int(replay_row.get("episode", -1))
        episode = episode_rows.get(episode_no)
        if not isinstance(episode, dict):
            continue
        match_id = _memory_match_id_from_deck_id(str(episode.get("learnerDeckId") or ""))
        if not match_id or match_id in seen_matches:
            continue
        winning_row = _winning_counterfactual_row(replay_row)
        if winning_row is None:
            continue
        opponent = str(episode.get("opponent") or "")
        ai_action = _action_summary(winning_row.get("override"))
        decision_index = int(winning_row.get("decisionIndex", -1))
        seen_matches.add(match_id)
        corrections.append({
            "schema": 1,
            "kind": "codeman_corrected_replay",
            "matchId": str(match_id),
            "sourceEpisode": episode_no,
            "learnerSide": str(episode.get("learnerSide") or "P1"),
            "playerController": "codeman_self" if opponent == "self" else "codeman",
            "opponentController": "codeman_self" if opponent == "self" else opponent,
            "replayControl": "codeman_self_vs_self" if opponent == "self" else opponent,
            "divergences": [{
                "eventIndex": 0,
                "decisionIndex": decision_index,
                "playerAction": "recorded action",
                "aiAction": ai_action,
                "hint": f"Codeman chose {ai_action} instead of the recorded action and found a winning branch.",
            }],
            "logEvents": [{
                "type": "codeman_correction",
                "actionKind": "ai_correction",
                "label": f"AI correction: {ai_action}",
                "decisionIndex": decision_index,
                "winner": winning_row.get("winner"),
            }],
        })
    return corrections


def _winning_counterfactual_row(replay_row: dict[str, Any]) -> dict[str, Any] | None:
    rows = replay_row.get("rows")
    if not isinstance(rows, list):
        return None
    return next((row for row in rows if isinstance(row, dict) and row.get("won")), None)


def _memory_deck_matchups(memory_rows: list[dict[str, Any]], *, limit: int = 8) -> list[tuple[DeckSpec, DeckSpec]]:
    matchups: list[tuple[DeckSpec, DeckSpec]] = []
    seen: set[str] = set()
    for row in _memory_rows_for_training(memory_rows):
        player_recipe = _normalise_recipe(row.get("player_deck_recipe"))
        player_forces = _normalise_forces(row.get("player_forces"))
        opponent_recipe = _normalise_recipe(row.get("opponent_deck_recipe"))
        opponent_forces = _normalise_forces(row.get("opponent_forces"))
        if not player_recipe or not opponent_recipe or len(player_forces) != 2 or len(opponent_forces) != 2:
            continue
        key = json.dumps({
            "player": {"recipe": player_recipe, "forces": player_forces},
            "opponent": {"recipe": opponent_recipe, "forces": opponent_forces},
        }, sort_keys=True)
        if key in seen:
            continue
        seen.add(key)
        index = len(matchups) + 1
        match_key = _safe_memory_match_key(row.get("match_id") or f"{index}")
        matchups.append((
            DeckSpec(
                id=f"memory-match-{match_key}-player",
                name=f"Codeman Memory Match {index} Player",
                recipe=player_recipe,
                forces=player_forces,
            ),
            DeckSpec(
                id=f"memory-match-{match_key}-opponent",
                name=f"Codeman Memory Match {index} Opponent",
                recipe=opponent_recipe,
                forces=opponent_forces,
            ),
        ))
        if len(matchups) >= limit:
            return matchups
    return matchups


def _memory_trace_paths(memory_rows: list[dict[str, Any]], *, data_root: Path, limit: int = 12) -> list[Path]:
    paths: list[Path] = []
    seen: set[str] = set()
    for row in _memory_rows_for_training(memory_rows):
        raw_candidates: list[tuple[Any, int]] = [
            (row.get("corrected_trace_path"), CODEMAN_CORRECTED_TRACE_WEIGHT),
            (row.get("trace_path"), 1),
        ]
        for raw_path, repeat_count in raw_candidates:
            if not isinstance(raw_path, str) or not raw_path:
                continue
            path = Path(raw_path)
            resolved = path if path.is_absolute() else data_root / path
            try:
                resolved = resolved.resolve()
                root = data_root.resolve()
            except OSError:
                continue
            if resolved != root and root not in resolved.parents:
                continue
            if not resolved.exists():
                continue
            key = str(resolved).lower()
            if key in seen:
                break
            seen.add(key)
            for _ in range(max(1, int(repeat_count))):
                paths.append(resolved)
                if len(paths) >= limit:
                    return paths
            break
    return paths


def _safe_memory_match_key(value: Any) -> str:
    raw = str(value or "").strip()
    safe = "".join(ch if ch.isalnum() or ch in {"_", "-", "."} else "_" for ch in raw).strip("._")
    return safe or "memory"


def _memory_rows_for_training(memory_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    latest_first = list(reversed(memory_rows))
    losses = [row for row in latest_first if _is_memory_player_loss(row)]
    non_losses = [row for row in latest_first if not _is_memory_player_loss(row)]
    return losses + non_losses


def _memory_loss_rows(memory_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row for row in memory_rows if _is_memory_player_loss(row)]


def _is_memory_player_loss(row: dict[str, Any]) -> bool:
    player_side = row.get("player_side")
    winner_side = row.get("winner_side")
    if not player_side or not winner_side:
        return False
    return str(player_side) != str(winner_side)


def _normalise_recipe(raw: Any) -> dict[str, int]:
    if not isinstance(raw, dict):
        return {}
    recipe: dict[str, int] = {}
    for card_id, count in raw.items():
        try:
            parsed = int(count)
        except (TypeError, ValueError):
            continue
        if parsed > 0:
            recipe[str(card_id)] = parsed
    return recipe


def _normalise_forces(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    return [str(force_id) for force_id in raw if str(force_id)]


def _deck_id_or_none(deck: Any | None) -> str | None:
    if deck is None:
        return None
    value = getattr(deck, "id", None)
    return str(value) if value else None


def _deck_name_or_none(deck: Any | None) -> str | None:
    if deck is None:
        return None
    value = getattr(deck, "name", None)
    return str(value) if value else None


def _deck_recipe_or_none(deck: Any | None) -> dict[str, int] | None:
    if deck is None:
        return None
    recipe = getattr(deck, "recipe", None)
    if not isinstance(recipe, dict):
        return None
    return {str(card_id): int(count) for card_id, count in recipe.items()}


def _deck_forces_or_none(deck: Any | None) -> list[str] | None:
    if deck is None:
        return None
    forces = getattr(deck, "forces", None)
    if not isinstance(forces, list):
        return None
    return [str(force_id) for force_id in forces]


def _gate_deck_rows(
    deck_matchups: list[tuple[DeckSpec, DeckSpec]] | None,
) -> list[tuple[int | None, DeckSpec | None, DeckSpec | None]]:
    if not deck_matchups:
        return [(None, None, None)]
    return [
        (index, learner_deck, opponent_deck)
        for index, (learner_deck, opponent_deck) in enumerate(deck_matchups)
    ]


def _gate_episodes_per_matchup(episodes: int, matchup_count: int) -> int:
    episodes = max(1, int(episodes))
    matchup_count = max(1, int(matchup_count))
    return max(1, (episodes + matchup_count - 1) // matchup_count)


def _derive_gate_metrics(
    *,
    warm_start_model_path: str | Path,
    candidate_path: Path,
    codeman_id: str,
    data_root: str | Path,
    normal_model_path: str | Path | None,
    deep_model_path: str | Path | None,
    deck_matchups: list[tuple[DeckSpec, DeckSpec]] | None = None,
    seed: int,
    episodes: int,
) -> dict[str, Any]:
    data_root_path = Path(data_root)
    champion = read_codeman_champion(codeman_id, data_root=data_root_path)
    current_champion_path = _checkpoint_path_from_pointer(champion, data_root_path)
    if current_champion_path is not None and not current_champion_path.exists():
        current_champion_path = None
    baseline_path = current_champion_path or Path(warm_start_model_path)
    normal_path = Path(normal_model_path) if normal_model_path is not None else DEFAULT_NORMAL_MODEL_PATH
    deep_path = Path(deep_model_path) if deep_model_path is not None else DEFAULT_DEEP_MODEL_PATH

    gate_deck_rows = _gate_deck_rows(deck_matchups)
    gate_deck_source = "memory_matchups" if deck_matchups else "default"
    gate_row_episodes = _gate_episodes_per_matchup(episodes, len(gate_deck_rows))
    rows: list[dict[str, Any]] = []
    opponent_specs: list[tuple[str, Path | None]] = [("greedy", None)]
    if normal_path.exists():
        opponent_specs.append(("normal", normal_path))
    if deep_path.exists():
        opponent_specs.append(("deep", deep_path))
    if current_champion_path is not None:
        opponent_specs.append(("current_champion", current_champion_path))

    for matchup_index, learner_deck, opponent_deck in gate_deck_rows:
        seed_matchup_index = matchup_index or 0
        for opponent_index, (opponent_name, opponent_path) in enumerate(opponent_specs):
            for seat_index, candidate_seat in enumerate(("P1", "P2")):
                rows.append(_evaluate_candidate_matchup(
                    candidate_path=candidate_path,
                    opponent_name=opponent_name,
                    opponent_path=opponent_path,
                    candidate_seat=candidate_seat,
                    episodes=gate_row_episodes,
                    seed=seed + 10000 + seed_matchup_index * 10000 + opponent_index * 1000 + seat_index * 100,
                    learner_deck=learner_deck,
                    opponent_deck=opponent_deck,
                    deck_source="memory_matchup" if learner_deck is not None else "default",
                    deck_matchup_index=matchup_index,
                ))

    aggregates = {
        opponent_name: _aggregate_matchup_rows(rows, opponent_name)
        for opponent_name, _ in opponent_specs
    }
    baseline = _evaluate_checkpoint_against_greedy_random_seats(
        baseline_path,
        episodes=episodes,
        seed=seed + 200000,
        deck_matchups=deck_matchups,
    )
    candidate_greedy = aggregates["greedy"]
    candidate_average = candidate_greedy["winRate"]
    baseline_average = baseline["winRate"]
    errors = int(baseline["errors"]) + sum(int(row["errors"]) for row in rows)
    report = {
        "kind": "codeman_promotion_league_gate",
        "seed": seed,
        "episodesPerSeat": episodes,
        "candidatePath": str(candidate_path),
        "baselinePath": str(baseline_path),
        "normalCheckpointPath": str(normal_path) if normal_path.exists() else None,
        "deepCheckpointPath": str(deep_path) if deep_path.exists() else None,
        "currentChampionCheckpointPath": str(current_champion_path) if current_champion_path is not None else None,
        "hasCurrentChampion": current_champion_path is not None,
        "personalFirstChampion": current_champion_path is None and gate_deck_source == "memory_matchups",
        "deepBenchmarkRole": (
            "diagnostic_public_anchor"
            if current_champion_path is None and gate_deck_source == "memory_matchups"
            else "promotion_floor"
        ),
        "gateDeckSource": gate_deck_source,
        "gateDeckMatchupCount": len(deck_matchups or []),
        "targetEpisodesPerSeat": episodes,
        "episodesPerDeckMatchupSeat": gate_row_episodes,
        "opponents": [name for name, _ in opponent_specs],
        "greedyWinRate": candidate_average,
        "currentChampionWinRate": baseline_average,
        "candidateChampionWinRate": candidate_average,
        "targetImprovement": candidate_average - baseline_average,
        "secondPlayerImprovement": candidate_greedy["p2WinRate"] - baseline["p2WinRate"],
        "errors": errors,
        "baselineGreedyWinRate": baseline_average,
        "baselineP1WinRate": baseline["p1WinRate"],
        "baselineP2WinRate": baseline["p2WinRate"],
        "candidateP1WinRate": candidate_greedy["p1WinRate"],
        "candidateP2WinRate": candidate_greedy["p2WinRate"],
        "rowCount": len(rows),
        "rows": rows,
    }
    if "normal" in aggregates:
        report["normalWinRate"] = aggregates["normal"]["winRate"]
    if "deep" in aggregates:
        report["deepWinRate"] = aggregates["deep"]["winRate"]
    if "current_champion" in aggregates:
        report["candidateVsCurrentChampionWinRate"] = aggregates["current_champion"]["winRate"]
        report["directChampionImprovement"] = aggregates["current_champion"]["winRate"] - 0.50
    return report


def _evaluate_checkpoint_against_greedy_random_seats(
    path: str | Path,
    *,
    seed: int,
    episodes: int,
    deck_matchups: list[tuple[DeckSpec, DeckSpec]] | None = None,
) -> dict[str, Any]:
    if not deck_matchups:
        p1 = _evaluate_checkpoint(path, seed=seed, episodes=episodes, learner_side="P1")
        p2 = _evaluate_checkpoint(path, seed=seed + 1000, episodes=episodes, learner_side="P2")
        return {
            "winRate": (float(p1["winRate"]) + float(p2["winRate"])) / 2.0,
            "p1WinRate": float(p1["winRate"]),
            "p2WinRate": float(p2["winRate"]),
            "errors": int(p1["results"].get("errors", 0)) + int(p2["results"].get("errors", 0)),
        }

    rows: list[dict[str, Any]] = []
    gate_rows = _gate_deck_rows(deck_matchups)
    row_episodes = _gate_episodes_per_matchup(episodes, len(gate_rows))
    for matchup_index, learner_deck, opponent_deck in gate_rows:
        seed_matchup_index = matchup_index or 0
        for seat_index, candidate_seat in enumerate(("P1", "P2")):
            rows.append(_evaluate_candidate_matchup(
                candidate_path=Path(path),
                opponent_name="greedy",
                opponent_path=None,
                candidate_seat=candidate_seat,
                episodes=row_episodes,
                seed=seed + seed_matchup_index * 10000 + seat_index * 100,
                learner_deck=learner_deck,
                opponent_deck=opponent_deck,
                deck_source="memory_matchup",
                deck_matchup_index=matchup_index,
            ))
    aggregate = _aggregate_matchup_rows(rows, "greedy")
    return {
        "winRate": float(aggregate["winRate"]),
        "p1WinRate": float(aggregate["p1WinRate"]),
        "p2WinRate": float(aggregate["p2WinRate"]),
        "errors": int(aggregate["errors"]),
        "rows": rows,
    }


def _evaluate_candidate_matchup(
    *,
    candidate_path: Path,
    opponent_name: str,
    opponent_path: Path | None,
    candidate_seat: str,
    episodes: int,
    seed: int,
    learner_deck: DeckSpec | None = None,
    opponent_deck: DeckSpec | None = None,
    deck_source: str = "default",
    deck_matchup_index: int | None = None,
) -> dict[str, Any]:
    results = {"played": 0, "candidateWins": 0, "opponentWins": 0, "ties": 0, "errors": 0}
    turns_total = 0
    limited_games = 0
    candidate_timeouts = 0
    opponent_timeouts = 0
    for index in range(max(1, int(episodes))):
        game_seed = seed + index
        try:
            candidate_policy = _policy_for_checkpoint(candidate_path, game_seed + 17)
            opponent_policy = (
                GreedyLegalPolicy(random.Random(game_seed + 31))
                if opponent_path is None
                else _policy_for_checkpoint(opponent_path, game_seed + 31)
            )
            if candidate_seat == "P1":
                p1_policy, p2_policy = candidate_policy, opponent_policy
                p1_deck, p2_deck = learner_deck, opponent_deck
            else:
                p1_policy, p2_policy = opponent_policy, candidate_policy
                p1_deck, p2_deck = opponent_deck, learner_deck
            winner, turns, limited, limited_side = _play_gate_game_with_policy(
                game_seed,
                p1_policy=p1_policy,
                p2_policy=p2_policy,
                p1_recipe=_deck_recipe_or_none(p1_deck),
                p2_recipe=_deck_recipe_or_none(p2_deck),
                p1_forces=_deck_forces_or_none(p1_deck),
                p2_forces=_deck_forces_or_none(p2_deck),
            )
        except Exception as exc:  # pragma: no cover - diagnostic path for local training
            results["errors"] += 1
            continue
        if limited:
            limited_games += 1
            results["played"] += 1
            turns_total += turns
            if limited_side == candidate_seat:
                candidate_timeouts += 1
                results["opponentWins"] += 1
            else:
                opponent_timeouts += 1
                results["candidateWins"] += 1
            continue
        results["played"] += 1
        turns_total += turns
        if winner == "tie":
            results["ties"] += 1
        elif winner == candidate_seat:
            results["candidateWins"] += 1
        else:
            results["opponentWins"] += 1
    completed = max(1, results["played"])
    return {
        "opponent": opponent_name,
        "opponentCheckpointPath": None if opponent_path is None else str(opponent_path),
        "candidateSeat": candidate_seat,
        "deckSource": deck_source,
        "deckMatchupIndex": deck_matchup_index,
        "learnerDeckId": _deck_id_or_none(learner_deck),
        "learnerDeckName": _deck_name_or_none(learner_deck),
        "learnerForces": _deck_forces_or_none(learner_deck),
        "opponentDeckId": _deck_id_or_none(opponent_deck),
        "opponentDeckName": _deck_name_or_none(opponent_deck),
        "opponentForces": _deck_forces_or_none(opponent_deck),
        "episodes": episodes,
        "seed": seed,
        "results": results,
        "winRate": results["candidateWins"] / completed,
        "averageTurns": turns_total / completed,
        "errors": results["errors"],
        "limitedGames": limited_games,
        "candidateTimeouts": candidate_timeouts,
        "opponentTimeouts": opponent_timeouts,
    }


def _play_gate_game_with_policy(
    seed: int,
    *,
    p1_policy: Any,
    p2_policy: Any,
    p1_recipe: dict[str, int] | None = None,
    p2_recipe: dict[str, int] | None = None,
    p1_forces: list[str] | None = None,
    p2_forces: list[str] | None = None,
    max_turns: int = GATE_MAX_TURNS,
    max_actions: int = GATE_MAX_ACTIONS,
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
    actions = 0
    try:
        engine.begin_turn()
        while True:
            if engine.state.turn > max_turns or actions >= max_actions:
                return "tie", engine.state.turn, True, engine.state.active.name
            action = engine.policy_for(engine.state.active).choose(engine)
            actions += 1
            engine.apply(action)
    except GameOver as game_over:
        return game_over.winner.name if game_over.winner else "tie", engine.state.turn, False, None


def _aggregate_matchup_rows(rows: list[dict[str, Any]], opponent_name: str) -> dict[str, Any]:
    selected = [row for row in rows if row["opponent"] == opponent_name]
    played = sum(int(row["results"].get("played", 0)) for row in selected)
    wins = sum(int(row["results"].get("candidateWins", 0)) for row in selected)
    errors = sum(int(row.get("errors", 0)) for row in selected)
    p1_rows = [row for row in selected if row["candidateSeat"] == "P1"]
    p2_rows = [row for row in selected if row["candidateSeat"] == "P2"]
    return {
        "winRate": wins / max(1, played),
        "p1WinRate": _aggregate_seat_win_rate(p1_rows),
        "p2WinRate": _aggregate_seat_win_rate(p2_rows),
        "played": played,
        "errors": errors,
    }


def _aggregate_seat_win_rate(rows: list[dict[str, Any]]) -> float:
    played = sum(int(row["results"].get("played", 0)) for row in rows)
    wins = sum(int(row["results"].get("candidateWins", 0)) for row in rows)
    return wins / max(1, played)


def _policy_for_checkpoint(path: str | Path, seed: int) -> Any:
    path = Path(path)
    if path.suffix.lower() == ".json":
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = {}
        if isinstance(payload, dict) and bool(payload.get("runtimeLaunchableActor")):
            from zz.policy_factories import create_current_policy_actor_rollout_policy

            actor_id = str(payload.get("actorPolicyId") or payload.get("candidatePolicyId") or payload.get("modelId") or "")
            return create_current_policy_actor_rollout_policy(
                model_path=path,
                seed=seed,
                policy_id=actor_id,
                expected_candidate_policy_ids=[actor_id],
                expected_source_actor_policy_id=str(payload.get("sourceActorPolicyId") or ""),
                min_source_rows=0,
            )
    if path.suffix.lower() == ".pt":
        from zz.deep_rl import TorchActionValueModel
        from zz.rl_ai import (
            DEEP_LOOKAHEAD_BRANCH_WIDTH,
            DEEP_LOOKAHEAD_DEPTH,
            DEEP_LOOKAHEAD_KEY_DECISIONS_ONLY,
            DEEP_LOOKAHEAD_WEIGHT,
            DEEP_MAX_LOOKAHEAD_ACTIONS,
        )

        return LookaheadRLPolicy(
            model=TorchActionValueModel.load(path),
            rng=random.Random(seed),
            epsilon=0.0,
            lookahead_weight=DEEP_LOOKAHEAD_WEIGHT,
            max_lookahead_actions=DEEP_MAX_LOOKAHEAD_ACTIONS,
            lookahead_depth=DEEP_LOOKAHEAD_DEPTH,
            lookahead_branch_width=DEEP_LOOKAHEAD_BRANCH_WIDTH,
            lookahead_key_decisions_only=DEEP_LOOKAHEAD_KEY_DECISIONS_ONLY,
        )
    return LookaheadRLPolicy(model=LinearQModel.load(path), rng=random.Random(seed), epsilon=0.0)


def _evaluate_checkpoint(path: str | Path, *, seed: int, episodes: int, learner_side: str) -> dict[str, Any]:
    path = Path(path)
    if path.suffix.lower() == ".pt":
        from zz.deep_rl import run_deep_evaluation

        return run_deep_evaluation(
            model_path=path,
            episodes=episodes,
            seed=seed,
            opponent="greedy",
            learner_side=learner_side,
        )
    return run_evaluation(
        model_path=path,
        episodes=episodes,
        seed=seed,
        opponent="greedy",
        learner_side=learner_side,
    )
