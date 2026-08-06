from __future__ import annotations

import argparse
import json
import mimetypes
import os
import secrets
import shutil
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import RLock
from urllib.parse import parse_qs, unquote, urlparse

from zz.ai_registry import DEFAULT_DATA_ROOT, read_codeman_champion
from zz.codeman_memory import CodemanMemoryStore
from zz.codeman_replay_correction import attempt_memory_replay_correction
from zz.deck_ai import (
    DeckBuildConstraints,
    _color_inputs_from_recipe,
    deck_score,
    generate_completion_recipe,
    recipe_distribution,
)
from zz.decks import validate_forces, validate_user_deck_recipe
from zz.web.debug_tools import (
    add_debug_card_to_zone,
    build_debug_queue,
    move_debug_card,
    replace_debug_forces,
    set_debug_card_state,
    set_debug_force_state,
    set_debug_control,
    set_debug_life,
    setup_debug_fixed_board,
    setup_debug_lab,
)
from zz.web.catalog import catalog_dto
from zz.web.deck_store import DeckStore
from zz.web.settings_store import SettingsStore, normalize_ai_difficulty
from zz.web.session import GameSession


PROJECT_ROOT = Path(__file__).resolve().parents[2]
STATIC_DIR = Path(__file__).with_name("static")
DOCS_DIR = PROJECT_ROOT / "docs" / "rules"
HOME_IMAGE = PROJECT_ROOT / "image.png"
HOME_THEME_VIDEO = PROJECT_ROOT / "asserts" / "video" / "OP02.mp4"
DEV_MODE_PASSWORD_ENV = "ZZ_DEV_MODE_PASSWORD"
RULEBOOK_FILES = {
    "zh": "zz_rulebook_zh.md",
    "ja": "zz_rulebook_ja.md",
    "en": "zz_rulebook_en.md",
}


@dataclass
class ServerState:
    seed: int | None = None
    asset_root: str | Path | None = None
    deck_root: str | Path | None = None
    settings_root: str | Path | None = None
    ai_data_root: str | Path | None = None
    mode: str = "human-vs-ai"
    dev_mode: bool | None = None
    session: GameSession | None = None
    session_lock: object = field(default_factory=RLock, repr=False)

    def _random_seed(self) -> int:
        return secrets.randbelow(2_147_483_647)

    def _session_seed(self) -> int:
        if self.seed is None:
            self.seed = self._random_seed()
        return self.seed

    def ensure_session(self) -> GameSession:
        if self.session is None:
            settings = self.settings_store().load()
            self.session = GameSession(
                seed=self._session_seed(),
                mode=self.mode,
                asset_root=self.asset_root,
                player_profile=settings.get("playerProfile"),
                opponent_profile=settings.get("opponentProfile"),
                opponent_ai_difficulty=settings.get("opponentAiDifficulty", "deep"),
                ai_data_root=self.ai_data_root_path(),
            )
        return self.session

    def catalog(self) -> dict:
        session = self.ensure_session()
        payload = catalog_dto(session.asset_index)
        payload["devMode"] = self.is_dev_mode()
        return payload

    def is_dev_mode(self) -> bool:
        if self.dev_mode is True:
            return True
        if os.environ.get("ZENONZARD_DEV_MODE") == "1":
            return True
        try:
            return bool(self.settings().get("developerMode"))
        except (OSError, ValueError):
            return False

    def deck_store(self) -> DeckStore:
        return DeckStore(self.deck_root)

    def settings_store(self) -> SettingsStore:
        return SettingsStore(self.settings_root)

    def settings(self) -> dict:
        return self.settings_store().load()

    def ai_data_root_path(self) -> Path:
        return Path(self.ai_data_root) if self.ai_data_root is not None else DEFAULT_DATA_ROOT

    def _recipe_from_payload(self, payload: dict, key: str) -> dict[str, int] | None:
        raw = payload.get(key)
        if raw is None:
            return None
        if not isinstance(raw, dict):
            raise ValueError(f"{key} must be an object")
        recipe = {
            str(card_id): int(count)
            for card_id, count in raw.items()
            if int(count) > 0
        }
        validate_user_deck_recipe(recipe)
        return recipe

    def _forces_from_payload(self, payload: dict, key: str) -> list[str] | None:
        raw = payload.get(key)
        if raw is None:
            return None
        if not isinstance(raw, list):
            raise ValueError(f"{key} must be a list")
        return [str(force_id) for force_id in raw]

    def new_session(self, payload: dict | None) -> GameSession:
        payload = payload or {}
        if "seed" in payload and payload.get("seed") not in (None, ""):
            self.seed = int(payload["seed"])
        else:
            self.seed = self._random_seed()
        self.mode = payload.get("mode", self.mode)
        self.asset_root = payload.get("assetRoot", self.asset_root)
        first_player = payload.get("firstPlayer", "roll")
        human_side = _normalise_player_side(payload.get("humanSide") or payload.get("playerSide") or "P1")
        settings = self.settings()
        player_profile = payload.get("playerProfile", settings.get("playerProfile"))
        opponent_profile = payload.get("opponentProfile", settings.get("opponentProfile"))
        opponent_ai_difficulty = normalize_ai_difficulty(
            payload.get("opponentAiDifficulty", settings.get("opponentAiDifficulty", "deep"))
        )
        player_recipe = self._recipe_from_payload(payload, "playerDeck")
        player_force_ids = self._forces_from_payload(payload, "playerForces")
        opponent_recipe = self._recipe_from_payload(payload, "opponentDeck")
        opponent_force_ids = self._forces_from_payload(payload, "opponentForces")
        challenge_metadata = payload.get("challenge") if isinstance(payload.get("challenge"), dict) else None
        self.session = GameSession(
            seed=self._session_seed(),
            mode=self.mode,
            asset_root=self.asset_root,
            first_player=first_player,
            human_side=human_side,
            player_recipe=player_recipe,
            player_force_ids=player_force_ids,
            opponent_recipe=opponent_recipe,
            opponent_force_ids=opponent_force_ids,
            player_profile=player_profile,
            opponent_profile=opponent_profile,
            opponent_ai_difficulty=opponent_ai_difficulty,
            ai_data_root=self.ai_data_root_path(),
            challenge_metadata=challenge_metadata,
        )
        return self.session

    def set_mode(self, payload: dict | None) -> GameSession:
        payload = payload or {}
        mode = str(payload.get("mode", self.mode))
        if self.session is None:
            self.mode = mode
            return self.ensure_session()
        self.mode = mode
        self.session.set_mode(mode)
        return self.session


