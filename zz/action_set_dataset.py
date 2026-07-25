from __future__ import annotations

import copy
import gzip
import json
from collections import defaultdict
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from zz.model import Action, Player
from zz.rl_action_vocab import (
    ACTION_KIND_VOCAB_VERSION,
    DECISION_KINDS,
    decision_kind_for_action,
    normalise_decision_kind,
)
from zz.rl_tensor_schema import (
    ACTION_SET_TENSOR_SCHEMA_FINGERPRINT,
    ACTION_TENSOR_SCHEMA_VERSION,
    CARD_ID_VOCAB_HASH,
    CARD_ID_VOCAB_VERSION,
)
from zz.training_fast_path import build_training_action_set_frame, fast_path_row_metadata_from_frame

try:
    import ujson as _ujson
except ImportError:  # pragma: no cover - optional local speedup.
    _ujson = None


ACTION_SET_DATASET_VERSION = "action_set_dataset_v1"
ACTION_SET_COMPACT_SHARD_VERSION = "action_set_compact_shard_v1"
ACTION_SET_SHARED_ROW_KEYS = (
    "cardFeatureNames",
    "historyFeatureNames",
    "globalFeatureNames",
    "actionFeatureNames",
)


def compact_action_set_rows(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Hoist repeated per-row schema fields into a shard-level payload."""
    row_list = [dict(row) for row in rows]
    shared: dict[str, Any] = {}
    for key in ACTION_SET_SHARED_ROW_KEYS:
        if not row_list or key not in row_list[0]:
            continue
        first_value = row_list[0].get(key)
        if not all(row.get(key) == first_value for row in row_list):
            continue
        shared[key] = first_value
        for row in row_list:
            row.pop(key, None)
    return {
        "format": ACTION_SET_COMPACT_SHARD_VERSION,
        "rowCount": len(row_list),
        "shared": shared,
        "rows": row_list,
    }


def expand_action_set_rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [dict(row) if isinstance(row, Mapping) else row for row in payload]
    if not isinstance(payload, Mapping):
        raise ValueError("action-set shard payload must be a JSON array or compact object")
    if payload.get("format") != ACTION_SET_COMPACT_SHARD_VERSION:
        raise ValueError(f"unsupported action-set shard format: {payload.get('format')!r}")
    shared = payload.get("shared") if isinstance(payload.get("shared"), Mapping) else {}
    rows = payload.get("rows")
    if not isinstance(rows, list):
        raise ValueError("compact action-set shard rows must be a JSON array")
    expanded: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, Mapping):
            raise ValueError("compact action-set shard rows must be JSON objects")
        copied = dict(shared)
        copied.update(dict(row))
        expanded.append(copied)
    expected_count = payload.get("rowCount")
    if expected_count is not None and int(expected_count) != len(expanded):
        raise ValueError("compact action-set shard rowCount does not match rows length")
    return expanded


def write_action_set_rows_gzip(
    path: str | Path,
    rows: Iterable[Mapping[str, Any]],
    *,
    compact: bool = True,
    compresslevel: int = 1,
) -> None:
    path_obj = Path(path)
    path_obj.parent.mkdir(parents=True, exist_ok=True)
    row_list = [dict(row) for row in rows]
    payload: Any = compact_action_set_rows(row_list) if compact else row_list
    with gzip.open(path_obj, "wt", encoding="utf-8", compresslevel=int(compresslevel)) as handle:
        json.dump(payload, handle, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def read_action_set_rows(path: str | Path) -> list[dict[str, Any]]:
    path_obj = Path(path)
    payload = _load_action_set_json_payload(path_obj)
    return expand_action_set_rows(payload)


def _load_action_set_json_payload(path_obj: Path) -> Any:
    opener = gzip.open if path_obj.suffix.lower() == ".gz" else open
    if _ujson is not None:
        with opener(path_obj, "rb") as handle:
            return _ujson.loads(handle.read())
    with opener(path_obj, "rt", encoding="utf-8") as handle:
        return json.load(handle)


class ActionSetTeacherRecorder:
    def __init__(
        self,
        *,
        max_actions: int,
        rows: list[dict[str, Any]] | None = None,
        metadata: Mapping[str, Any] | None = None,
        capture_decision_snapshots: bool = False,
    ) -> None:
        if max_actions <= 0:
            raise ValueError("max_actions must be positive")
        self.max_actions = int(max_actions)
        self.rows: list[dict[str, Any]] = rows if rows is not None else []
        self.metadata = _json_mapping(metadata or {})
        self.capture_decision_snapshots = bool(capture_decision_snapshots)
        self.decision_snapshots: list[dict[str, Any]] = []
        self.skipped_overflow_count = 0
        self.skipped_invalid_count = 0
        self.skipped_snapshot_count = 0
        self._replay_context: dict[str, Any] = {}
        self._replay_decision_index = 0
        self._recent_action_history: list[dict[str, Any]] = []

    def begin_replay_context(self, context: Mapping[str, Any] | None = None) -> None:
        self._replay_context = _json_mapping(context or {})
        self._replay_decision_index = 0

    def record_decision(
        self,
        engine: Any,
        player: Player,
        actions: list[Action] | tuple[Action, ...],
        *,
        teacher_scores: list[float] | tuple[float, ...],
        selected_action_slot: int,
        decision_kind: str | None = None,
        raw_scores: list[float] | tuple[float, ...] | None = None,
        lookahead_deltas: list[float] | tuple[float, ...] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> int:
        replay_decision_index = self._next_replay_decision_index()
        action_list = list(actions)
        if len(action_list) > self.max_actions:
            self.skipped_overflow_count += 1
            return -1
        row_metadata = dict(self.metadata)
        row_metadata.update(self._replay_context)
        row_metadata.update(_json_mapping(metadata or {}))
        if replay_decision_index is not None:
            _add_replay_cursor_metadata(row_metadata, replay_decision_index)
        history_context = _history_context_from_metadata(
            row_metadata,
            recent_action_history=self._recent_action_history,
        )
        try:
            row = build_action_set_teacher_row(
                engine,
                player,
                action_list,
                teacher_scores=teacher_scores,
                selected_action_slot=selected_action_slot,
                max_actions=self.max_actions,
                decision_kind=decision_kind,
                raw_scores=raw_scores,
                lookahead_deltas=lookahead_deltas,
                metadata=row_metadata,
                history_context=history_context,
            )
        except ValueError:
            self.skipped_invalid_count += 1
            return -1
        self.rows.append(row)
        if self.capture_decision_snapshots:
            snapshot = _snapshot_engine_for_action_set(engine)
            if snapshot is None:
                self.skipped_snapshot_count += 1
            else:
                self.decision_snapshots.append(
                    {
                        "row": row,
                        "engine": snapshot,
                        "activePlayer": _player_label(player),
                    }
                )
        self._append_recent_action(
            action_list=action_list,
            selected_action_slot=selected_action_slot,
            decision_kind=str(row.get("decisionKind") or decision_kind or "unknown"),
        )
        return len(self.rows) - 1

    def _next_replay_decision_index(self) -> int | None:
        if not self._replay_context:
            return None
        decision_index = int(self._replay_decision_index)
        self._replay_decision_index += 1
        return decision_index

    def _append_recent_action(
        self,
        *,
        action_list: list[Action],
        selected_action_slot: int,
        decision_kind: str,
    ) -> None:
        if selected_action_slot < 0 or selected_action_slot >= len(action_list):
            return
        selected = action_list[int(selected_action_slot)]
        self._recent_action_history.append(
            {
                "kind": str(getattr(selected, "kind", "unknown") or "unknown"),
                "decisionKind": normalise_decision_kind(decision_kind),
            }
        )
        if len(self._recent_action_history) > 8:
            del self._recent_action_history[:-8]


def build_action_set_teacher_row(
    engine: Any,
    player: Player,
    actions: list[Action] | tuple[Action, ...],
    *,
    teacher_scores: list[float] | tuple[float, ...],
    selected_action_slot: int,
    max_actions: int,
    decision_kind: str | None = None,
    raw_scores: list[float] | tuple[float, ...] | None = None,
    lookahead_deltas: list[float] | tuple[float, ...] | None = None,
    metadata: Mapping[str, Any] | None = None,
    history_context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    action_list = list(actions)
    _validate_action_set_inputs(
        action_count=len(action_list),
        max_actions=max_actions,
        selected_action_slot=selected_action_slot,
        teacher_scores=teacher_scores,
        raw_scores=raw_scores,
        lookahead_deltas=lookahead_deltas,
    )
    fast_path_frame = build_training_action_set_frame(
        engine,
        player,
        action_list,
        max_actions=max_actions,
        decision_kind=decision_kind,
        history_context=history_context,
    )
    encoded = fast_path_frame.tensor
    teacher_score_list = [float(score) for score in teacher_scores]

    action_records = [_action_record(action, engine=engine, player=player) for action in action_list]
    padded_action_records = action_records + [None] * (max_actions - len(action_list))

    row = {
        "datasetVersion": ACTION_SET_DATASET_VERSION,
        "actionVocabVersion": ACTION_KIND_VOCAB_VERSION,
        "actionTensorSchemaVersion": ACTION_TENSOR_SCHEMA_VERSION,
        "actionTensorSchemaFingerprint": ACTION_SET_TENSOR_SCHEMA_FINGERPRINT,
        "cardIdVocabVersion": CARD_ID_VOCAB_VERSION,
        "cardIdVocabHash": CARD_ID_VOCAB_HASH,
        "decisionKind": encoded.decisionKind,
        "legalCount": len(action_list),
        "selectedActionSlot": int(selected_action_slot),
        "teacherTopSlot": _top_slot(teacher_score_list),
        "cardFeatureNames": list(encoded.cardFeatureNames),
        "historyFeatureNames": list(encoded.historyFeatureNames),
        "globalFeatureNames": list(encoded.globalFeatureNames),
        "actionFeatureNames": list(encoded.actionFeatureNames),
        "cards_": [list(row) for row in encoded.cards_],
        "history_": list(encoded.history_),
        "global_": list(encoded.global_),
        "actions_": [list(row) for row in encoded.actions_],
        "mask_": list(encoded.mask_),
        "actions": list(padded_action_records),
        "actionRecords": list(padded_action_records),
        "teacherScores": _pad_scores(teacher_score_list, max_actions),
        "rawScores": _pad_scores(raw_scores, max_actions) if raw_scores is not None else [None] * max_actions,
        "lookaheadDeltas": (
            _pad_scores(lookahead_deltas, max_actions)
            if lookahead_deltas is not None
            else [None] * max_actions
        ),
        "metadata": _json_mapping(metadata or {}),
    }
    row.update(fast_path_row_metadata_from_frame(fast_path_frame, max_actions=max_actions))
    return row


def _history_context_from_metadata(
    metadata: Mapping[str, Any],
    *,
    recent_action_history: list[dict[str, Any]],
) -> dict[str, Any]:
    context = _json_mapping(metadata)
    if "recentActions" not in context:
        context["recentActions"] = [dict(item) for item in recent_action_history[-8:]]
    return context


def summarize_action_set_shadow_rows(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    total = _ShadowSummary()
    by_decision: dict[str, _ShadowSummary] = defaultdict(_ShadowSummary)

    for row in rows:
        selected_slot = _optional_int(row.get("selectedActionSlot"))
        mask = _mask_slots(row.get("mask_"))
        shadow_scores = _score_slots(row.get("shadowScores"))
        if selected_slot is None or not mask or not shadow_scores:
            total.skipped += 1
            continue
        legal_slots = [
            index
            for index, enabled in enumerate(mask)
            if enabled and index < len(shadow_scores) and shadow_scores[index] is not None
        ]
        if selected_slot not in legal_slots:
            total.skipped += 1
            continue

        ranked_slots = sorted(legal_slots, key=lambda index: (shadow_scores[index], -index), reverse=True)
        decision_kind = str(row.get("decisionKind") or "unknown")
        total.record(selected_slot, ranked_slots)
        by_decision[decision_kind].record(selected_slot, ranked_slots)

    return {
        **total.to_dict(),
        "byDecisionKind": {
            decision_kind: summary.to_dict()
            for decision_kind, summary in sorted(by_decision.items())
        },
    }


def normalize_action_set_teacher_row_decision_kind(row: Mapping[str, Any]) -> dict[str, Any]:
    current_kind = normalise_decision_kind(str(row.get("decisionKind") or "unknown"))
    refined_kind = _refined_decision_kind_from_actions(row, current_kind)
    copied = dict(row)
    if refined_kind == current_kind:
        return copied
    copied["decisionKind"] = refined_kind
    action_feature_names = [str(name) for name in row.get("actionFeatureNames") or []]
    old_index = _feature_index(action_feature_names, f"decision:{current_kind}")
    new_index = _feature_index(action_feature_names, f"decision:{refined_kind}")
    actions = row.get("actions_") or []
    normalized_actions: list[list[float]] = []
    for slot, values in enumerate(actions):
        action_values = _float_list(values)
        if slot < int(row.get("legalCount") or 0):
            if old_index is not None and old_index < len(action_values):
                action_values[old_index] = 0.0
            if new_index is not None and new_index < len(action_values):
                action_values[new_index] = 1.0
        normalized_actions.append(action_values)
    copied["actions_"] = normalized_actions
    return copied


def summarize_action_set_teacher_coverage(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    row_count = 0
    by_decision: dict[str, int] = {}
    by_action_kind: dict[str, int] = {}
    by_difficulty: dict[str, int] = {}
    by_side: dict[str, int] = {}
    by_player_deck: dict[str, int] = {}
    by_opponent_deck: dict[str, int] = {}
    selected_action_by_decision: dict[str, dict[str, int]] = defaultdict(dict)
    teacher_top_action_by_decision: dict[str, dict[str, int]] = defaultdict(dict)
    legal_counts: list[int] = []
    focused = {
        "mulligan": _FocusedCoverage(
            decision_kind="mulligan",
            action_kinds={"mulligan_keep", "mulligan_replace"},
        ),
        "flash": _FocusedCoverage(
            decision_kind="flash",
            action_kinds={"flash_pass", "activate_flash_ability"},
            context_action_kinds={"play_card"},
        ),
        "replacement": _FocusedCoverage(
            decision_kind="replacement",
            action_kinds={"choose_replacement"},
            payload_fields={"replace_base_iid", "replace_field_iid"},
        ),
        "color_swap": _FocusedCoverage(
            decision_kind="color_swap",
            action_kinds={"swap_mana_color"},
        ),
    }

    for row in rows:
        row_count += 1
        decision_kind = str(row.get("decisionKind") or "unknown")
        _increment(by_decision, decision_kind)
        legal_counts.append(int(row.get("legalCount", 0) or 0))
        metadata = dict(row.get("metadata") or {})
        _increment(by_difficulty, str(metadata.get("difficulty") or "unknown"))
        _increment(by_side, str(metadata.get("modelSide") or "unknown"))
        _increment(by_player_deck, str(metadata.get("playerDeckId") or "unknown"))
        _increment(by_opponent_deck, str(metadata.get("opponentDeckId") or "unknown"))

        actions = _legal_action_records(row)
        selected_kind = _action_kind_for_slot(row, "selectedActionSlot")
        if selected_kind is not None:
            _increment(selected_action_by_decision[decision_kind], selected_kind)
        teacher_top_kind = _action_kind_for_slot(row, "teacherTopSlot")
        if teacher_top_kind is not None:
            _increment(teacher_top_action_by_decision[decision_kind], teacher_top_kind)
        for focus in focused.values():
            focus.record_row(decision_kind=decision_kind, actions=actions)
        for action in actions:
            _increment(by_action_kind, _action_kind_from_record(action))

    return {
        "kind": "action_set_teacher_coverage_v2",
        "rowCount": row_count,
        "byDecisionKind": dict(sorted(by_decision.items())),
        "requiredDecisionKinds": list(DECISION_KINDS),
        "missingDecisionKinds": [
            decision_kind
            for decision_kind in DECISION_KINDS
            if decision_kind not in by_decision
        ],
        "byActionKind": dict(sorted(by_action_kind.items())),
        "selectedActionKindByDecisionKind": {
            decision_kind: dict(sorted(counts.items()))
            for decision_kind, counts in sorted(selected_action_by_decision.items())
        },
        "teacherTopActionKindByDecisionKind": {
            decision_kind: dict(sorted(counts.items()))
            for decision_kind, counts in sorted(teacher_top_action_by_decision.items())
        },
        "focusedDecisionCoverage": {
            name: coverage.to_dict()
            for name, coverage in sorted(focused.items())
        },
        "byDifficulty": dict(sorted(by_difficulty.items())),
        "byModelSide": dict(sorted(by_side.items())),
        "byPlayerDeckId": dict(sorted(by_player_deck.items())),
        "byOpponentDeckId": dict(sorted(by_opponent_deck.items())),
        "legalCount": _legal_count_summary(legal_counts),
    }


def _validate_action_set_inputs(
    *,
    action_count: int,
    max_actions: int,
    selected_action_slot: int,
    teacher_scores: list[float] | tuple[float, ...],
    raw_scores: list[float] | tuple[float, ...] | None,
    lookahead_deltas: list[float] | tuple[float, ...] | None,
) -> None:
    if max_actions <= 0:
        raise ValueError("max_actions must be positive")
    if action_count > max_actions:
        raise ValueError("actions cannot exceed max_actions for teacher rows")
    if len(teacher_scores) != action_count:
        raise ValueError("teacher_scores length must match actions")
    if raw_scores is not None and len(raw_scores) != action_count:
        raise ValueError("raw_scores length must match actions")
    if lookahead_deltas is not None and len(lookahead_deltas) != action_count:
        raise ValueError("lookahead_deltas length must match actions")
    if selected_action_slot < 0 or selected_action_slot >= action_count:
        raise ValueError("selected_action_slot must reference a legal action")


def _legal_action_records(row: Mapping[str, Any]) -> list[Any]:
    legal_count = int(row.get("legalCount") or 0)
    actions = row.get("actions") or []
    if not isinstance(actions, list | tuple):
        return []
    return [action for action in actions[:legal_count] if action is not None]


def _action_kind_from_record(action: Any) -> str:
    if isinstance(action, Mapping):
        return str(action.get("kind") or "unknown")
    return str(getattr(action, "kind", "unknown") or "unknown")


def _action_kind_for_slot(row: Mapping[str, Any], slot_key: str) -> str | None:
    slot = _optional_int(row.get(slot_key))
    if slot is None or slot < 0:
        return None
    actions = row.get("actions") or []
    if not isinstance(actions, list | tuple) or slot >= len(actions):
        return None
    action = actions[slot]
    if action is None:
        return None
    return _action_kind_from_record(action)


def _payload_from_record(action: Any) -> Mapping[str, Any]:
    if isinstance(action, Mapping):
        payload = action.get("payload") or {}
        return payload if isinstance(payload, Mapping) else {}
    payload = getattr(action, "payload", None) or {}
    return payload if isinstance(payload, Mapping) else {}


def _legal_count_summary(values: list[int]) -> dict[str, Any]:
    if not values:
        return {"min": 0, "median": 0, "max": 0}
    ordered = sorted(values)
    return {
        "min": int(ordered[0]),
        "median": int(ordered[len(ordered) // 2]),
        "max": int(ordered[-1]),
    }


def _increment(counter: dict[str, int], key: str) -> None:
    counter[key] = counter.get(key, 0) + 1


def _pad_scores(values: Iterable[float] | None, max_actions: int) -> list[float | None]:
    if values is None:
        return [None] * max_actions
    out = [float(value) for value in values]
    return out + [None] * (max_actions - len(out))


def _top_slot(scores: list[float]) -> int | None:
    if not scores:
        return None
    return max(range(len(scores)), key=lambda index: (scores[index], -index))


def _snapshot_engine_for_action_set(engine: Any) -> Any | None:
    try:
        clone_for_simulation = getattr(engine, "clone_for_simulation", None)
        snapshot = clone_for_simulation() if callable(clone_for_simulation) else copy.deepcopy(engine)
        if hasattr(snapshot, "state") and hasattr(snapshot.state, "engine"):
            snapshot.state.engine = snapshot
        if hasattr(snapshot, "triggers") and hasattr(snapshot.triggers, "_engine"):
            snapshot.triggers._engine = snapshot
        rebind = getattr(snapshot, "rebind_passive_modifiers", None)
        if callable(rebind):
            rebind()
        return snapshot
    except Exception:
        return None


def _player_label(player: Any) -> str:
    side = getattr(player, "side", None)
    side_name = getattr(side, "name", None)
    if side_name:
        return str(side_name)
    side_value = getattr(side, "value", None)
    if side_value:
        return str(side_value)
    return str(getattr(player, "name", "unknown"))


def _action_record(action: Action, *, engine: Any | None = None, player: Player | None = None) -> dict[str, Any]:
    record = {
        "kind": str(getattr(action, "kind", "")),
        "payload": _json_mapping(getattr(action, "payload", {}) or {}),
    }
    if engine is not None and player is not None:
        try:
            from zz.rl_training import action_signature

            record["signature"] = _json_mapping(action_signature(engine, player, action))
        except Exception:
            pass
    return record


def _json_mapping(mapping: Mapping[str, Any]) -> dict[str, Any]:
    return {str(key): _json_value(value) for key, value in mapping.items()}


def _add_replay_cursor_metadata(row_metadata: dict[str, Any], decision_index: int) -> None:
    row_metadata.setdefault("actionSetDecisionIndex", int(decision_index))
    raw_cursor = row_metadata.get("replayCursor")
    cursor = dict(raw_cursor) if isinstance(raw_cursor, Mapping) else {}
    for key in ("episodeIndex", "runSeed", "modelPolicySeed", "opponentPolicySeed"):
        if key in row_metadata and key not in cursor:
            cursor[key] = row_metadata[key]
    cursor.setdefault("decisionIndex", int(decision_index))
    cursor.setdefault("actionSetDecisionIndex", int(decision_index))
    row_metadata["replayCursor"] = _json_mapping(cursor)


def _json_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return _json_mapping(value)
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    enum_value = getattr(value, "value", None)
    if isinstance(enum_value, (str, int, float, bool)):
        return enum_value
    return str(value)


def _mask_slots(value: Any) -> list[bool]:
    if not isinstance(value, list | tuple):
        return []
    return [bool(item) for item in value]


def _score_slots(value: Any) -> list[float | None]:
    if not isinstance(value, list | tuple):
        return []
    out: list[float | None] = []
    for item in value:
        if item is None:
            out.append(None)
            continue
        try:
            out.append(float(item))
        except (TypeError, ValueError):
            out.append(None)
    return out


def _optional_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _refined_decision_kind_from_actions(row: Mapping[str, Any], current_kind: str) -> str:
    explicit = normalise_decision_kind(current_kind)
    legal_count = int(row.get("legalCount") or 0)
    actions = row.get("actions") or []
    inferred: set[str] = set()
    if isinstance(actions, list | tuple):
        for action in actions[:legal_count]:
            if not isinstance(action, Mapping):
                continue
            kind = str(action.get("kind") or "unknown")
            inferred.add(decision_kind_for_action(kind))
    if explicit == "main" and len(inferred) == 1:
        inferred_kind = next(iter(inferred))
        if inferred_kind not in {"unknown", "main"}:
            return inferred_kind
    return explicit


def _feature_index(names: list[str], target: str) -> int | None:
    try:
        return names.index(target)
    except ValueError:
        return None


def _float_list(value: Any) -> list[float]:
    if not isinstance(value, list | tuple):
        return []
    out: list[float] = []
    for item in value:
        try:
            out.append(float(item))
        except (TypeError, ValueError):
            out.append(0.0)
    return out


class _FocusedCoverage:
    def __init__(
        self,
        *,
        decision_kind: str,
        action_kinds: set[str],
        context_action_kinds: set[str] | None = None,
        payload_fields: set[str] | None = None,
    ) -> None:
        self.decision_kind = decision_kind
        self.action_kinds = set(action_kinds)
        self.context_action_kinds = set(context_action_kinds or set())
        self.payload_fields = set(payload_fields or set())
        self.row_count = 0
        self.action_row_count = 0
        self.action_count = 0

    def record_row(self, *, decision_kind: str, actions: list[Any]) -> None:
        if decision_kind == self.decision_kind:
            self.row_count += 1
        matched_actions = 0
        for action in actions:
            kind = _action_kind_from_record(action)
            payload = _payload_from_record(action)
            if kind in self.action_kinds:
                matched_actions += 1
                continue
            if decision_kind == self.decision_kind and kind in self.context_action_kinds:
                matched_actions += 1
                continue
            if any(payload.get(field) is not None for field in self.payload_fields):
                matched_actions += 1
        if matched_actions:
            self.action_row_count += 1
            self.action_count += matched_actions

    def to_dict(self) -> dict[str, Any]:
        return {
            "decisionKind": self.decision_kind,
            "rowCount": int(self.row_count),
            "actionRowCount": int(self.action_row_count),
            "actionCount": int(self.action_count),
        }


class _ShadowSummary:
    def __init__(self) -> None:
        self.rows = 0
        self.top1 = 0
        self.top3 = 0
        self.skipped = 0

    def record(self, selected_slot: int, ranked_slots: list[int]) -> None:
        self.rows += 1
        if ranked_slots and ranked_slots[0] == selected_slot:
            self.top1 += 1
        if selected_slot in ranked_slots[:3]:
            self.top3 += 1

    def to_dict(self) -> dict[str, Any]:
        denominator = max(1, self.rows)
        return {
            "rowCount": self.rows,
            "skippedRowCount": self.skipped,
            "top1Agreement": self.top1 / denominator,
            "top3Coverage": self.top3 / denominator,
        }
