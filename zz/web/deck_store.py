from __future__ import annotations

import json
import re
import secrets
from pathlib import Path
from typing import Any

from zz.decks import validate_forces, validate_user_deck_recipe


DEFAULT_DECK_ROOT = Path(__file__).resolve().parents[2] / "data" / "decks"


class DeckStore:
    def __init__(self, root: str | Path | None = None):
        self.root = Path(root) if root is not None else DEFAULT_DECK_ROOT

    def list_decks(self) -> list[dict[str, Any]]:
        self.root.mkdir(parents=True, exist_ok=True)
        decks = []
        for path in sorted(self.root.glob("*.json")):
            try:
                deck = json.loads(path.read_text(encoding="utf-8"))
                self._validate_stored_deck(deck)
            except (OSError, ValueError, json.JSONDecodeError):
                continue
            decks.append(deck)
        return decks

    def save_deck(self, payload: dict[str, Any]) -> dict[str, Any]:
        recipe = self._recipe_from_payload(payload.get("recipe", {}))
        forces = [str(force_id) for force_id in payload.get("forces", [])]
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
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(deck, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(path)
        return deck

    def delete_deck(self, deck_id: str) -> bool:
        path = self._path_for(deck_id)
        if not path.exists():
            return False
        path.unlink()
        return True

    def _recipe_from_payload(self, raw: Any) -> dict[str, int]:
        if not isinstance(raw, dict):
            raise ValueError("recipe must be an object")
        recipe: dict[str, int] = {}
        for card_id, count in raw.items():
            count_int = int(count)
            if count_int > 0:
                recipe[str(card_id)] = count_int
        return recipe

    def _validate_stored_deck(self, deck: dict[str, Any]) -> None:
        if not isinstance(deck, dict):
            raise ValueError("deck must be an object")
        if not deck.get("id") or not deck.get("name"):
            raise ValueError("deck id and name are required")
        validate_user_deck_recipe(self._recipe_from_payload(deck.get("recipe", {})))
        validate_forces([str(force_id) for force_id in deck.get("forces", [])])

    def _deck_id(self, raw: Any, allow_existing: bool = False) -> str:
        base = re.sub(r"[^A-Za-z0-9_-]+", "-", str(raw).strip()).strip("-").lower()
        if not base:
            base = "deck"
        deck_id = base[:48]
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
        return path
