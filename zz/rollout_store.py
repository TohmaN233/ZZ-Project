from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable


ROLLOUT_STORE_SCHEMA_VERSION = 1
ROLLOUT_TASK_STATES = ("pending", "running", "done", "failed", "cancelled")

_TASK_STATUS_SQL = ", ".join(f"'{status}'" for status in ROLLOUT_TASK_STATES)


def connect_rollout_store(path: str | Path) -> sqlite3.Connection:
    db_path = Path(path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def initialize_rollout_store(conn: sqlite3.Connection) -> None:
    conn.executescript(
        f"""
        CREATE TABLE IF NOT EXISTS schema_version (
            key TEXT PRIMARY KEY,
            version INTEGER NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS rollout_run (
            run_id TEXT PRIMARY KEY,
            created_at TEXT NOT NULL,
            purpose TEXT NOT NULL,
            policy_id TEXT NOT NULL,
            teacher_id TEXT,
            scorer_id TEXT,
            suite_id TEXT,
            runtime_weights_json TEXT NOT NULL,
            metadata_json TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS deck (
            deck_id TEXT PRIMARY KEY,
            deck_name TEXT NOT NULL,
            source TEXT NOT NULL,
            deck_hash TEXT NOT NULL,
            summary_json TEXT NOT NULL,
            card_embedding_version TEXT,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS rollout_task (
            task_id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL REFERENCES rollout_run(run_id),
            player_deck_id TEXT NOT NULL REFERENCES deck(deck_id),
            opponent_deck_id TEXT NOT NULL,
            model_side TEXT NOT NULL,
            true_turn_order TEXT NOT NULL,
            difficulty TEXT NOT NULL,
            seed INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ({_TASK_STATUS_SQL})),
            task_spec_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            claimed_by TEXT,
            claim_expires_at TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_rollout_task_run_status
            ON rollout_task(run_id, status, task_id);

        CREATE TABLE IF NOT EXISTS game_result (
            result_id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id TEXT NOT NULL REFERENCES rollout_task(task_id),
            run_id TEXT NOT NULL REFERENCES rollout_run(run_id),
            game_index INTEGER NOT NULL,
            winner TEXT,
            turns INTEGER,
            error_json TEXT,
            result_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS decision_summary (
            summary_id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id TEXT NOT NULL REFERENCES rollout_task(task_id),
            run_id TEXT NOT NULL REFERENCES rollout_run(run_id),
            decision_kind TEXT NOT NULL,
            summary_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS action_set_shard (
            shard_id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL REFERENCES rollout_run(run_id),
            path TEXT NOT NULL,
            compression TEXT,
            row_count INTEGER NOT NULL DEFAULT 0,
            card_embedding_version TEXT,
            metadata_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS deck_eval_summary (
            summary_id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL REFERENCES rollout_run(run_id),
            deck_id TEXT NOT NULL REFERENCES deck(deck_id),
            opponent_id TEXT,
            difficulty TEXT,
            true_turn_order TEXT,
            summary_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS card_usage_summary (
            summary_id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL REFERENCES rollout_run(run_id),
            deck_id TEXT NOT NULL REFERENCES deck(deck_id),
            card_id TEXT NOT NULL,
            summary_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS hard_state (
            hard_state_id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL REFERENCES rollout_run(run_id),
            task_id TEXT REFERENCES rollout_task(task_id),
            state_kind TEXT NOT NULL,
            priority REAL NOT NULL DEFAULT 0.0,
            shard_path TEXT,
            metadata_json TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ({_TASK_STATUS_SQL})),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        """
    )
    conn.execute(
        """
        INSERT INTO schema_version(key, version, updated_at)
        VALUES ('rollout_store', ?, ?)
        ON CONFLICT(key) DO UPDATE SET
            version = excluded.version,
            updated_at = excluded.updated_at
        """,
        (ROLLOUT_STORE_SCHEMA_VERSION, _utc_now()),
    )
    conn.commit()


def deterministic_rollout_task_id(
    *,
    run_id: str,
    player_deck_id: str,
    opponent_deck_id: str,
    model_side: str,
    true_turn_order: str,
    difficulty: str,
    seed: int,
) -> str:
    payload = {
        "runId": run_id,
        "playerDeckId": player_deck_id,
        "opponentDeckId": opponent_deck_id,
        "modelSide": model_side,
        "trueTurnOrder": true_turn_order,
        "difficulty": difficulty,
        "seed": int(seed),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return f"task-{hashlib.sha256(encoded).hexdigest()[:16]}"


def create_rollout_run(
    conn: sqlite3.Connection,
    *,
    run_id: str,
    purpose: str,
    policy_id: str,
    suite_id: str | None = None,
    teacher_id: str | None = None,
    scorer_id: str | None = None,
    runtime_weights: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO rollout_run(
            run_id,
            created_at,
            purpose,
            policy_id,
            teacher_id,
            scorer_id,
            suite_id,
            runtime_weights_json,
            metadata_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            run_id,
            _utc_now(),
            purpose,
            policy_id,
            teacher_id,
            scorer_id,
            suite_id,
            _json_dumps(runtime_weights or {}),
            _json_dumps(metadata or {}),
        ),
    )


def upsert_deck_summary(conn: sqlite3.Connection, summary: dict[str, Any]) -> None:
    deck_id = str(summary["deckId"])
    conn.execute(
        """
        INSERT INTO deck(deck_id, deck_name, source, deck_hash, summary_json, card_embedding_version, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(deck_id) DO UPDATE SET
            deck_name = excluded.deck_name,
            source = excluded.source,
            deck_hash = excluded.deck_hash,
            summary_json = excluded.summary_json,
            card_embedding_version = excluded.card_embedding_version,
            updated_at = excluded.updated_at
        """,
        (
            deck_id,
            str(summary.get("deckName") or deck_id),
            str(summary.get("source") or ""),
            str(summary.get("deckHash") or ""),
            _json_dumps(summary),
            summary.get("cardEmbeddingVersion"),
            _utc_now(),
        ),
    )


def insert_rollout_tasks(conn: sqlite3.Connection, tasks: Iterable[dict[str, Any]]) -> None:
    now = _utc_now()
    rows = []
    for task in tasks:
        rows.append(
            (
                str(task["taskId"]),
                str(task["runId"]),
                str(task["playerDeckId"]),
                str(task["opponentDeckId"]),
                str(task["modelSide"]),
                str(task["trueTurnOrder"]),
                str(task["difficulty"]),
                int(task["seed"]),
                str(task.get("status") or "pending"),
                _json_dumps(task.get("taskSpec") or {}),
                now,
                now,
            )
        )
    conn.executemany(
        """
        INSERT INTO rollout_task(
            task_id,
            run_id,
            player_deck_id,
            opponent_deck_id,
            model_side,
            true_turn_order,
            difficulty,
            seed,
            status,
            task_spec_json,
            created_at,
            updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(task_id) DO NOTHING
        """,
        rows,
    )


def list_rollout_runs(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT run_id, created_at, purpose, policy_id, teacher_id, scorer_id, suite_id,
               runtime_weights_json, metadata_json
        FROM rollout_run
        ORDER BY created_at, run_id
        """
    ).fetchall()
    return [
        {
            "runId": row["run_id"],
            "createdAt": row["created_at"],
            "purpose": row["purpose"],
            "policyId": row["policy_id"],
            "teacherId": row["teacher_id"],
            "scorerId": row["scorer_id"],
            "suiteId": row["suite_id"],
            "runtimeWeights": _json_loads(row["runtime_weights_json"]),
            "metadata": _json_loads(row["metadata_json"]),
        }
        for row in rows
    ]


def list_rollout_decks(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT deck_id, deck_name, source, deck_hash, summary_json, card_embedding_version
        FROM deck
        ORDER BY deck_id
        """
    ).fetchall()
    return [
        {
            "deckId": row["deck_id"],
            "deckName": row["deck_name"],
            "source": row["source"],
            "deckHash": row["deck_hash"],
            "cardEmbeddingVersion": row["card_embedding_version"],
            "summary": _json_loads(row["summary_json"]),
        }
        for row in rows
    ]


def list_rollout_tasks(conn: sqlite3.Connection, *, run_id: str | None = None) -> list[dict[str, Any]]:
    sql = """
        SELECT task_id, run_id, player_deck_id, opponent_deck_id, model_side,
               true_turn_order, difficulty, seed, status, task_spec_json
        FROM rollout_task
    """
    params: tuple[Any, ...] = ()
    if run_id is not None:
        sql += " WHERE run_id = ?"
        params = (run_id,)
    sql += " ORDER BY task_id"
    rows = conn.execute(sql, params).fetchall()
    return [
        {
            "taskId": row["task_id"],
            "runId": row["run_id"],
            "playerDeckId": row["player_deck_id"],
            "opponentDeckId": row["opponent_deck_id"],
            "modelSide": row["model_side"],
            "trueTurnOrder": row["true_turn_order"],
            "difficulty": row["difficulty"],
            "seed": int(row["seed"]),
            "status": row["status"],
            "taskSpec": _json_loads(row["task_spec_json"]),
        }
        for row in rows
    ]


def claim_next_rollout_task(
    conn: sqlite3.Connection,
    *,
    run_id: str,
    worker_id: str,
    lease_seconds: int = 300,
    now: str | None = None,
    include_pending: bool = True,
) -> dict[str, Any] | None:
    """Atomically claim one pending or expired-running rollout task."""
    now_ts = now or _utc_now()
    expires_at = _utc_plus(now_ts, max(0, int(lease_seconds)))
    pending_clause = "status = 'pending'" if include_pending else "0"
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            f"""
            SELECT task_id, run_id, player_deck_id, opponent_deck_id, model_side,
                   true_turn_order, difficulty, seed, status, task_spec_json,
                   claimed_by, claim_expires_at
            FROM rollout_task
            WHERE run_id = ?
              AND (
                {pending_clause}
                OR (
                  status = 'running'
                  AND (claim_expires_at IS NULL OR claim_expires_at <= ?)
                )
              )
            ORDER BY CASE status WHEN 'pending' THEN 0 ELSE 1 END, task_id
            LIMIT 1
            """,
            (run_id, now_ts),
        ).fetchone()
        if row is None:
            conn.commit()
            return None
        reclaimed = str(row["status"]) == "running"
        conn.execute(
            """
            UPDATE rollout_task
            SET status = 'running',
                claimed_by = ?,
                claim_expires_at = ?,
                updated_at = ?
            WHERE task_id = ?
            """,
            (worker_id, expires_at, now_ts, row["task_id"]),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    task = _task_from_row(row)
    task["status"] = "running"
    task["claimedBy"] = str(worker_id)
    task["claimExpiresAt"] = expires_at
    task["reclaimed"] = reclaimed
    return task


def complete_rollout_task(
    conn: sqlite3.Connection,
    *,
    task_id: str,
    worker_id: str,
    result: dict[str, Any] | None = None,
    now: str | None = None,
) -> None:
    """Write task result metadata and mark a claimed task done."""
    now_ts = now or _utc_now()
    payload = result or {}
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = _select_claimed_task_for_worker(conn, task_id=task_id, worker_id=worker_id)
        for game in _game_result_rows(payload):
            conn.execute(
                """
                INSERT INTO game_result(task_id, run_id, game_index, winner, turns, error_json, result_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task_id,
                    row["run_id"],
                    int(game.get("gameIndex", 0)),
                    game.get("winner"),
                    game.get("turns"),
                    _json_dumps(game.get("error")) if game.get("error") is not None else None,
                    _json_dumps(game.get("result") or game),
                    now_ts,
                ),
            )
        for summary in payload.get("decisionSummaries") or []:
            conn.execute(
                """
                INSERT INTO decision_summary(task_id, run_id, decision_kind, summary_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    task_id,
                    row["run_id"],
                    str(summary.get("decisionKind") or "unknown"),
                    _json_dumps(summary.get("summary") or summary),
                    now_ts,
                ),
            )
        for shard in payload.get("actionSetShards") or []:
            conn.execute(
                """
                INSERT INTO action_set_shard(
                    shard_id, run_id, path, compression, row_count,
                    card_embedding_version, metadata_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(shard_id) DO NOTHING
                """,
                (
                    str(shard["shardId"]),
                    row["run_id"],
                    str(shard.get("path") or ""),
                    shard.get("compression"),
                    int(shard.get("rowCount") or 0),
                    shard.get("cardEmbeddingVersion"),
                    _json_dumps(shard.get("metadata") or {}),
                    now_ts,
                ),
            )
        conn.execute(
            """
            UPDATE rollout_task
            SET status = 'done',
                claimed_by = ?,
                claim_expires_at = NULL,
                updated_at = ?
            WHERE task_id = ?
            """,
            (worker_id, now_ts, task_id),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def fail_rollout_task(
    conn: sqlite3.Connection,
    *,
    task_id: str,
    worker_id: str,
    error: dict[str, Any] | None = None,
    now: str | None = None,
) -> None:
    """Record an inspectable worker error and mark the task failed."""
    now_ts = now or _utc_now()
    error_payload = error or {"type": "UnknownError", "message": "unknown rollout worker error"}
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = _select_claimed_task_for_worker(conn, task_id=task_id, worker_id=worker_id)
        conn.execute(
            """
            INSERT INTO game_result(task_id, run_id, game_index, winner, turns, error_json, result_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                task_id,
                row["run_id"],
                -1,
                "error",
                None,
                _json_dumps(error_payload),
                _json_dumps({"failed": True, "workerId": worker_id}),
                now_ts,
            ),
        )
        conn.execute(
            """
            UPDATE rollout_task
            SET status = 'failed',
                claimed_by = ?,
                claim_expires_at = NULL,
                updated_at = ?
            WHERE task_id = ?
            """,
            (worker_id, now_ts, task_id),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def retry_failed_rollout_tasks(
    conn: sqlite3.Connection,
    *,
    run_id: str,
    limit: int | None = None,
    now: str | None = None,
) -> int:
    """Move failed tasks back to pending without deleting their error evidence."""
    now_ts = now or _utc_now()
    params: tuple[Any, ...] = (run_id,)
    sql = """
        SELECT task_id
        FROM rollout_task
        WHERE run_id = ? AND status = 'failed'
        ORDER BY task_id
    """
    if limit is not None:
        sql += " LIMIT ?"
        params = (run_id, max(0, int(limit)))
    rows = conn.execute(sql, params).fetchall()
    task_ids = [str(row["task_id"]) for row in rows]
    if not task_ids:
        return 0
    conn.executemany(
        """
        UPDATE rollout_task
        SET status = 'pending',
            claimed_by = NULL,
            claim_expires_at = NULL,
            updated_at = ?
        WHERE task_id = ?
        """,
        [(now_ts, task_id) for task_id in task_ids],
    )
    return len(task_ids)


def rollout_task_status_counts(conn: sqlite3.Connection, *, run_id: str | None = None) -> dict[str, int]:
    sql = "SELECT status, COUNT(*) AS count FROM rollout_task"
    params: tuple[Any, ...] = ()
    if run_id is not None:
        sql += " WHERE run_id = ?"
        params = (run_id,)
    sql += " GROUP BY status ORDER BY status"
    return {str(row["status"]): int(row["count"]) for row in conn.execute(sql, params).fetchall()}


def rollout_table_counts(conn: sqlite3.Connection, *, run_id: str) -> dict[str, int]:
    return {
        "tasks": int(conn.execute("SELECT COUNT(*) FROM rollout_task WHERE run_id = ?", (run_id,)).fetchone()[0]),
        "gameResults": int(conn.execute("SELECT COUNT(*) FROM game_result WHERE run_id = ?", (run_id,)).fetchone()[0]),
        "actionSetShards": int(conn.execute("SELECT COUNT(*) FROM action_set_shard WHERE run_id = ?", (run_id,)).fetchone()[0]),
    }


def insert_hard_states(conn: sqlite3.Connection, hard_states: Iterable[dict[str, Any]]) -> int:
    now = _utc_now()
    rows = []
    for state in hard_states:
        rows.append(
            (
                str(state["hardStateId"]),
                str(state["runId"]),
                state.get("taskId"),
                str(state["stateKind"]),
                float(state.get("priority", 0.0)),
                state.get("shardPath"),
                _json_dumps(state.get("metadata") or {}),
                str(state.get("status") or "pending"),
                now,
                now,
            )
        )
    if not rows:
        return 0
    before = conn.total_changes
    conn.executemany(
        """
        INSERT INTO hard_state(
            hard_state_id,
            run_id,
            task_id,
            state_kind,
            priority,
            shard_path,
            metadata_json,
            status,
            created_at,
            updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(hard_state_id) DO NOTHING
        """,
        rows,
    )
    return int(conn.total_changes - before)


def list_hard_states(
    conn: sqlite3.Connection,
    *,
    run_id: str,
    status: str | None = None,
) -> list[dict[str, Any]]:
    sql = """
        SELECT hard_state_id, run_id, task_id, state_kind, priority,
               shard_path, metadata_json, status
        FROM hard_state
        WHERE run_id = ?
    """
    params: tuple[Any, ...] = (run_id,)
    if status is not None:
        sql += " AND status = ?"
        params = (run_id, status)
    sql += " ORDER BY state_kind, hard_state_id"
    rows = conn.execute(sql, params).fetchall()
    return [
        {
            "hardStateId": row["hard_state_id"],
            "runId": row["run_id"],
            "taskId": row["task_id"],
            "stateKind": row["state_kind"],
            "priority": float(row["priority"]),
            "shardPath": row["shard_path"],
            "metadata": _json_loads(row["metadata_json"]),
            "status": row["status"],
        }
        for row in rows
    ]


def mark_hard_states_relabelled(
    conn: sqlite3.Connection,
    *,
    run_id: str,
    hard_state_ids: Iterable[str],
    shard_path: str,
) -> int:
    now = _utc_now()
    ids = [str(hard_state_id) for hard_state_id in hard_state_ids]
    if not ids:
        return 0
    before = conn.total_changes
    conn.executemany(
        """
        UPDATE hard_state
        SET status = 'done',
            shard_path = ?,
            updated_at = ?
        WHERE run_id = ? AND hard_state_id = ?
        """,
        [(shard_path, now, run_id, hard_state_id) for hard_state_id in ids],
    )
    return int(conn.total_changes - before)


def _select_claimed_task_for_worker(
    conn: sqlite3.Connection,
    *,
    task_id: str,
    worker_id: str,
) -> sqlite3.Row:
    row = conn.execute(
        """
        SELECT task_id, run_id, status, claimed_by
        FROM rollout_task
        WHERE task_id = ?
        """,
        (task_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"unknown rollout task: {task_id}")
    if row["status"] != "running":
        raise ValueError(f"rollout task {task_id} is not running")
    if row["claimed_by"] != worker_id:
        raise ValueError(f"rollout task {task_id} is claimed by {row['claimed_by']!r}, not {worker_id!r}")
    return row


def _task_from_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "taskId": row["task_id"],
        "runId": row["run_id"],
        "playerDeckId": row["player_deck_id"],
        "opponentDeckId": row["opponent_deck_id"],
        "modelSide": row["model_side"],
        "trueTurnOrder": row["true_turn_order"],
        "difficulty": row["difficulty"],
        "seed": int(row["seed"]),
        "status": row["status"],
        "taskSpec": _json_loads(row["task_spec_json"]),
    }


def _game_result_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    if "gameResults" in payload:
        return list(payload.get("gameResults") or [])
    if "gameResult" in payload:
        return [dict(payload["gameResult"])]
    return []


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _utc_plus(timestamp: str, seconds: int) -> str:
    value = _parse_utc(timestamp) + timedelta(seconds=seconds)
    return value.isoformat(timespec="seconds").replace("+00:00", "Z")


def _parse_utc(timestamp: str) -> datetime:
    return datetime.fromisoformat(timestamp.replace("Z", "+00:00")).astimezone(timezone.utc)


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _json_loads(value: str | bytes | None) -> Any:
    if value is None or value == "":
        return {}
    return json.loads(value)
