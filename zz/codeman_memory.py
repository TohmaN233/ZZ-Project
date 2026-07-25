from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


DEFAULT_CODEMAN_AI_ROOT = Path(__file__).resolve().parent.parent / "data"
DEFAULT_CODEMAN_MEMORY_KEEP = 20


class CodemanMemoryStore:
    def __init__(self, root: str | Path | None = None):
        self.root = Path(root) if root is not None else DEFAULT_CODEMAN_AI_ROOT

    def append_game(self, codeman_id: str, row: dict[str, Any], *, keep: int = DEFAULT_CODEMAN_MEMORY_KEEP) -> Path:
        safe_id = self._safe_codeman_id(codeman_id)
        path = self._memory_path(safe_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload: dict[str, Any] = {
            "schema": 1,
            "codeman_id": safe_id,
        }
        payload.update(row)
        payload["schema"] = 1
        payload["codeman_id"] = safe_id
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=True, sort_keys=True))
            handle.write("\n")
        self.prune_recent_games(safe_id, keep=keep)
        return path

    def read_games(self, codeman_id: str) -> list[dict[str, Any]]:
        path = self._memory_path(self._safe_codeman_id(codeman_id))
        if not path.exists():
            return []
        rows: list[dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            rows.append(json.loads(line))
        return rows

    def list_game_summaries(self, codeman_id: str, *, limit: int | None = None) -> list[dict[str, Any]]:
        rows = [self._summary_for_row(row) for row in self.read_games(codeman_id)]
        rows.reverse()
        if limit is not None:
            return rows[:max(0, int(limit))]
        return rows

    def read_replay(self, codeman_id: str, match_id: str) -> dict[str, Any]:
        safe_id = self._safe_codeman_id(codeman_id)
        row = self._row_for_match(safe_id, match_id)
        if row is None:
            raise FileNotFoundError(match_id)
        return {
            "memory": self._summary_for_row(row),
            "trace": self._read_json_path(row.get("trace_path")),
            "correctedReplay": self._read_json_path(row.get("corrected_trace_path")),
        }

    def write_corrected_replay(
        self,
        codeman_id: str,
        match_id: str,
        replay: dict[str, Any],
        *,
        run_id: str,
    ) -> Path:
        safe_id = self._safe_codeman_id(codeman_id)
        rows = self.read_games(safe_id)
        target_index = next(
            (index for index, row in enumerate(rows) if str(row.get("match_id") or "") == str(match_id)),
            None,
        )
        if target_index is None:
            raise FileNotFoundError(match_id)
        safe_match = self._safe_filename(match_id)
        safe_run = self._safe_filename(run_id)
        rel_path = Path("codeman_ai") / safe_id / "corrected" / f"{safe_match}-{safe_run}.json"
        path = self.root / rel_path
        payload = dict(replay)
        payload.setdefault("schema", 1)
        payload.setdefault("kind", "codeman_corrected_replay")
        payload.setdefault("matchId", str(match_id))
        payload.setdefault("codemanId", safe_id)
        payload["runId"] = str(run_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=True, indent=2, default=str), encoding="utf-8")

        divergences = payload.get("divergences")
        rows[target_index].update({
            "ai_comeback": True,
            "corrected_trace_path": rel_path.as_posix(),
            "corrected_run_id": str(run_id),
            "corrected_divergence_count": len(divergences) if isinstance(divergences, list) else 0,
        })
        self._write_rows(safe_id, rows)
        return path

    def prune_recent_games(self, codeman_id: str, *, keep: int) -> int:
        safe_id = self._safe_codeman_id(codeman_id)
        path = self._memory_path(safe_id)
        if not path.exists():
            return 0
        rows = self.read_games(safe_id)
        keep_count = max(0, int(keep))
        retained = rows[-keep_count:] if keep_count else []
        dropped = rows[:len(rows) - len(retained)]
        removed = len(rows) - len(retained)
        self._remove_trace_files(dropped)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as handle:
            for row in retained:
                handle.write(json.dumps(row, ensure_ascii=True, sort_keys=True))
                handle.write("\n")
        return removed

    def _write_rows(self, codeman_id: str, rows: list[dict[str, Any]]) -> None:
        path = self._memory_path(codeman_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=True, sort_keys=True))
                handle.write("\n")

    def _row_for_match(self, codeman_id: str, match_id: str) -> dict[str, Any] | None:
        target = str(match_id)
        for row in self.read_games(codeman_id):
            if str(row.get("match_id") or "") == target:
                return row
        return None

    def _summary_for_row(self, row: dict[str, Any]) -> dict[str, Any]:
        corrected = bool(row.get("corrected_trace_path"))
        return {
            "matchId": row.get("match_id"),
            "mode": row.get("mode"),
            "seed": row.get("seed"),
            "playerSide": row.get("player_side"),
            "winnerSide": row.get("winner_side"),
            "turns": row.get("turns"),
            "reason": row.get("reason"),
            "opponentAiDifficulty": row.get("opponent_ai_difficulty"),
            "playerForces": list(row.get("player_forces") or []),
            "opponentForces": list(row.get("opponent_forces") or []),
            "hasTrace": bool(row.get("trace_path")),
            "aiComeback": bool(row.get("ai_comeback")),
            "correctedReplayAvailable": corrected,
            "correctedRunId": row.get("corrected_run_id"),
            "correctedDivergenceCount": int(row.get("corrected_divergence_count") or 0),
        }

    def _read_json_path(self, raw_path: Any) -> dict[str, Any] | None:
        path = self._resolve_owned_path(raw_path)
        if path is None or not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def _resolve_owned_path(self, raw_path: Any) -> Path | None:
        if not isinstance(raw_path, str) or not raw_path:
            return None
        try:
            root = self.root.resolve()
        except OSError:
            return None
        path = Path(raw_path)
        target = path if path.is_absolute() else self.root / path
        try:
            resolved = target.resolve()
        except OSError:
            return None
        if resolved == root or root not in resolved.parents:
            return None
        return resolved

    def _remove_trace_files(self, rows: list[dict[str, Any]]) -> None:
        for row in rows:
            for key in ("trace_path", "corrected_trace_path"):
                self._remove_owned_path(row.get(key))

    def _remove_owned_path(self, raw_path: Any) -> None:
        resolved = self._resolve_owned_path(raw_path)
        if resolved is None:
            return
        try:
            resolved.unlink()
        except FileNotFoundError:
            return
        except OSError:
            return

    def _safe_filename(self, value: str) -> str:
        safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value or "").strip()).strip("._")
        return safe or "replay"

    def _memory_path(self, codeman_id: str) -> Path:
        return self.root / "codeman_ai" / codeman_id / "memory.jsonl"

    def _safe_codeman_id(self, codeman_id: str) -> str:
        safe_id = str(codeman_id or "").strip()
        if not safe_id or "/" in safe_id or "\\" in safe_id or safe_id in {".", ".."}:
            raise ValueError(f"invalid codeman id: {codeman_id!r}")
        return safe_id
