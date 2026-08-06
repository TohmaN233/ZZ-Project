from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from zz.codeman_semantic_audit import audit_actor_semantic_contract, audit_codeman_trace_files


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Audit real Codeman traces for semantically invalid or suspicious choices."
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--codeman-id")
    source.add_argument("--trace", action="append", type=Path)
    source.add_argument("--model", type=Path)
    parser.add_argument("--data-root", type=Path, default=PROJECT_ROOT / "data")
    parser.add_argument("--early-turn-max", type=int, default=3)
    args = parser.parse_args()

    if args.model:
        report = audit_actor_semantic_contract(args.model.resolve())
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["passed"] else 1
    if args.trace:
        paths = [path.resolve() for path in args.trace]
    else:
        trace_dir = args.data_root / "codeman_ai" / args.codeman_id / "traces"
        paths = sorted(trace_dir.glob("*.json"))
    if not paths:
        raise FileNotFoundError("No Codeman trace files found")

    report = audit_codeman_trace_files(paths, early_turn_max=args.early_turn_max)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if report["semanticViolationCount"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
