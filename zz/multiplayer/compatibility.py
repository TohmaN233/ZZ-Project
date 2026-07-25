from __future__ import annotations

import hashlib
import json
import re
from importlib.resources import files
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping


_MANIFEST_FIELDS = {
    "applicationVersion",
    "protocolVersion",
    "rulesVersion",
    "cardDatabaseChecksum",
}
_HELLO_FIELDS = {
    "applicationVersion",
    "rulesVersion",
    "cardDatabaseChecksum",
}

# These files define the card database and the rules path used by an
# authoritative multiplayer match. New authoritative definition files must be
# added here so the manifest freshness test detects them.
AUTHORITATIVE_DEFINITION_PATHS = tuple(sorted((
    "data/cards_bilingual_v4.tsv",
    "zz/basic.py",
    "zz/cards.py",
    "zz/deckcode0.py",
    "zz/decks.py",
    "zz/effects.py",
    "zz/engine.py",
    "zz/enums.py",
    "zz/forces.py",
    "zz/house_rules.py",
    "zz/keyword_rules.py",
    "zz/model.py",
    "zz/multiplayer/match.py",
    "zz/pc01.py",
    "zz/triggers.py",
    "zz/web/session.py",
)))


def _load_manifest() -> dict[str, Any]:
    resource = files("zz.multiplayer").joinpath("compatibility.json")
    manifest = json.loads(resource.read_text(encoding="utf-8"))
    return _validate_manifest(manifest)


def _validate_manifest(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != _MANIFEST_FIELDS:
        raise ValueError("compatibility manifest has invalid fields")
    application_version = value["applicationVersion"]
    protocol_version = value["protocolVersion"]
    rules_version = value["rulesVersion"]
    checksum = value["cardDatabaseChecksum"]
    if not isinstance(application_version, str) or not re.fullmatch(
        r"\d+\.\d+\.\d+", application_version
    ):
        raise ValueError("compatibility applicationVersion must be semantic version")
    if (
        isinstance(protocol_version, bool)
        or not isinstance(protocol_version, int)
        or protocol_version <= 0
    ):
        raise ValueError("compatibility protocolVersion must be a positive integer")
    if not isinstance(rules_version, str) or not rules_version:
        raise ValueError("compatibility rulesVersion must be a non-empty string")
    if not isinstance(checksum, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", checksum):
        raise ValueError("compatibility cardDatabaseChecksum must be SHA-256")
    return dict(value)


_COMPATIBILITY = _load_manifest()
COMPATIBILITY = MappingProxyType(_COMPATIBILITY)
APPLICATION_VERSION = str(COMPATIBILITY["applicationVersion"])
PROTOCOL_VERSION = int(COMPATIBILITY["protocolVersion"])
RULES_VERSION = str(COMPATIBILITY["rulesVersion"])
CARD_DATABASE_CHECKSUM = str(COMPATIBILITY["cardDatabaseChecksum"])


def compatibility_payload() -> dict[str, Any]:
    return dict(COMPATIBILITY)


def hello_compatibility_payload() -> dict[str, str]:
    return {
        field: str(COMPATIBILITY[field])
        for field in sorted(_HELLO_FIELDS)
    }


def is_compatible_hello(value: Mapping[str, Any]) -> bool:
    return dict(value) == hello_compatibility_payload()


def calculate_card_database_checksum(project_root: str | Path | None = None) -> str:
    root = (
        Path(project_root).resolve()
        if project_root is not None
        else Path(__file__).resolve().parents[2]
    )
    digest = hashlib.sha256()
    for relative_path in AUTHORITATIVE_DEFINITION_PATHS:
        path = root.joinpath(*relative_path.split("/"))
        content = path.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")
        encoded_path = relative_path.encode("utf-8")
        digest.update(len(encoded_path).to_bytes(4, "big"))
        digest.update(encoded_path)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return f"sha256:{digest.hexdigest()}"
