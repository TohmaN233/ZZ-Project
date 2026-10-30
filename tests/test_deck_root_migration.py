from __future__ import annotations

import json
import shutil
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest

from zz.web import deck_store, server
from zz.web.deck_store import DeckStore, initialize_deck_storage


ROOT = Path(__file__).resolve().parents[1]


def sample_deck(deck_id: str, name: str) -> dict:
    deck = json.loads((ROOT / "data/decks/h.json").read_text(encoding="utf-8"))
    return {**deck, "id": deck_id, "name": name}


def write_deck(root: Path, filename: str, deck: dict) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    path = root / filename
    path.write_text(json.dumps(deck, ensure_ascii=False), encoding="utf-8")
    return path


def test_migration_preserves_conflicts_and_does_not_resurrect_deleted_decks(tmp_path):
    root = tmp_path / "game/data/decks"
    legacy = tmp_path / "appdata/game-data/decks"
    state = tmp_path / "appdata/game-data/settings"
    existing = write_deck(root, "shared.json", sample_deck("shared", "Existing"))
    source = write_deck(legacy, "shared.json", sample_deck("shared", "Old version"))
    unique = write_deck(legacy, "different-filename.json", sample_deck("UPPER NAME", "Portable"))
    duplicate = write_deck(legacy, "duplicate.json", sample_deck("shared", "Existing"))
    before_existing = existing.read_bytes()
    originals = {p.name: p.read_bytes() for p in (source, unique, duplicate)}

    initialize_deck_storage(root, legacy_root=legacy, state_root=state)
    store = DeckStore(root)
    decks = store.list_decks()
    assert store.load_warnings == []
    assert {d["name"] for d in decks} == {"Existing", "Old version", "Portable"}
    assert len({d["id"] for d in decks}) == 3
    assert existing.read_bytes() == before_existing
    assert {p.name: p.read_bytes() for p in (source, unique, duplicate)} == originals
    for deck in decks:
        assert (root / f'{deck["id"]}.json').is_file()
    imported = next(d for d in decks if d["name"] == "Old version")
    assert imported["id"] != "shared"
    assert next(d for d in decks if d["name"] == "Portable")["id"] == "upper-name"

    assert store.delete_deck(imported["id"])
    initialize_deck_storage(root, legacy_root=legacy, state_root=state)
    assert {d["name"] for d in store.list_decks()} == {"Existing", "Portable"}
    assert source.read_bytes() == originals[source.name]

    moved = tmp_path / "moved-game/data/decks"
    shutil.copytree(root, moved)
    initialize_deck_storage(moved, legacy_root=legacy, state_root=state)
    assert {d["name"] for d in DeckStore(moved).list_decks()} == {"Existing", "Portable"}


def test_copied_game_merges_another_computers_legacy_without_overwriting(tmp_path):
    first = tmp_path / "first-game/data/decks"
    first_legacy = tmp_path / "first-appdata/decks"
    first_state = tmp_path / "first-appdata/settings"
    write_deck(first_legacy, "shared.json", sample_deck("shared", "First computer"))
    initialize_deck_storage(first, legacy_root=first_legacy, state_root=first_state)

    second = tmp_path / "second-game/data/decks"
    shutil.copytree(first, second)
    second_legacy = tmp_path / "second-appdata/decks"
    second_state = tmp_path / "second-appdata/settings"
    write_deck(second_legacy, "shared.json", sample_deck("shared", "Second computer"))
    initialize_deck_storage(second, legacy_root=second_legacy, state_root=second_state)
    decks = DeckStore(second).list_decks()
    assert {d["name"] for d in decks} == {"First computer", "Second computer"}
    assert len({d["id"] for d in decks}) == 2


def test_invalid_legacy_files_are_preserved_and_reported_without_hiding_valid_decks(tmp_path):
    root = tmp_path / "game/data/decks"
    legacy = tmp_path / "appdata/decks"
    state = tmp_path / "appdata/settings"
    bad_json = write_deck(legacy, "null-force.json", {**sample_deck("null-force", "Bad force"), "forces": None})
    bad_count = write_deck(legacy, "null-count.json", {**sample_deck("null-count", "Bad count"), "recipe": {"red_00_01_00_00": None}})
    malformed = legacy / "broken.json"
    malformed.write_bytes(b"{broken json")
    good = write_deck(legacy, "good.json", sample_deck("good", "Good"))
    originals = {p.name: p.read_bytes() for p in (bad_json, bad_count, malformed, good)}
    initialize_deck_storage(root, legacy_root=legacy, state_root=state)
    store = DeckStore(root)
    assert [deck["name"] for deck in store.list_decks()] == ["Good"]
    assert {warning["file"] for warning in store.load_warnings} == {"broken.json", "null-count.json", "null-force.json"}
    assert {p.name: p.read_bytes() for p in (bad_json, bad_count, malformed, good)} == originals