def _envelope(state: dict, dev_mode: bool = False) -> dict:
    state = {**state, "devMode": dev_mode}
    error = state.get("error")
    out = {"ok": error is None, "state": state}
    if error is not None:
        out["error"] = error
    return out


def _split_dispatch_path(path: str) -> tuple[str, dict[str, str]]:
    parsed = urlparse(path)
    query = {
        key: values[-1]
        for key, values in parse_qs(parsed.query, keep_blank_values=False).items()
        if values
    }
    return parsed.path, query


def _ai_difficulties() -> list[dict[str, str]]:
    return [
        {"id": "easy", "label": "Easy", "policy": "greedy"},
        {"id": "normal", "label": "Medium", "policy": "linear"},
        {"id": "deep", "label": "High", "policy": "deep"},
    ]


def _normalise_player_side(value: object) -> str:
    return "P2" if str(value or "").strip().upper() == "P2" else "P1"


def _codeman_status(app: ServerState, codeman_id: str) -> dict:
    data_root = app.ai_data_root_path()
    memory_games = len(CodemanMemoryStore(data_root).read_games(codeman_id))
    latest_report = _latest_codeman_report(data_root, codeman_id)
    return {
        "codemanId": codeman_id,
        "memoryGames": memory_games,
        "champion": read_codeman_champion(codeman_id, data_root=data_root),
        "latestReport": latest_report,
    }


