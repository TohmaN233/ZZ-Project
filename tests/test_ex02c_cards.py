"""EX02C registry and public-action semantic acceptance tests."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from zz.cards import CARD_REGISTRY
from zz.ex02c import EX02C_CARD_IDS


ROOT = Path(__file__).resolve().parents[1]
SCENARIOS = ROOT / "tests" / "semantic_scenarios" / "ex02c"
RUNNER = ROOT / "tools" / "run_semantic_scenario.py"
SCENARIO_FILES = tuple(sorted(SCENARIOS.glob("*.json")))


def test_ex02c_registry_matches_source_and_scenarios() -> None:
    assert len(EX02C_CARD_IDS) == len(set(EX02C_CARD_IDS)) == 70
    expected = {
        f"{card_id}-{kind}.json"
        for card_id in EX02C_CARD_IDS
        for kind in ("positive", "boundary")
    } | {"green_08_02_02c_01-trash-boundary.json"}
    assert {path.name for path in SCENARIO_FILES} == expected
    for path in SCENARIO_FILES:
        scenario = json.loads(path.read_text(encoding="utf-8"))
        assert scenario["card_id"] in EX02C_CARD_IDS, path.name
        assert CARD_REGISTRY[scenario["card_id"]].name_jp, path.name


@pytest.mark.parametrize("scenario", SCENARIO_FILES, ids=lambda path: path.stem)
def test_ex02c_semantic_scenario(scenario: Path, tmp_path: Path) -> None:
    evidence = tmp_path / "evidence.json"
    result = subprocess.run(
        [sys.executable, "-B", str(RUNNER), str(scenario), "--project-root", str(ROOT),
         "--evidence", str(evidence)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert evidence.is_file(), scenario.name
    assert json.loads(evidence.read_text(encoding="utf-8")), scenario.name