def test_incomplete_migration_retries_without_overwriting_or_duplicates(tmp_path, monkeypatch):
    root = tmp_path / "game/data/decks"
    legacy = tmp_path / "appdata/decks"
    state = tmp_path / "appdata/settings"
    write_deck(legacy, "a.json", sample_deck("a", "A"))
    write_deck(legacy, "b.json", sample_deck("b", "B"))
    original_write = deck_store._write_new_deck_file
    calls = 0

    def interrupted(path, data):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("simulated storage failure")
        return original_write(path, data)

    monkeypatch.setattr(deck_store, "_write_new_deck_file", interrupted)
    with pytest.raises(OSError, match="simulated storage failure"):
        initialize_deck_storage(root, legacy_root=legacy, state_root=state)
    monkeypatch.setattr(deck_store, "_write_new_deck_file", original_write)
    initialize_deck_storage(root, legacy_root=legacy, state_root=state)
    assert {deck["name"] for deck in DeckStore(root).list_decks()} == {"A", "B"}
    assert len(list(root.glob("*.json"))) == 2


def test_packaged_server_reads_and_saves_decks_in_the_game_root(tmp_path, monkeypatch):
    user_data = tmp_path / "appdata/game-data"
    legacy = user_data / "decks"
    bundled = tmp_path / "game/resources/default-decks"
    destination = tmp_path / "game/data/decks"
    old = write_deck(legacy, "old.json", sample_deck("old", "Migrated"))
    write_deck(bundled, "sample.json", sample_deck("sample", "Sample"))
    captured = {}

    class FakeServer:
        server_address = ("127.0.0.1", 12345)
        def serve_forever(self):
            return None

    def make_server(host, port, app):
        captured["app"] = app
        return FakeServer()

    monkeypatch.setattr(server, "make_server", make_server)
    server.main(["--user-data-root", str(user_data), "--deck-root", str(destination),
                 "--bundled-deck-root", str(bundled)])
    app = captured["app"]
    assert app.deck_root == destination.resolve()
    _, listed = server.dispatch_api(app, "GET", "/api/decks", None)
    assert [deck["name"] for deck in listed["decks"]] == ["Migrated"]
    _, saved = server.dispatch_api(app, "POST", "/api/decks", sample_deck("new", "New"))
    assert saved["ok"] and (destination / "new.json").is_file()
    assert old.is_file() and not (legacy / "new.json").exists()


def test_fresh_install_seeds_defaults_without_creating_appdata_deck_directory(tmp_path):
    root = tmp_path / "game/data/decks"
    legacy = tmp_path / "appdata/game-data/decks"
    state = tmp_path / "appdata/game-data/settings"
    bundled = tmp_path / "game/resources/default-decks"
    write_deck(bundled, "h.json", sample_deck("h", "Sample"))
    initialize_deck_storage(root, legacy_root=legacy, state_root=state, bundled_root=bundled)
    assert [deck["name"] for deck in DeckStore(root).list_decks()] == ["Sample"]
    assert not legacy.exists()
    assert DeckStore(root).delete_deck("h")
    initialize_deck_storage(root, legacy_root=legacy, state_root=state, bundled_root=bundled)
    assert DeckStore(root).list_decks() == []
    copied = tmp_path / "another-computer/game/data/decks"
    shutil.copytree(root, copied)
    initialize_deck_storage(copied, legacy_root=tmp_path / "other-appdata/decks",
                            state_root=tmp_path / "other-appdata/settings", bundled_root=bundled)
    assert DeckStore(copied).list_decks() == []


