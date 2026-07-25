from __future__ import annotations

from typing import Any, Iterable

from zz.runtime_profile import RUNTIME_PROFILE_BUCKET_FIELDS, RUNTIME_PROFILE_COUNTER_FIELDS


def aggregate_runtime_profiles(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    row_list = list(rows)
    totals: dict[str, float] = {
        field_name: 0.0
        for field_name in RUNTIME_PROFILE_BUCKET_FIELDS.values()
    }
    counters: dict[str, int] = {
        field_name: 0
        for field_name in RUNTIME_PROFILE_COUNTER_FIELDS
    }
    timeouts = 0
    errors = 0
    profiled_count = 0
    for row in row_list:
        profile = row.get("runtimeProfile") if isinstance(row, dict) else None
        if not isinstance(profile, dict):
            continue
        profiled_count += 1
        for field_name in totals:
            totals[field_name] += _float(profile.get(field_name))
        for field_name in counters:
            counters[field_name] += int(_float(profile.get(field_name)))
        timeouts += int(_float(profile.get("timeouts")))
        errors += int(_float(profile.get("errors")))

    report: dict[str, Any] = {
        "rowCount": len(row_list),
        "profiledRowCount": profiled_count,
    }
    for field_name, value in totals.items():
        report[field_name] = round(float(value), 6)
    report.update(counters)
    report["timeouts"] = int(timeouts)
    report["errors"] = int(errors)
    total_seconds = float(report.get("totalSeconds", 0.0) or 0.0)
    actions = int(report.get("actions", 0) or 0)
    report["sps"] = round(actions / total_seconds, 6) if total_seconds > 0.0 else 0.0
    report["highestCostBucket"] = _highest_cost_bucket(report)
    return report


def _highest_cost_bucket(report: dict[str, Any]) -> str | None:
    candidates = [
        field_name
        for bucket, field_name in RUNTIME_PROFILE_BUCKET_FIELDS.items()
        if bucket != "total"
    ]
    best_field = None
    best_value = 0.0
    for field_name in candidates:
        value = _float(report.get(field_name))
        if best_field is None or value > best_value:
            best_field = field_name
            best_value = value
    return best_field if best_value > 0.0 else None


def _float(value: object) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0