def _latest_codeman_report(data_root: Path, codeman_id: str) -> dict | None:
    reports_dir = data_root / "codeman_ai" / codeman_id / "reports"
    if not reports_dir.exists():
        return None
    reports = sorted(reports_dir.glob("*.json"), key=lambda path: path.stat().st_mtime, reverse=True)
    if not reports:
        return None
    try:
        return json.loads(reports[0].read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _safe_path_component(value: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in {"_", "-", "."} else "_" for ch in str(value or "").strip())
    return safe.strip("._") or "item"


def _codeman_progress_path(app: ServerState, codeman_id: str, run_id: str) -> Path:
    safe_id = _safe_path_component(codeman_id)
    safe_run = _safe_path_component(run_id)
    return app.ai_data_root_path() / "codeman_ai" / safe_id / "progress" / f"{safe_run}.json"


def _latest_codeman_progress_path(app: ServerState, codeman_id: str) -> Path | None:
    progress_dir = app.ai_data_root_path() / "codeman_ai" / _safe_path_component(codeman_id) / "progress"
    if not progress_dir.exists():
        return None
    paths = sorted(progress_dir.glob("*.json"), key=lambda path: path.stat().st_mtime, reverse=True)
    return paths[0] if paths else None


def _read_codeman_progress(app: ServerState, codeman_id: str, run_id: str | None) -> dict | None:
    path = _codeman_progress_path(app, codeman_id, run_id) if run_id else _latest_codeman_progress_path(app, codeman_id)
    if path is None or not path.exists():
        return None
    try:
        progress = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if isinstance(progress, dict):
        progress["progressPath"] = str(path)
        return progress
    return None


def _partial_recipe_from_payload(raw: object) -> dict[str, int]:
    if not isinstance(raw, dict):
        raise ValueError("recipe must be an object")
    recipe: dict[str, int] = {}
    for card_id, count in raw.items():
        count_int = int(count)
        if count_int > 0:
            recipe[str(card_id)] = count_int
    return recipe


def _complete_deck_payload(payload: dict | None, seed: int) -> dict:
    body = payload or {}
    recipe = _partial_recipe_from_payload(body.get("recipe", {}))
    forces = [str(force_id) for force_id in body.get("forces", [])]
    validate_forces(forces)
    current_cards = sum(recipe.values())
    if current_cards < 15:
        raise ValueError(f"deck completion requires at least 15 cards (got {current_cards})")
    completion_seed = int(body.get("seed", seed))
    colors = [str(color) for color in body.get("colors", [])] or _color_inputs_from_recipe(recipe)
    constraints = DeckBuildConstraints.from_inputs(colors, forces)
    completed = generate_completion_recipe(
        recipe,
        constraints,
        seed=completion_seed,
        reference_recipe=recipe,
    )
    distribution = recipe_distribution(completed)
    distribution["total"] = distribution.get("total_cards", sum(completed.values()))
    added = {
        card_id: count - recipe.get(card_id, 0)
        for card_id, count in completed.items()
        if count > recipe.get(card_id, 0)
    }
    return {
        "seed": completion_seed,
        "recipe": completed,
        "addedRecipe": added,
        "forces": forces,
        "colors": [color.name.lower() for color in constraints.colors],
        "cards": sum(completed.values()),
        "sourceCards": current_cards,
        "distribution": distribution,
        "heuristic": deck_score(completed, constraints),
        "warnings": list(constraints.warnings),
    }


def _needs_session_lock(method: str, route: str) -> bool:
    if route.startswith("/api/debug"):
        return True
    if route in {
        "/api/catalog",
        "/api/state",
        "/api/new-game",
        "/api/leave-game",
        "/api/mode",
        "/api/choose",
        "/api/advice",
        "/api/auto-step",
    }:
        return True
    return False


def dispatch_api(app: ServerState, method: str, path: str, payload: dict | None) -> tuple[int, dict]:
    route, query = _split_dispatch_path(path)
    if _needs_session_lock(method, route):
        with app.session_lock:
            return _dispatch_api_unlocked(app, method, route, query, path, payload)
    return _dispatch_api_unlocked(app, method, route, query, path, payload)


def _dispatch_api_unlocked(
    app: ServerState,
    method: str,
    route: str,
    query: dict[str, str],
    path: str,
    payload: dict | None,
) -> tuple[int, dict]:
    if method == "GET" and route == "/api/catalog":
        return 200, app.catalog()
    if method == "GET" and route == "/api/ai/difficulties":
        return 200, {"ok": True, "difficulties": _ai_difficulties()}
    if method == "POST" and route == "/api/ai/league":
        from zz.ai_league import run_difficulty_league_evaluation

        body = payload or {}
        try:
            report = run_difficulty_league_evaluation(
                episodes=int(body.get("episodes", 1)),
                seed=int(body.get("seed", app._session_seed())),
                normal_model_path=body.get("normalModelPath"),
                deep_model_path=body.get("deepModelPath"),
                data_root=app.ai_data_root_path(),
            )
        except (OSError, TypeError, ValueError) as exc:
            return 400, {"ok": False, "error": {"code": "invalid_ai_league", "message": str(exc)}}
        return 200, {"ok": True, "report": report}
    if route.startswith("/api/codeman-ai/"):
        suffix = route[len("/api/codeman-ai/"):]
        is_runs = suffix.endswith("/training-runs")
        is_progress = suffix.endswith("/training-progress")
        is_train = suffix.endswith("/train")
        is_memory = suffix.endswith("/memory")
        is_memory_replay = "/memory/" in suffix
        is_memory_correction = is_memory_replay and suffix.endswith("/correct")
        memory_match_id = ""
        if is_memory_correction:
            codeman_id, memory_match_id = suffix[:-len("/correct")].split("/memory/", 1)
            codeman_id = unquote(codeman_id)
            memory_match_id = unquote(memory_match_id)
        elif is_memory_replay:
            codeman_id, memory_match_id = suffix.split("/memory/", 1)
            codeman_id = unquote(codeman_id)
            memory_match_id = unquote(memory_match_id)
        elif is_memory:
            codeman_id = unquote(suffix[:-len("/memory")])
        elif is_runs:
            codeman_id = unquote(suffix[:-len("/training-runs")])
        elif is_progress:
            codeman_id = unquote(suffix[:-len("/training-progress")])
        elif is_train:
            codeman_id = unquote(suffix[:-len("/train")])
        else:
            codeman_id = unquote(suffix)
        if not codeman_id:
            return 400, {"ok": False, "error": {"code": "invalid_codeman", "message": "missing Codeman id"}}
        if method == "GET" and is_memory:
            try:
                limit = int(query["limit"]) if "limit" in query else None
                memory = CodemanMemoryStore(app.ai_data_root_path()).list_game_summaries(codeman_id, limit=limit)
            except (OSError, TypeError, ValueError) as exc:
                return 400, {"ok": False, "error": {"code": "invalid_codeman_memory", "message": str(exc)}}
            return 200, {"ok": True, "codemanId": codeman_id, "memory": memory}
        if method == "GET" and is_memory_replay:
            try:
                replay = CodemanMemoryStore(app.ai_data_root_path()).read_replay(codeman_id, memory_match_id)
            except FileNotFoundError:
                return 404, {"ok": False, "error": {"code": "codeman_replay_not_found", "message": memory_match_id}}
            except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
                return 400, {"ok": False, "error": {"code": "invalid_codeman_replay", "message": str(exc)}}
            return 200, {"ok": True, "codemanId": codeman_id, "replay": replay}
        if method == "POST" and is_memory_correction:
            body = payload or {}
            try:
                result = attempt_memory_replay_correction(
                    codeman_id,
                    memory_match_id,
                    data_root=app.ai_data_root_path(),
                    decision_window=int(body.get("decisionWindow", 10)),
                    alternatives_per_decision=int(body.get("alternativesPerDecision", 3)),
                    run_id=body.get("runId"),
                )
            except FileNotFoundError:
                return 404, {"ok": False, "error": {"code": "codeman_replay_not_found", "message": memory_match_id}}
            except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
                return 400, {"ok": False, "error": {"code": "invalid_codeman_replay_correction", "message": str(exc)}}
            return 200, {"ok": True, "codemanId": codeman_id, "result": result}
        if method == "GET" and is_runs:
            from zz.codeman_training import list_codeman_training_runs

            try:
                limit = int(query["limit"]) if "limit" in query else None
                runs = list_codeman_training_runs(codeman_id, data_root=app.ai_data_root_path(), limit=limit)
            except (OSError, TypeError, ValueError) as exc:
                return 400, {"ok": False, "error": {"code": "invalid_codeman_runs", "message": str(exc)}}
            return 200, {"ok": True, "codemanId": codeman_id, "runs": runs}
        if method == "GET" and is_progress:
            progress = _read_codeman_progress(app, codeman_id, query.get("runId"))
            return 200, {
                "ok": True,
                "codemanId": codeman_id,
                "progress": progress or {
                    "state": "idle",
                    "stage": "idle",
                    "percent": 0,
                    "codemanId": codeman_id,
                    "runId": query.get("runId"),
                },
            }
        if method == "GET" and not is_train:
            return 200, {"ok": True, "codeman": _codeman_status(app, codeman_id)}
        if method == "POST" and is_train:
            from zz.codeman_training import run_codeman_training

            body = payload or {}
            run_id = str(body.get("runId") or "").strip() or None
            try:
                report = run_codeman_training(
                    codeman_id,
                    data_root=app.ai_data_root_path(),
                    warm_start_model_path=body.get("warmStartModelPath"),
                    normal_model_path=body.get("normalModelPath"),
                    deep_model_path=body.get("deepModelPath"),
                    preset=str(body.get("preset") or "standard"),
                    rounds=int(body["rounds"]) if "rounds" in body else None,
                    gate_metrics=body.get("gateMetrics") if "gateMetrics" in body else None,
                    run_id=run_id,
                    progress_path=_codeman_progress_path(app, codeman_id, run_id) if run_id else None,
                    circles=int(body["circles"]) if "circles" in body else None,
                    training_method=str(body.get("trainingMethod") or "gae_epoch1_local"),
                    checkpoint_interval=int(body.get("checkpointInterval") or 5),
                )
            except (OSError, RuntimeError, TypeError, ValueError) as exc:
                return 400, {"ok": False, "error": {"code": "invalid_codeman_training", "message": str(exc)}}
            return 200, {"ok": True, "report": report, "codeman": _codeman_status(app, codeman_id)}
    if route.startswith("/api/debug"):
        if not app.is_dev_mode():
            return 403, {
                "ok": False,
                "error": {
                    "code": "dev_mode_required",
                    "message": "Professional debug mode is disabled.",
                },
            }
        if method == "GET" and route == "/api/debug/status":
            return 200, {"ok": True, "devMode": True, "mode": "debug-card-lab"}
        if method == "GET" and route == "/api/debug/cards":
            debug = build_debug_queue(app.catalog()["cards"], query)
            return 200, {"ok": True, "devMode": True, "debug": debug}
        if method == "POST" and route in {"/api/debug/setup", "/api/debug/reset"}:
            try:
                body = payload or {}
                card_id = str(body.get("cardId") or "")
                session = app.new_session({
                    "mode": "debug-card-lab",
                    "seed": body.get("seed"),
                    "firstPlayer": "human",
                    "playerProfile": body.get("playerProfile"),
                    "opponentProfile": body.get("opponentProfile"),
                })
                debug = setup_debug_lab(
                    session,
                    card_id,
                    zone=str(body.get("zone") or "hand"),
                    player_forces=body.get("playerForces"),
                    opponent_forces=body.get("opponentForces"),
                    compact_board=bool(body.get("compactBoard", False)),
                    non_minion_mana_only=bool(body.get("nonMinionManaOnly", False)),
                )
            except ValueError as exc:
                return 400, {"ok": False, "error": {"code": "invalid_debug_setup", "message": str(exc)}}
            out = _envelope(session.state_dto(), app.is_dev_mode())
            out["debug"] = debug
            return 200, out
        if method == "POST" and route == "/api/debug/forces":
            try:
                session = app.ensure_session()
                body = payload or {}
                debug = replace_debug_forces(session, str(body.get("side") or ""), list(body.get("forceIds") or []))
            except (KeyError, ValueError) as exc:
                return 400, {"ok": False, "error": {"code": "invalid_debug_forces", "message": str(exc)}}
            out = _envelope(session.state_dto(), app.is_dev_mode())
            out["debug"] = debug
            return 200, out
        if method == "POST" and route == "/api/debug/add-card":
            try:
                session = app.ensure_session()
                body = payload or {}
                debug = add_debug_card_to_zone(
                    session,
                    str(body.get("cardId") or ""),
                    side=str(body.get("side") or "P1"),
                    zone=str(body.get("zone") or "hand"),
                    rested=bool(body.get("rested", False)),
                )
            except (KeyError, ValueError) as exc:
                return 400, {"ok": False, "error": {"code": "invalid_debug_add_card", "message": str(exc)}}
            out = _envelope(session.state_dto(), app.is_dev_mode())
            out["debug"] = debug
            return 200, out
        if method == "POST" and route == "/api/debug/move-card":
            try:
                session = app.ensure_session()
                body = payload or {}
                debug = move_debug_card(
                    session,
                    int(body.get("iid")),
                    zone=str(body.get("zone") or "hand"),
                    rested=body.get("rested") if "rested" in body else None,
                )
            except (TypeError, ValueError) as exc:
                return 400, {"ok": False, "error": {"code": "invalid_debug_move_card", "message": str(exc)}}
            out = _envelope(session.state_dto(), app.is_dev_mode())
            out["debug"] = debug
            return 200, out
        if method == "POST" and route == "/api/debug/card-state":
            try:
                session = app.ensure_session()
                body = payload or {}
                debug = set_debug_card_state(
                    session,
                    int(body.get("iid")),
                    rested=body.get("rested") if "rested" in body else None,
                    permanent_bp_modifier=(
                        None if "permanentBpModifier" not in body else int(body.get("permanentBpModifier"))
                    ),
                    permanent_dp_modifier=(
                        None if "permanentDpModifier" not in body else int(body.get("permanentDpModifier"))
                    ),
                )
            except (TypeError, ValueError) as exc:
                return 400, {"ok": False, "error": {"code": "invalid_debug_card_state", "message": str(exc)}}
            out = _envelope(session.state_dto(), app.is_dev_mode())
            out["debug"] = debug
            return 200, out
        if method == "POST" and route == "/api/debug/control":
            session = app.ensure_session()
            debug = set_debug_control(session, bool((payload or {}).get("controlBoth", False)))
            out = _envelope(session.state_dto(), app.is_dev_mode())
            out["debug"] = debug
            return 200, out
        if method == "POST" and route == "/api/debug/fixed-board":
            try:
                session = app.ensure_session()
                body = payload or {}
                debug = setup_debug_fixed_board(
                    session,
                    active_side=str(body.get("activeSide") or "P1"),
                    control_both=bool(body.get("controlBoth", True)),
                    preserve_board=bool(body.get("preserveBoard", False)),
                    step=str(body.get("step") or "main"),
                )
            except (KeyError, ValueError) as exc:
                return 400, {"ok": False, "error": {"code": "invalid_debug_fixed_board", "message": str(exc)}}
            out = _envelope(session.state_dto(), app.is_dev_mode())
            out["debug"] = debug
            return 200, out
        if method == "POST" and route == "/api/debug/life":
            try:
                session = app.ensure_session()
                body = payload or {}
                debug = set_debug_life(
                    session,
                    side=str(body.get("side") or "P1"),
                    life=int(body.get("life")),
                    force_index=int(body["forceIndex"]) if "forceIndex" in body else None,
                )
            except (KeyError, TypeError, ValueError, IndexError) as exc:
                return 400, {"ok": False, "error": {"code": "invalid_debug_life", "message": str(exc)}}
            out = _envelope(session.state_dto(), app.is_dev_mode())
            out["debug"] = debug
            return 200, out
        if method == "POST" and route == "/api/debug/force-state":
            try:
                session = app.ensure_session()
                body = payload or {}
                debug = set_debug_force_state(
                    session,
                    side=str(body.get("side") or "P1"),
                    force_index=int(body.get("forceIndex")),
                    destroyed=bool(body.get("destroyed", False)),
                    rested=None if "rested" not in body else bool(body.get("rested")),
                )
            except (KeyError, TypeError, ValueError, IndexError) as exc:
                return 400, {"ok": False, "error": {"code": "invalid_debug_force_state", "message": str(exc)}}
            out = _envelope(session.state_dto(), app.is_dev_mode())
            out["debug"] = debug
            return 200, out
        if method == "POST" and route in {"/api/debug/select-card", "/api/debug/navigate"}:
            debug = build_debug_queue(app.catalog()["cards"], query)
            body = payload or {}
            selected = str(body.get("cardId") or "")
            if selected:
                for index, card in enumerate(debug["queue"]):
                    if card["cardId"] == selected:
                        debug["index"] = index
                        break
            return 200, {"ok": True, "devMode": True, "debug": debug}
        return 404, {"ok": False, "error": {"code": "not_found", "message": path}}
    if method == "GET" and route == "/api/settings":
        return 200, {"ok": True, "settings": app.settings()}
    if method == "POST" and route == "/api/settings":
        try:
            settings = app.settings_store().save(payload or {})
        except ValueError as exc:
            return 400, {"ok": False, "error": {"code": "invalid_settings", "message": str(exc)}}
        return 200, {"ok": True, "settings": settings}
    if method == "POST" and route == "/api/settings/developer-mode":
        body = payload or {}
        enabled = bool(body.get("enabled", False))
        if enabled:
            expected_password = os.environ.get(DEV_MODE_PASSWORD_ENV, "")
            if not expected_password:
                return 503, {
                    "ok": False,
                    "error": {
                        "code": "developer_mode_unconfigured",
                        "message": f"set {DEV_MODE_PASSWORD_ENV} before enabling developer mode",
                    },
                }
            supplied_password = str(body.get("password") or "")
            if not secrets.compare_digest(supplied_password, expected_password):
                return 403, {
                    "ok": False,
                    "error": {"code": "invalid_developer_password", "message": "invalid developer password"},
                }
        settings = app.settings_store().set_developer_mode(enabled)
        return 200, {"ok": True, "settings": settings, "devMode": app.is_dev_mode()}
    if method == "GET" and route == "/api/decks":
        return 200, {"ok": True, "decks": app.deck_store().list_decks()}
    if method == "POST" and route == "/api/decks/ai-complete":
        try:
            completion = _complete_deck_payload(payload, app._session_seed())
        except (TypeError, ValueError) as exc:
            return 400, {
                "ok": False,
                "error": {"code": "invalid_deck_completion", "message": str(exc)},
            }
        return 200, {"ok": True, "completion": completion}
    if method == "POST" and route == "/api/decks":
        try:
            deck = app.deck_store().save_deck(payload or {})
        except ValueError as exc:
            return 400, {"ok": False, "error": {"code": "invalid_deck", "message": str(exc)}}
        return 200, {"ok": True, "deck": deck}
    if method == "DELETE" and route.startswith("/api/decks/"):
        deck_id = unquote(route[len("/api/decks/"):])
        try:
            deleted = app.deck_store().delete_deck(deck_id)
        except ValueError as exc:
            return 400, {"ok": False, "error": {"code": "invalid_deck", "message": str(exc)}}
        return 200, {"ok": True, "deleted": deleted}
    if method == "GET" and route == "/api/state":
        return 200, _envelope(app.ensure_session().state_dto(), app.is_dev_mode())
    if method == "POST" and route == "/api/new-game":
        try:
            return 200, _envelope(app.new_session(payload).state_dto(), app.is_dev_mode())
        except ValueError as exc:
            return 400, {"ok": False, "error": {"code": "invalid_deck", "message": str(exc)}}
    if method == "POST" and route == "/api/leave-game":
        app.session = None
        return 200, {"ok": True}
    if method == "POST" and route == "/api/mode":
        try:
            return 200, _envelope(app.set_mode(payload).state_dto(), app.is_dev_mode())
        except ValueError as exc:
            return 400, {"ok": False, "error": {"code": "invalid_mode", "message": str(exc)}}
    if method == "POST" and route == "/api/choose":
        session = app.ensure_session()
        payload = payload or {}
        state = session.choose(str(payload.get("promptId", "")), str(payload.get("optionId", "")), payload)
        return 200, _envelope(state, app.is_dev_mode())
    if method == "POST" and route == "/api/advice":
        return 200, {"ok": True, "advice": app.ensure_session().advice()}
    if method == "POST" and route == "/api/auto-step":
        session = app.ensure_session()
        payload = payload or {}
        limit = int(payload.get("limit", 1))
        return 200, _envelope(session.auto_step(limit=limit), app.is_dev_mode())
    return 404, {"ok": False, "error": {"code": "not_found", "message": path}}


def _read_json(handler: BaseHTTPRequestHandler) -> dict:
    length = int(handler.headers.get("Content-Length", "0") or "0")
    if length <= 0:
        return {}
    raw = handler.rfile.read(length)
    if not raw:
        return {}
    return json.loads(raw.decode("utf-8"))


def _write_json(handler: BaseHTTPRequestHandler, status: int, payload: dict) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _safe_static_path(name: str) -> Path | None:
    rel = unquote(name).lstrip("/")
    path = (STATIC_DIR / rel).resolve()
    try:
        path.relative_to(STATIC_DIR.resolve())
    except ValueError:
        return None
    if not path.is_file():
        return None
    return path


class ZenonzardHandler(BaseHTTPRequestHandler):
    app: ServerState

    def log_message(self, format, *args):
        return

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self._send_file(STATIC_DIR / "index.html")
            return
        if parsed.path == "/duel":
            self._send_file(STATIC_DIR / "duel.html")
            return
        if parsed.path == "/image.png":
            self._send_file(HOME_IMAGE)
            return
        if parsed.path == "/theme/op02.mp4":
            self._send_file(HOME_THEME_VIDEO)
            return
        if parsed.path == "/rules" or parsed.path.startswith("/rules/"):
            lang = parsed.path.rsplit("/", 1)[-1] if parsed.path != "/rules" else "zh"
            self._send_rulebook(lang)
            return
        if parsed.path.startswith("/static/"):
            self._send_static(parsed.path[len("/static/"):])
            return
        if parsed.path.startswith("/assets/"):
            self._send_asset(parsed.path[len("/assets/"):])
            return
        if parsed.path.startswith("/audio/"):
            self._send_audio(parsed.path[len("/audio/"):])
            return
        if parsed.path.startswith("/api/"):
            status, payload = dispatch_api(self.app, "GET", self.path, None)
            _write_json(self, status, payload)
            return
        _write_json(self, 404, {"ok": False, "error": {"code": "not_found", "message": parsed.path}})

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/"):
            try:
                payload = _read_json(self)
            except json.JSONDecodeError as exc:
                _write_json(self, 400, {"ok": False, "error": {"code": "bad_json", "message": str(exc)}})
                return
            status, out = dispatch_api(self.app, "POST", self.path, payload)
            _write_json(self, status, out)
            return
        _write_json(self, 404, {"ok": False, "error": {"code": "not_found", "message": parsed.path}})

    def do_DELETE(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/"):
            status, out = dispatch_api(self.app, "DELETE", self.path, None)
            _write_json(self, status, out)
            return
        _write_json(self, 404, {"ok": False, "error": {"code": "not_found", "message": parsed.path}})

    def _send_static(self, name: str) -> None:
        path = _safe_static_path(name)
        if path is None:
            _write_json(self, 404, {"ok": False, "error": {"code": "not_found", "message": name}})
            return
        self._send_file(path)

    def _send_asset(self, asset_id: str) -> None:
        session = self.app.ensure_session()
        path = session.asset_index.resolve_asset_id(unquote(asset_id))
        if path is None:
            _write_json(self, 404, {"ok": False, "error": {"code": "asset_not_found", "message": asset_id}})
            return
        self._send_file(path)

    def _send_audio(self, audio_id: str) -> None:
        session = self.app.ensure_session()
        path = session.asset_index.resolve_audio_id(unquote(audio_id))
        if path is None:
            _write_json(self, 404, {"ok": False, "error": {"code": "audio_not_found", "message": audio_id}})
            return
        self._send_file(path)

    def _send_rulebook(self, language: str) -> None:
        filename = RULEBOOK_FILES.get(str(language or "").lower())
        if filename is None:
            _write_json(self, 404, {"ok": False, "error": {"code": "rulebook_not_found", "message": language}})
            return
        path = (DOCS_DIR / filename).resolve()
        try:
            path.relative_to(DOCS_DIR.resolve())
        except ValueError:
            _write_json(self, 404, {"ok": False, "error": {"code": "rulebook_not_found", "message": language}})
            return
        if not path.is_file():
            _write_json(self, 404, {"ok": False, "error": {"code": "rulebook_not_found", "message": language}})
            return
        body = path.read_text(encoding="utf-8").encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/markdown; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path: Path) -> None:
        if not path.is_file():
            _write_json(self, 404, {"ok": False, "error": {"code": "not_found", "message": str(path)}})
            return
        body = path.read_bytes()
        content_type = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        if path.suffix == ".js":
            content_type = "text/javascript"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        if path.resolve().is_relative_to(STATIC_DIR.resolve()):
            self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)