def test_interrupted_default_seeding_completes_on_retry(tmp_path, monkeypatch):
    root = tmp_path / "game/data/decks"
    legacy = tmp_path / "appdata/decks"
    state = tmp_path / "appdata/settings"
    bundled = tmp_path / "game/resources/default-decks"
    write_deck(bundled, "a.json", sample_deck("a", "A"))
    write_deck(bundled, "b.json", sample_deck("b", "B"))
    original_write = deck_store._write_new_deck_file

    def interrupted(path, data):
        if path == root / "b.json":
            raise OSError("simulated default deck write failure")
        return original_write(path, data)

    monkeypatch.setattr(deck_store, "_write_new_deck_file", interrupted)
    with pytest.raises(OSError, match="simulated default deck write failure"):
        initialize_deck_storage(root, legacy_root=legacy, state_root=state, bundled_root=bundled)
    assert (root / "a.json").is_file()
    monkeypatch.setattr(deck_store, "_write_new_deck_file", original_write)
    initialize_deck_storage(root, legacy_root=legacy, state_root=state, bundled_root=bundled)
    assert {deck["name"] for deck in DeckStore(root).list_decks()} == {"A", "B"}


def test_missing_bundled_defaults_are_reported(tmp_path):
    root = tmp_path / "game/data/decks"
    write_deck(root, "existing.json", sample_deck("existing", "Existing"))
    with pytest.raises(FileNotFoundError, match="Bundled default deck directory is missing"):
        initialize_deck_storage(root, bundled_root=tmp_path / "missing")


def test_partial_write_never_publishes_a_truncated_file(tmp_path, monkeypatch):
    destination = tmp_path / "deck.json"
    original_fsync = deck_store.os.fsync

    def failed_fsync(_fd):
        raise OSError("simulated interrupted write")

    monkeypatch.setattr(deck_store.os, "fsync", failed_fsync)
    with pytest.raises(OSError, match="simulated interrupted write"):
        deck_store._write_new_deck_file(destination, b'{"complete": true}')
    assert not destination.exists()
    assert list(tmp_path.iterdir()) == []
    monkeypatch.setattr(deck_store.os, "fsync", original_fsync)
    deck_store._write_new_deck_file(destination, b'{"complete": true}')
    assert json.loads(destination.read_bytes()) == {"complete": True}


def test_concurrent_initialization_publishes_one_complete_deck(tmp_path, monkeypatch):
    root = tmp_path / "game/data/decks"
    legacy = tmp_path / "appdata/decks"
    state = tmp_path / "appdata/settings"
    write_deck(legacy, "shared.json", sample_deck("shared", "Shared"))
    original_publish = deck_store._publish_new_deck_file
    barriers = {name: Barrier(2) for name in (".zz-deck-store-id", "shared.json")}

    def synchronized_publish(temporary, destination):
        if destination.name in barriers:
            barriers[destination.name].wait(timeout=10)
        return original_publish(temporary, destination)

    monkeypatch.setattr(deck_store, "_publish_new_deck_file", synchronized_publish)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(initialize_deck_storage, root, legacy_root=legacy, state_root=state)
                   for _ in range(2)]
        for future in futures:
            future.result(timeout=20)
    store = DeckStore(root)
    assert [deck["name"] for deck in store.list_decks()] == ["Shared"]
    assert store.load_warnings == []
    assert len(list(root.glob("*.json"))) == 1


def test_renamed_deck_files_remain_editable_without_duplicate_import(tmp_path):
    root = tmp_path / "game/data/decks"
    legacy = tmp_path / "appdata/decks"
    state = tmp_path / "appdata/settings"
    deck = sample_deck("real-id", "Original")
    renamed = write_deck(root, "my-backup-name.json", deck)
    write_deck(legacy, "real-id.json", deck)
    initialize_deck_storage(root, legacy_root=legacy, state_root=state)
    assert len(list(root.glob("*.json"))) == 1
    store = DeckStore(root)
    edited = store.save_deck({**deck, "name": "Edited"})
    assert edited["id"] == "real-id"
    assert json.loads(renamed.read_text(encoding="utf-8"))["name"] == "Edited"
    assert store.delete_deck("real-id")
    assert not renamed.exists()


def test_swapped_filenames_cannot_overwrite_another_deck(tmp_path):
    root = tmp_path / "decks"
    first = sample_deck("first", "First")
    second = sample_deck("second", "Second")
    first_file = write_deck(root, "second.json", first)
    second_file = write_deck(root, "first.json", second)
    original_second = second_file.read_bytes()
    store = DeckStore(root)
    store.save_deck({**first, "name": "First edited"})
    assert json.loads(first_file.read_text(encoding="utf-8"))["name"] == "First edited"
    assert second_file.read_bytes() == original_second
    assert store.delete_deck("first")
    assert not first_file.exists() and second_file.read_bytes() == original_second
