from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
from pathlib import Path
from typing import Any

from zz.decks import validate_forces, validate_user_deck_recipe


DEFAULT_DECK_ROOT = Path(__file__).resolve().parents[2] / "data" / "decks"


def _canonical_deck_id(raw: Any) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "-", str(raw).strip()).strip("-").lower()[:48]


def _publish_new_deck_file(temporary: Path, path: Path) -> None:
    # Windows rename rejects an existing destination; POSIX link does too.
    if os.name == "nt":
        os.rename(temporary, path)
    else:
        os.link(temporary, path)


def _write_new_deck_file(path: Path, content: bytes) -> None:
    # Publish only a fully written file and never replace an existing player file.
    # Staging in the same directory keeps publication on the same filesystem.
    temporary = path.with_name(f".zz-deck-{secrets.token_hex(12)}.tmp")
    created = False
    try:
        with temporary.open("xb") as handle:
            created = True
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        _publish_new_deck_file(temporary, path)
    finally:
        if created:
            temporary.unlink(missing_ok=True)


def _decode_deck_object(content: bytes) -> dict[str, Any] | None:
    try:
        value = json.loads(content.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _migration_id(deck: dict[str, Any] | None) -> str | None:
    raw = deck.get("id") if deck is not None else None
    if not isinstance(raw, str) or not raw.strip():
        return None
    return _canonical_deck_id(raw) or None


def _deck_store_identity(root: Path) -> str:
    path = root / ".zz-deck-store-id"
    try:
        identity = path.read_text(encoding="ascii").strip()
    except FileNotFoundError:
        identity = secrets.token_hex(16)
        try:
            _write_new_deck_file(path, (identity + "\n").encode("ascii"))
        except FileExistsError:
            identity = path.read_text(encoding="ascii").strip()
    if not re.fullmatch(r"[0-9a-f]{32}", identity):
        raise ValueError(f"Invalid deck store identity: {path}")
    return identity


def _migrated_id(base: str, digest: str, attempt: int) -> str:
    if attempt == 0:
        return base
    suffix = f"-migrated-{digest[:8]}" + (f"-{attempt}" if attempt > 1 else "")
    return (base[: 48 - len(suffix)].rstrip("-") or "deck") + suffix


def _migrate_legacy_decks(legacy_root: Path, root: Path) -> dict[str, int]:
    result = {"copied": 0, "duplicates": 0, "renamed": 0, "invalid": 0}
    if not legacy_root.is_dir():
        return result

    existing: dict[str, list[dict[str, Any]]] = {}
    for path in sorted(root.glob("*.json")):
        deck = _decode_deck_object(path.read_bytes())
        deck_id = _migration_id(deck)
        if deck_id is not None and deck is not None:
            normalized = {**deck, "id": deck_id}
            existing.setdefault(deck_id, []).append(normalized)

    for source in sorted(legacy_root.glob("*.json")):
        content = source.read_bytes()
        deck = _decode_deck_object(content)
        base = _migration_id(deck)
        digest = hashlib.sha256(content).hexdigest()
        if base is None or deck is None:
            result["invalid"] += 1
            stem = _canonical_deck_id(source.stem) or "invalid"
            attempt = 0
            while True:
                name = source.name if attempt == 0 else f"{_migrated_id(stem, digest, attempt)}.json"
                destination = root / name
                try:
                    _write_new_deck_file(destination, content)
                    result["copied"] += 1
                    if attempt:
                        result["renamed"] += 1
                    break
                except FileExistsError:
                    if destination.is_file() and destination.read_bytes() == content:
                        result["duplicates"] += 1
                        break
                    attempt += 1
            continue

        attempt = 0
        while True:
            deck_id = _migrated_id(base, digest, attempt)
            normalized = {**deck, "id": deck_id}
            occupied = existing.get(deck_id, [])
            if normalized in occupied:
                result["duplicates"] += 1
                break
            if occupied:
                attempt += 1
                continue
            destination = root / f"{deck_id}.json"
            encoded = (json.dumps(normalized, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
            try:
                _write_new_deck_file(destination, encoded)
            except FileExistsError:
                # The name may belong to invalid data or a concurrently created deck.
                if destination.is_file():
                    other = _decode_deck_object(destination.read_bytes())
                    other_id = _migration_id(other)
                    if other is not None and other_id == deck_id and {**other, "id": other_id} == normalized:
                        result["duplicates"] += 1
                        break
                attempt += 1
                continue
            existing.setdefault(deck_id, []).append(normalized)
            result["copied"] += 1
            if attempt:
                result["renamed"] += 1
            break
    return result


def _read_migration_intent(pending: Path, marker: Path) -> str | None:
    try:
        intent = pending.read_text(encoding="ascii")
    except FileNotFoundError:
        # A completed migration takes precedence over a missing intent.
        if marker.exists():
            return None
        raise
    if intent not in ("seed\n", "skip\n"):
        raise ValueError(f"Invalid deck migration state: {pending}")
    return intent


def initialize_deck_storage(
    root: str | Path,
    *,
    legacy_root: str | Path | None = None,
    state_root: str | Path | None = None,
    bundled_root: str | Path | None = None,
) -> dict[str, int | bool]:
    root = Path(root).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    result: dict[str, int | bool] = {"copied": 0, "duplicates": 0, "renamed": 0, "invalid": 0, "seeded": 0, "already_migrated": False}
    bundled = Path(bundled_root).expanduser().resolve() if bundled_root is not None else None
    if bundled is not None and not bundled.is_dir():
        raise FileNotFoundError(f"Bundled default deck directory is missing: {bundled}")
    marker = None
    pending = None
    seed_defaults = bundled is not None and not any(root.glob("*.json"))
    if legacy_root is not None:
        legacy = Path(legacy_root).expanduser().resolve()
        if legacy != root:
            if state_root is None:
                raise ValueError("A state directory is required for deck migration")
            state = Path(state_root).expanduser().resolve()
            state.mkdir(parents=True, exist_ok=True)
            marker = state / f"deck-root-migration-{_deck_store_identity(root)}.done"
            pending = marker.with_suffix(".intent")
            defaults_marker = root / ".zz-deck-defaults-initialized"
            if marker.exists():
                result["already_migrated"] = True
                seed_defaults = False
            else:
                if pending.exists():
                    intent = _read_migration_intent(pending, marker)
                    result["already_migrated"] = intent is None
                    seed_defaults = intent == "seed\n"
                else:
                    result.update(_migrate_legacy_decks(legacy, root))
                    seed_defaults = bundled is not None and not defaults_marker.exists() and not any(root.glob("*.json"))
                    if marker.exists():
                        result["already_migrated"] = True
                        seed_defaults = False
                    else:
                        try:
                            _write_new_deck_file(pending, b"seed\n" if seed_defaults else b"skip\n")
                        except FileExistsError:
                            intent = _read_migration_intent(pending, marker)
                            result["already_migrated"] = intent is None
                            seed_defaults = intent == "seed\n"
    if seed_defaults and bundled is not None:
        for source in sorted(bundled.glob("*.json")):
            try:
                _write_new_deck_file(root / source.name, source.read_bytes())
            except FileExistsError:
                continue
            result["seeded"] = int(result["seeded"]) + 1
    if marker is not None and not result["already_migrated"]:
        try:
            _write_new_deck_file(defaults_marker, b"completed\n")
        except FileExistsError:
            pass
        try:
            _write_new_deck_file(marker, b"completed\n")
        except FileExistsError:
            pass
        # Keep the immutable intent: another starting instance may still be
        # reading it, and the completed marker always takes precedence.
    return result


class DeckStore:
    def __init__(self, root: str | Path | None = None):
        self.root = Path(root) if root is not None else DEFAULT_DECK_ROOT
        self.load_warnings: list[dict[str, str]] = []

    def list_decks(self) -> list[dict[str, Any]]:
        self.root.mkdir(parents=True, exist_ok=True)
        self.load_warnings = []
        decks = []
        for path in sorted(self.root.glob("*.json")):
            try:
                deck = json.loads(path.read_text(encoding="utf-8"))
                self._validate_stored_deck(deck)
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                self.load_warnings.append({"file": path.name, "message": str(exc)})
                continue
            decks.append(deck)
        return decks

    def save_deck(self, payload: dict[str, Any]) -> dict[str, Any]:
        recipe = self._recipe_from_payload(payload.get("recipe", {}))
        forces = self._forces_from_payload(payload.get("forces", []))
        validate_user_deck_recipe(recipe)
        validate_forces(forces)
        deck_id = self._deck_id(
            payload.get("id") or payload.get("name") or "deck",
            allow_existing=bool(payload.get("id")),
        )
        deck = {
            "id": deck_id,
            "name": str(payload.get("name") or "Unnamed Deck"),
            "recipe": recipe,
            "forces": forces,
        }
        self.root.mkdir(parents=True, exist_ok=True)
        path = self._path_for(deck_id)
        if path.exists() and _migration_id(_decode_deck_object(path.read_bytes())) != deck_id:
            raise ValueError(f"deck filename belongs to different or invalid data: {path}")
        tmp = path.with_name(f".zz-deck-{secrets.token_hex(12)}.tmp")
        created = False
        try:
            with tmp.open("x", encoding="utf-8") as handle:
                created = True
                json.dump(deck, handle, ensure_ascii=False, indent=2, sort_keys=True)
            tmp.replace(path)
        finally:
            if created:
                tmp.unlink(missing_ok=True)
        return deck

    def delete_deck(self, deck_id: str) -> bool:
        path = self._path_for(deck_id)
        if not path.exists():
            return False
        if _migration_id(_decode_deck_object(path.read_bytes())) != _canonical_deck_id(deck_id):
            raise ValueError(f"deck filename belongs to different or invalid data: {path}")
        path.unlink()
        return True

    def _recipe_from_payload(self, raw: Any) -> dict[str, int]:
        if not isinstance(raw, dict):
            raise ValueError("recipe must be an object")
        recipe: dict[str, int] = {}
        for card_id, count in raw.items():
            try:
                count_int = int(count)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"invalid card count for {card_id}: {count!r}") from exc
            if count_int > 0:
                recipe[str(card_id)] = count_int
        return recipe

    def _forces_from_payload(self, raw: Any) -> list[str]:
        if not isinstance(raw, list):
            raise ValueError("forces must be an array")
        return [str(force_id) for force_id in raw]

    def _validate_stored_deck(self, deck: dict[str, Any]) -> None:
        if not isinstance(deck, dict):
            raise ValueError("deck must be an object")
        if not deck.get("id") or not deck.get("name"):
            raise ValueError("deck id and name are required")
        validate_user_deck_recipe(self._recipe_from_payload(deck.get("recipe", {})))
        validate_forces(self._forces_from_payload(deck.get("forces", [])))

    def _deck_id(self, raw: Any, allow_existing: bool = False) -> str:
        deck_id = _canonical_deck_id(raw) or "deck"
        if not allow_existing and self._path_for(deck_id).exists():
            deck_id = f"{deck_id}-{secrets.token_hex(3)}"
        return deck_id

    def _path_for(self, deck_id: str) -> Path:
        clean = re.sub(r"[^A-Za-z0-9_-]+", "", str(deck_id))
        if not clean:
            raise ValueError("invalid deck id")
        path = (self.root / f"{clean}.json").resolve()
        root = self.root.resolve()
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise ValueError("invalid deck id") from exc
        requested = _canonical_deck_id(deck_id)
        matches = []
        for candidate in self.root.glob("*.json"):
            other = _decode_deck_object(candidate.read_bytes())
            if _migration_id(other) == requested:
                resolved = candidate.resolve()
                if not resolved.is_relative_to(root):
                    raise ValueError(f"deck file escapes deck directory: {candidate}")
                matches.append(resolved)
        if len(matches) > 1:
            raise ValueError(f"multiple deck files have the same id: {deck_id}")
        if matches:
            return matches[0]
        return path