def make_server(host: str, port: int, app: ServerState) -> ThreadingHTTPServer:
    class Handler(ZenonzardHandler):
        pass
    Handler.app = app
    return ThreadingHTTPServer((host, port), Handler)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--mode", choices=["human-vs-ai", "ai-vs-ai", "god"], default="human-vs-ai")
    parser.add_argument("--asset-root", default=None)
    parser.add_argument("--user-data-root", default=None)
    parser.add_argument("--dev-mode", action="store_true")
    args = parser.parse_args(argv)
    user_data_root = Path(args.user_data_root).expanduser().resolve() if args.user_data_root else None
    if user_data_root is not None:
        for name in ("decks", "settings", "codeman_ai", "ai_challenges"):
            (user_data_root / name).mkdir(parents=True, exist_ok=True)
        bundled_decks = PROJECT_ROOT / "data" / "decks"
        user_decks = user_data_root / "decks"
        if bundled_decks.is_dir() and not any(user_decks.glob("*.json")):
            for source in bundled_decks.glob("*.json"):
                shutil.copy2(source, user_decks / source.name)
    app = ServerState(
        seed=args.seed,
        asset_root=args.asset_root,
        deck_root=user_data_root / "decks" if user_data_root is not None else None,
        settings_root=user_data_root / "settings" if user_data_root is not None else None,
        ai_data_root=user_data_root if user_data_root is not None else None,
        mode=args.mode,
        dev_mode=args.dev_mode,
    )
    server = make_server(args.host, args.port, app)
    host, port = server.server_address
    print(f"Serving Zenonzard web frontend at http://{host}:{port}/", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
