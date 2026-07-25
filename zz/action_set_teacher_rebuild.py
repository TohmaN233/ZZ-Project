from __future__ import annotations

import gzip
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from zz.action_set_dataset import (
    expand_action_set_rows,
    normalize_action_set_teacher_row_decision_kind,
    summarize_action_set_teacher_coverage,
)
from zz.rl_action_vocab import (
    action_category_tags,
    action_state_numeric_features,
    card_profile_numeric_features,
    decision_kind_for_action,
    normalise_action_kind,
    normalise_decision_kind,
    payload_numeric_features,
)
from zz.model import Action
from zz.rl_tensor_schema import (
    ACTION_CARD_FEATURE_NAMES,
    ACTION_FEATURE_NAMES,
    CARD_FEATURE_NAMES,
    HISTORY_FEATURE_NAMES,
    _action_source_target_iids,
    _action_feature_map,
    history_feature_row,
)
from zz.rl_tensor_schema import GLOBAL_FEATURE_NAMES
from zz.training_fast_path import attach_fast_path_row_metadata


ACTION_SET_TEACHER_REBUILD_VERSION = "normalized_action_set_teacher_rebuild_v1"


def rebuild_normalized_action_set_teacher_rows(
    rows: list[Mapping[str, Any]],
    *,
    source_path: str | Path | None = None,
) -> dict[str, Any]:
    row_list = [dict(row) for row in rows]
    normalized_rows: list[dict[str, Any]] = []
    replay_histories: dict[tuple[str, ...], list[dict[str, Any]]] = {}
    changed = 0
    for index, row in enumerate(row_list):
        before_kind = str(row.get("decisionKind") or "unknown")
        normalized = normalize_action_set_teacher_row_decision_kind(row)
        after_kind = str(normalized.get("decisionKind") or "unknown")
        if after_kind != before_kind:
            changed += 1
        metadata = dict(normalized.get("metadata") or {})
        if source_path is not None:
            metadata["sourceTeacherRowsPath"] = str(source_path)
        metadata["sourceTeacherRowIndex"] = int(index)
        metadata["decisionKindBeforeNormalization"] = before_kind
        metadata["decisionKindNormalized"] = bool(after_kind != before_kind)
        normalized["metadata"] = metadata
        replay_key = _replay_history_key(metadata)
        recent_history = replay_histories.setdefault(replay_key, [])
        history_context = dict(metadata)
        history_context["recentActions"] = [dict(item) for item in recent_history[-8:]]
        normalized["historyFeatureNames"] = list(HISTORY_FEATURE_NAMES)
        normalized["history_"] = list(history_feature_row(history_context))
        _refresh_global_semantic_features(normalized)
        _refresh_action_semantic_features(normalized, force_full_refresh=True)
        _refresh_card_semantic_features(normalized)
        normalized_rows.append(attach_fast_path_row_metadata(normalized))
        selected_history = _selected_history_item(normalized)
        if selected_history is not None:
            recent_history.append(selected_history)
            if len(recent_history) > 8:
                del recent_history[:-8]

    return {
        "kind": ACTION_SET_TEACHER_REBUILD_VERSION,
        "createdAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "sourceTeacherRowsPath": str(source_path) if source_path is not None else None,
        "rowCount": len(row_list),
        "changedDecisionKindRows": int(changed),
        "coverageBefore": summarize_action_set_teacher_coverage(row_list),
        "coverageAfter": summarize_action_set_teacher_coverage(normalized_rows),
        "actionCardIdentityCoverageAfter": summarize_action_card_identity_coverage(normalized_rows),
        "rows": normalized_rows,
        "defaultRuntimeChanged": False,
        "defaultBaselineOverwritten": False,
        "defaultSidecarOverwritten": False,
        "candidatePruningEnabled": False,
        "promotionApproved": False,
    }


