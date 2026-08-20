from __future__ import annotations

import json
import re
from pathlib import Path

from zz.multiplayer.compatibility import (
    AUTHORITATIVE_DEFINITION_PATHS,
    COMPATIBILITY,
    calculate_card_database_checksum,
)
from zz.multiplayer.match import RULES_VERSION
from zz.multiplayer.protocol import PROTOCOL_VERSION


ROOT = Path(__file__).resolve().parents[1]


def test_static_manifest_matches_versions_and_authoritative_definitions() -> None:
    package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")

    assert COMPATIBILITY["applicationVersion"] == package["version"] == "0.3.2"
    assert re.search(r'^version = "0\.3\.2"$', pyproject, re.MULTILINE)
    assert COMPATIBILITY["protocolVersion"] == PROTOCOL_VERSION
    assert COMPATIBILITY["rulesVersion"] == RULES_VERSION
    assert COMPATIBILITY["cardDatabaseChecksum"] == calculate_card_database_checksum(ROOT)


def test_checksum_scope_covers_the_authoritative_card_and_rules_sources() -> None:
    required = {
        "data/cards_bilingual_v4.tsv",
        "zz/basic.py",
        "zz/deckcode0.py",
        "zz/effects.py",
        "zz/engine.py",
        "zz/forces.py",
        "zz/multiplayer/match.py",
        "zz/pc01.py",
        "zz/web/session.py",
    }

    assert required <= set(AUTHORITATIVE_DEFINITION_PATHS)
    assert all((ROOT / path).is_file() for path in AUTHORITATIVE_DEFINITION_PATHS)


def test_checksum_normalizes_windows_and_linux_line_endings(tmp_path: Path) -> None:
    linux_root = tmp_path / "linux"
    windows_root = tmp_path / "windows"
    for relative_path in AUTHORITATIVE_DEFINITION_PATHS:
        linux_path = linux_root / relative_path
        windows_path = windows_root / relative_path
        linux_path.parent.mkdir(parents=True, exist_ok=True)
        windows_path.parent.mkdir(parents=True, exist_ok=True)
        linux_path.write_bytes(b"first\nsecond\n")
        windows_path.write_bytes(b"first\r\nsecond\r\n")

    assert calculate_card_database_checksum(linux_root) == calculate_card_database_checksum(
        windows_root
    )
