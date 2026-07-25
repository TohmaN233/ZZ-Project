from __future__ import annotations

import argparse
import gzip
import json
import sys
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from zz.action_set_dataset import read_action_set_rows, summarize_action_set_teacher_coverage


def summarize_action_set_teacher_rows_files(paths: list[str | Path]) -> dict[str, Any]:
    row_paths = [Path(path) for path in paths]
    coverage = summarize_action_set_teacher_coverage(_iter_rows_from_paths(row_paths))
    return {
        "kind": "action_set_teacher_rows_summary_v1",
        "createdAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "sourceTeacherRowsPaths": [str(path) for path in row_paths],
        "sourceTeacherRowsPathCount": len(row_paths),
        "coverage": coverage,
    }


def write_action_set_teacher_rows_summary(
    *,
    teacher_rows_paths: list[str | Path],
    out_path: str | Path,
) -> dict[str, Any]:
    report = summarize_action_set_teacher_rows_files(teacher_rows_paths)
    destination = Path(out_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    report["reportPath"] = str(destination)
    return report


def _iter_rows_from_paths(paths: list[Path]) -> Iterator[dict[str, Any]]:
    for path in paths:
        yield from _iter_json_array_rows(path)


def _iter_json_array_rows(path: Path) -> Iterator[dict[str, Any]]:
    opener = gzip.open if path.suffix.lower() == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as handle:
        first = _first_non_space_char(handle)
        handle.seek(0)
        if first == "{":
            yield from read_action_set_rows(path)
            return
        yield from _iter_json_array_text(handle)


def _first_non_space_char(handle: Any) -> str:
    while True:
        char = handle.read(1)
        if not char:
            return ""
        if not char.isspace():
            return char


def _iter_json_array_text(handle: Any, *, chunk_size: int = 1024 * 1024) -> Iterator[dict[str, Any]]:
    decoder = json.JSONDecoder()
    buffer = ""
    index = 0
    started = False
    eof = False

    while True:
        if not eof and len(buffer) - index < chunk_size:
            chunk = handle.read(chunk_size)
            if chunk:
                buffer = buffer[index:] + chunk
                index = 0
            else:
                eof = True

        while True:
            index = _skip_json_space(buffer, index)
            if not started:
                if index >= len(buffer):
                    break
                if buffer[index] != "[":
                    raise ValueError("teacher rows file must contain a JSON array")
                started = True
                index += 1
                continue

            index = _skip_json_space(buffer, index)
            if index >= len(buffer):
                break
            if buffer[index] == "]":
                return
            if buffer[index] == ",":
                index += 1
                index = _skip_json_space(buffer, index)

            try:
                item, end = decoder.raw_decode(buffer, index)
            except json.JSONDecodeError:
                if eof:
                    raise
                break
            if not isinstance(item, dict):
                raise ValueError("teacher row entries must be JSON objects")
            yield item
            index = end

        if eof:
            if not started:
                raise ValueError("teacher rows file must contain a JSON array")
            raise ValueError("unterminated teacher rows JSON array")


def _skip_json_space(text: str, index: int) -> int:
    while index < len(text) and text[index] in " \t\r\n":
        index += 1
    return index


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Summarize action-set teacher rows without loading every row at once.")
    parser.add_argument("--teacher-rows", action="append", required=True, help="Path to action_set_teacher_rows JSON or JSON.GZ. Can be repeated.")
    parser.add_argument("--out", required=True, help="Path for the summary JSON report.")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    report = write_action_set_teacher_rows_summary(
        teacher_rows_paths=args.teacher_rows,
        out_path=args.out,
    )
    print(
        json.dumps(
            {
                "reportPath": report["reportPath"],
                "rowCount": report["coverage"]["rowCount"],
                "byDecisionKind": report["coverage"]["byDecisionKind"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