def summarize_action_card_identity_coverage(rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    by_kind: dict[str, Counter[str]] = {}
    totals: Counter[str] = Counter()
    for row in rows:
        action_feature_names = [str(name) for name in list(row.get("actionFeatureNames") or [])]
        known_index = _feature_index(action_feature_names, "action_card:known")
        actions = row.get("actions") or []
        action_rows = row.get("actions_") or []
        if not isinstance(actions, list | tuple) or not isinstance(action_rows, list | tuple):
            continue
        try:
            legal_count = int(row.get("legalCount") or 0)
        except (TypeError, ValueError):
            legal_count = 0
        for index, action in enumerate(actions[:legal_count]):
            if not isinstance(action, Mapping):
                continue
            kind = str(action.get("kind") or "unknown")
            counts = by_kind.setdefault(kind, Counter())
            counts["legalActions"] += 1
            totals["legalActions"] += 1
            has_serialized_ref = _action_has_serialized_card_ref(action)
            if has_serialized_ref:
                counts["serializedCardRefs"] += 1
                totals["serializedCardRefs"] += 1
            values = _float_list(action_rows[index]) if index < len(action_rows) else []
            known = known_index is not None and known_index < len(values) and abs(values[known_index]) > 1e-9
            if known:
                counts["actionCardKnown"] += 1
                totals["actionCardKnown"] += 1
            if has_serialized_ref and not known:
                counts["missingKnownForSerializedCardRefs"] += 1
                totals["missingKnownForSerializedCardRefs"] += 1
    return {
        "totals": _coverage_counter_to_dict(totals),
        "byActionKind": {kind: _coverage_counter_to_dict(by_kind[kind]) for kind in sorted(by_kind)},
    }


def refresh_action_set_row_semantic_features(
    row: dict[str, Any],
    *,
    force_action_semantics: bool = False,
) -> None:
    if isinstance(row.get("globalFeatureNames"), list):
        _refresh_global_semantic_features(row)
    _refresh_action_semantic_features(row, force_full_refresh=force_action_semantics)
    _refresh_card_semantic_features(row)


def _action_has_serialized_card_ref(action: Mapping[str, Any]) -> bool:
    payloads: list[Any] = []
    payload = action.get("payload")
    if isinstance(payload, Mapping):
        payloads.append(payload)
    signature = action.get("signature")
    if isinstance(signature, Mapping):
        signature_payload = signature.get("payload")
        if isinstance(signature_payload, Mapping):
            payloads.append(signature_payload)
    return any(_value_has_card_ref(payload_map) for payload_map in payloads)


def _value_has_card_ref(value: Any) -> bool:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if str(key) in {"cardId", "card_id", "base_card_id", "target_card_id", "source_card_id", "id"}:
                if _card_id_from_payload_value(child):
                    return True
            if _value_has_card_ref(child):
                return True
    if isinstance(value, list | tuple):
        return any(_value_has_card_ref(item) for item in value)
    return False


def _coverage_counter_to_dict(counter: Counter[str]) -> dict[str, int]:
    keys = (
        "legalActions",
        "serializedCardRefs",
        "actionCardKnown",
        "missingKnownForSerializedCardRefs",
    )
    return {key: int(counter.get(key, 0)) for key in keys}


def _replay_history_key(metadata: Mapping[str, Any]) -> tuple[str, ...]:
    cursor = metadata.get("replayCursor")
    cursor_map = cursor if isinstance(cursor, Mapping) else {}
    return (
        str(metadata.get("sourceRunId") or ""),
        str(metadata.get("sourceTaskId") or ""),
        str(metadata.get("runSeed") or cursor_map.get("runSeed") or ""),
        str(metadata.get("episodeIndex") or cursor_map.get("episodeIndex") or ""),
        str(metadata.get("modelSide") or ""),
    )


def _selected_history_item(row: Mapping[str, Any]) -> dict[str, Any] | None:
    try:
        slot = int(row.get("selectedActionSlot"))
    except (TypeError, ValueError):
        return None
    actions = row.get("actions") or []
    if not isinstance(actions, list | tuple) or slot < 0 or slot >= len(actions):
        return None
    action = actions[slot]
    if not isinstance(action, Mapping):
        return None
    return {
        "kind": str(action.get("kind") or "unknown"),
        "decisionKind": normalise_decision_kind(str(row.get("decisionKind") or "unknown")),
    }


def _refresh_action_semantic_features(row: dict[str, Any], *, force_full_refresh: bool = False) -> None:
    actions = row.get("actions") or []
    if not isinstance(actions, list):
        return
    action_list = [_action_from_serialized(action) for action in actions]
    if not action_list:
        return
    global_features = _feature_map(row.get("globalFeatureNames"), row.get("global_"))
    old_names = [str(name) for name in list(row.get("actionFeatureNames") or [])]
    old_name_set = set(old_names)
    current_name_set = set(ACTION_FEATURE_NAMES)
    preserved_names = old_name_set & current_name_set
    missing_names = tuple(name for name in ACTION_FEATURE_NAMES if name not in old_name_set)
    can_incremental_refresh = len(preserved_names) >= max(1, int(len(ACTION_FEATURE_NAMES) * 0.6))
    mask = row.get("mask_") or row.get("legalMask") or []
    old_rows = row.get("actions_") or []
    max_cards = _row_max_cards(row)
    card_slot_by_iid = _serialized_action_card_slot_by_iid(action_list, max_cards=max_cards)
    try:
        legal_count = int(row.get("legalCount") or 0)
    except (TypeError, ValueError):
        legal_count = 0
    row_count = max(len(action_list), len(mask) if isinstance(mask, list) else 0, len(old_rows) if isinstance(old_rows, list) else 0, legal_count)
    active_slots = _active_action_slots(
        mask=mask,
        legal_count=legal_count,
        action_count=len(action_list),
        row_count=row_count,
    )
    refreshed_rows: list[list[float]] = []
    for index in range(row_count):
        if index < len(action_list) and index in active_slots:
            if not force_full_refresh and can_incremental_refresh and index < len(old_rows):
                feature_map = _feature_map(old_names, old_rows[index])
                feature_map.update(
                    _missing_action_feature_map(
                        action_list[index],
                        missing_names,
                        context_decision_kind=str(row.get("decisionKind") or "unknown"),
                        global_features=global_features,
                        action_set_actions=action_list,
                        card_slot_by_iid=card_slot_by_iid,
                        max_cards=max_cards,
                    )
                )
                feature_map.update(
                    _refreshed_action_card_identity_feature_map(
                        action_list[index],
                        context_decision_kind=str(row.get("decisionKind") or "unknown"),
                        global_features=global_features,
                        action_set_actions=action_list,
                        card_slot_by_iid=card_slot_by_iid,
                        max_cards=max_cards,
                    )
                )
            else:
                feature_map = _action_feature_map(
                    action_list[index],
                    context_decision_kind=str(row.get("decisionKind") or "unknown"),
                    global_features=global_features,
                    action_set_actions=action_list,
                    card_slot_by_iid=card_slot_by_iid,
                    max_cards=max_cards,
                )
            if index < len(old_rows):
                _preserve_action_card_ref_features(feature_map, old_names, old_rows[index])
            refreshed_rows.append([float(feature_map[name]) for name in ACTION_FEATURE_NAMES])
        else:
            refreshed_rows.append([0.0 for _name in ACTION_FEATURE_NAMES])
    row["actionFeatureNames"] = list(ACTION_FEATURE_NAMES)
    row["actions_"] = refreshed_rows


def _active_action_slots(*, mask: Any, legal_count: int, action_count: int, row_count: int) -> set[int]:
    if isinstance(mask, list | tuple) and mask:
        return {
            index
            for index in range(min(row_count, len(mask), action_count))
            if bool(mask[index])
        }
    if legal_count > 0:
        return set(range(min(row_count, legal_count, action_count)))
    return set(range(min(row_count, action_count)))


def _preserve_action_card_ref_features(feature_map: dict[str, float], old_names: list[str], old_values: Any) -> None:
    values = _float_list(old_values)
    for feature_name in ("action_ref:source_card_slot_norm", "action_ref:target_card_slot_norm"):
        old_index = _feature_index(old_names, feature_name)
        if old_index is not None and old_index < len(values):
            old_value = float(values[old_index])
            if old_value > 0.0:
                feature_map[feature_name] = old_value


def _row_max_cards(row: Mapping[str, Any]) -> int:
    cards = row.get("cards_")
    if isinstance(cards, list | tuple) and cards:
        return len(cards)
    return 8


def _serialized_action_card_slot_by_iid(actions: list[Action], *, max_cards: int) -> dict[int, int]:
    slots: dict[int, int] = {}
    if max_cards <= 0:
        return slots
    for action in actions:
        source_iid, target_iid = _action_source_target_iids(action)
        for iid in (source_iid, target_iid):
            if iid is None or int(iid) in slots:
                continue
            if len(slots) >= int(max_cards):
                return slots
            slots[int(iid)] = len(slots)
    return slots


def _missing_action_feature_map(
    action: Action,
    missing_names: tuple[str, ...],
    *,
    context_decision_kind: str | None,
    global_features: dict[str, float],
    action_set_actions: list[Action],
    card_slot_by_iid: dict[int, int],
    max_cards: int,
) -> dict[str, float]:
    missing_set = set(missing_names)
    features = {name: 0.0 for name in missing_names}
    if not missing_set:
        return features

    if any(name.startswith("action_kind:") for name in missing_set):
        feature_name = f"action_kind:{normalise_action_kind(action)}"
        if feature_name in features:
            features[feature_name] = 1.0

    if any(name.startswith("decision:") for name in missing_set):
        feature_name = f"decision:{decision_kind_for_action(action, context_decision_kind=context_decision_kind)}"
        if feature_name in features:
            features[feature_name] = 1.0

    if any(name in missing_set for name in action_category_tags(action)):
        for tag in action_category_tags(action):
            if tag in features:
                features[tag] = 1.0

    if any(name.startswith("payload:") for name in missing_set):
        for name, value in payload_numeric_features(action).items():
            if name in features:
                features[name] = float(value)

    if any(name.startswith("state_action:") for name in missing_set):
        for name, value in action_state_numeric_features(
            action,
            global_features=global_features,
            action_set_actions=action_set_actions,
        ).items():
            if name in features:
                features[name] = float(value)

    if any(name.startswith("card_profile") for name in missing_set):
        for name, value in card_profile_numeric_features(action).items():
            if name in features:
                features[name] = float(value)

    if any(name.startswith("action_ref:") for name in missing_set):
        fresh = _action_feature_map(
            action,
            context_decision_kind=context_decision_kind,
            global_features=global_features,
            action_set_actions=action_set_actions,
            card_slot_by_iid=card_slot_by_iid,
            max_cards=max_cards,
        )
        for name in ("action_ref:source_card_slot_norm", "action_ref:target_card_slot_norm"):
            if name in features:
                features[name] = float(fresh.get(name, 0.0))

    return features


def _refreshed_action_card_identity_feature_map(
    action: Action,
    *,
    context_decision_kind: str | None,
    global_features: dict[str, float],
    action_set_actions: list[Action],
    card_slot_by_iid: dict[int, int],
    max_cards: int,
) -> dict[str, float]:
    fresh = _action_feature_map(
        action,
        context_decision_kind=context_decision_kind,
        global_features=global_features,
        action_set_actions=action_set_actions,
        card_slot_by_iid=card_slot_by_iid,
        max_cards=max_cards,
    )
    names = tuple(ACTION_CARD_FEATURE_NAMES) + (
        "action_ref:source_card_slot_norm",
        "action_ref:target_card_slot_norm",
    )
    return {name: float(fresh.get(name, 0.0)) for name in names}


def _refresh_global_semantic_features(row: dict[str, Any]) -> None:
    feature_map = _feature_map(row.get("globalFeatureNames"), row.get("global_"))
    row["globalFeatureNames"] = list(GLOBAL_FEATURE_NAMES)
    row["global_"] = [float(feature_map.get(name, 0.0)) for name in GLOBAL_FEATURE_NAMES]


def _refresh_card_semantic_features(row: dict[str, Any]) -> None:
    cards = row.get("cards_")
    if not isinstance(cards, list):
        return
    old_names = [str(name) for name in list(row.get("cardFeatureNames") or [])]
    card_ids_by_slot = _card_ids_by_slot_from_action_refs(row, max_cards=len(cards))
    refreshed_rows: list[list[float]] = []
    for index, values in enumerate(cards):
        feature_map = _feature_map(old_names, values)
        for card_id in card_ids_by_slot.get(index, ()):
            feature_name = f"card_id:{card_id}"
            if feature_name in CARD_FEATURE_NAMES:
                feature_map[feature_name] = 1.0
        refreshed_rows.append([float(feature_map.get(name, 0.0)) for name in CARD_FEATURE_NAMES])
    row["cardFeatureNames"] = list(CARD_FEATURE_NAMES)
    row["cards_"] = refreshed_rows


def _card_ids_by_slot_from_action_refs(row: Mapping[str, Any], *, max_cards: int) -> dict[int, set[str]]:
    if max_cards <= 0:
        return {}
    action_feature_names = [str(name) for name in list(row.get("actionFeatureNames") or [])]
    source_index = _feature_index(action_feature_names, "action_ref:source_card_slot_norm")
    target_index = _feature_index(action_feature_names, "action_ref:target_card_slot_norm")
    if source_index is None and target_index is None:
        return {}
    actions = row.get("actions") or []
    action_rows = row.get("actions_") or []
    if not isinstance(actions, list | tuple) or not isinstance(action_rows, list | tuple):
        return {}
    try:
        legal_count = int(row.get("legalCount") or 0)
    except (TypeError, ValueError):
        legal_count = 0
    out: dict[int, set[str]] = {}
    for index, action in enumerate(actions[:legal_count]):
        if not isinstance(action, Mapping) or index >= len(action_rows):
            continue
        values = _float_list(action_rows[index])
        if source_index is not None and source_index < len(values):
            slot = _slot_from_norm(values[source_index], max_cards=max_cards)
            card_id = _card_id_from_action_fields(
                action,
                fields=("card_id", "source_card_id", "base_card_id", "iid", "source_iid", "source_card_iid", "attacker_iid", "blocker_iid"),
            )
            if slot is not None and card_id:
                out.setdefault(slot, set()).add(card_id)
        if target_index is not None and target_index < len(values):
            slot = _slot_from_norm(values[target_index], max_cards=max_cards)
            card_id = _card_id_from_action_fields(
                action,
                fields=("target_card_id", "target_iid", "target_card_iid", "replace_field_iid", "replace_base_iid", "base_card_iid"),
            )
            if slot is not None and card_id:
                out.setdefault(slot, set()).add(card_id)
    return out


def _slot_from_norm(value: float, *, max_cards: int) -> int | None:
    if value <= 0.0 or max_cards <= 0:
        return None
    slot = int(round(value * max_cards)) - 1
    if slot < 0 or slot >= max_cards:
        return None
    expected = float(slot + 1) / float(max_cards)
    if abs(expected - value) > 1e-6:
        return None
    return slot


def _card_id_from_action_fields(action: Mapping[str, Any], *, fields: tuple[str, ...]) -> str | None:
    payloads = []
    payload = action.get("payload")
    if isinstance(payload, Mapping):
        payloads.append(payload)
    signature = action.get("signature")
    if isinstance(signature, Mapping) and isinstance(signature.get("payload"), Mapping):
        payloads.append(signature["payload"])
    for payload_map in payloads:
        for field in fields:
            card_id = _card_id_from_payload_value(payload_map.get(field))
            if card_id:
                return card_id
    return None


def _card_id_from_payload_value(value: Any) -> str | None:
    if isinstance(value, str):
        text = value.strip()
        return text if text else None
    if isinstance(value, Mapping):
        for field in ("cardId", "card_id", "base_card_id", "target_card_id", "source_card_id", "id"):
            card_id = _card_id_from_payload_value(value.get(field))
            if card_id:
                return card_id
    return None


def _action_from_serialized(value: Any) -> Action:
    if isinstance(value, Action):
        return value
    if isinstance(value, Mapping):
        payload = value.get("payload")
        payload_map = dict(payload) if isinstance(payload, Mapping) else {}
        _backfill_payload_card_ids_from_signature(value, payload_map)
        return Action(str(value.get("kind") or "unknown"), payload_map)
    return Action("unknown", {})


def _backfill_payload_card_ids_from_signature(action: Mapping[str, Any], payload: dict[str, Any]) -> None:
    if "card_id" not in payload and "source_card_id" not in payload:
        card_id = _card_id_from_action_fields(
            action,
            fields=(
                "card_id",
                "source_card_id",
                "card",
                "source_card",
                "attacker",
                "blocker",
                "iid",
                "source_iid",
                "source_card_iid",
                "attacker_iid",
                "blocker_iid",
            ),
        )
        if card_id:
            payload["card_id"] = card_id
    if "target_card_id" not in payload:
        target_card_id = _card_id_from_action_fields(
            action,
            fields=("target_card_id", "target", "target_iid", "target_card_iid", "replace_field_iid"),
        )
        if target_card_id:
            payload["target_card_id"] = target_card_id
    if "base_card_id" not in payload:
        base_card_id = _card_id_from_action_fields(
            action,
            fields=("base_card_id", "base_card_iid", "replace_base_iid"),
        )
        if base_card_id:
            payload["base_card_id"] = base_card_id


def _feature_map(names: Any, values: Any) -> dict[str, float]:
    if not isinstance(names, list | tuple) or not isinstance(values, list | tuple):
        return {}
    out: dict[str, float] = {}
    for name, value in zip(names, values, strict=False):
        try:
            out[str(name)] = float(value)
        except (TypeError, ValueError):
            out[str(name)] = 0.0
    return out


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


def write_normalized_action_set_teacher_rebuild(
    *,
    teacher_rows_path: str | Path,
    out_dir: str | Path,
    gzip_output: bool = False,
) -> dict[str, Any]:
    rows_path = Path(teacher_rows_path)
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    rows = _read_json_rows(rows_path)
    if not isinstance(rows, list):
        raise ValueError("teacher rows file must contain a JSON list")
    rebuilt = rebuild_normalized_action_set_teacher_rows(rows, source_path=rows_path)
    normalized_rows_path = out_path / (
        "normalized_action_set_teacher_rows.json.gz"
        if gzip_output
        else "normalized_action_set_teacher_rows.json"
    )
    report_path = out_path / "normalized_action_set_teacher_rebuild_report.json"
    _write_json_rows(normalized_rows_path, rebuilt["rows"], gzip_output=gzip_output)
    report = dict(rebuilt)
    report.pop("rows", None)
    report["normalizedTeacherRowsPath"] = str(normalized_rows_path)
    report["normalizedTeacherRowsCompression"] = "gzip" if gzip_output else None
    report["reportPath"] = str(report_path)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def _read_json_rows(path: Path) -> Any:
    if path.suffix.lower() == ".gz":
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            return expand_action_set_rows(json.load(handle))
    return expand_action_set_rows(json.loads(path.read_text(encoding="utf-8")))


def _write_json_rows(path: Path, rows: list[dict[str, Any]], *, gzip_output: bool) -> None:
    if gzip_output:
        with gzip.open(path, "wt", encoding="utf-8") as handle:
            json.dump(rows, handle, ensure_ascii=False, separators=(",", ":"))
        return
    path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
