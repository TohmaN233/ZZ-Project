"""PC:02R registry and public-action semantic acceptance tests."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from zz.cards import CARD_REGISTRY
from zz.enums import CardType
from zz.pc02 import PC02_CARD_IDS
from zz.pc02r import PC02R_CARD_IDS

ROOT = Path(__file__).resolve().parents[1]
SCENARIOS = ROOT / "tests" / "semantic_scenarios" / "pc02r"
RUNNER = ROOT / "tools" / "run_semantic_scenario.py"
SCENARIO_FILES = tuple(sorted(SCENARIOS.glob("*.json")))


def test_pc02r_registry_matches_source_and_scenarios() -> None:
    assert len(PC02R_CARD_IDS) == len(set(PC02R_CARD_IDS)) == 106
    assert not (set(PC02R_CARD_IDS) & set(PC02_CARD_IDS))
    assert len(SCENARIO_FILES) == 212
    assert {f"{card_id}-{kind}.json" for card_id in PC02R_CARD_IDS for kind in ("positive", "boundary")} == {
        path.name for path in SCENARIO_FILES
    }
    for card_id in PC02R_CARD_IDS:
        card = CARD_REGISTRY[card_id]
        assert card.name_jp and card.id == card_id
        assert card.type is CardType.MAGIC or (card.bp >= 0 and card.dp >= 0)


@pytest.mark.parametrize("scenario", SCENARIO_FILES, ids=lambda path: path.stem)
def test_pc02r_semantic_scenario(scenario: Path, tmp_path: Path) -> None:
    evidence = tmp_path / "evidence.json"
    result = subprocess.run(
        [sys.executable, str(RUNNER), str(scenario), "--project-root", str(ROOT), "--evidence", str(evidence)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert evidence.is_file(), scenario.name
    record = json.loads(evidence.read_text(encoding="utf-8"))
    assert record, scenario.name
