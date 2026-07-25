from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from zz.web.profiles import normalize_profile


DEFAULT_SETTINGS_ROOT = Path(__file__).resolve().parents[2] / "data" / "settings"
AI_DIFFICULTIES = {"easy", "normal", "deep"}
UI_LANGUAGES = {"zh", "ja", "en"}
BGM_TRACKS = {f"bgm_{index:02d}" for index in range(1, 21)}


def default_settings() -> dict[str, Any]:
    return {
        "playerProfile": normalize_profile({}),
        "opponentProfile": normalize_profile({}),
        "opponentAiDifficulty": "deep",
        "uiLanguage": "zh",
        "bgmTrack": "bgm_01",
        "developerMode": False,
        "reducedMotion": False,
    }


def normalize_ai_difficulty(value: Any) -> str:
    difficulty = str(value or "deep").strip().lower()
    if difficulty not in AI_DIFFICULTIES:
        raise ValueError(f"unknown opponent AI difficulty: {value!r}")
    return difficulty


def normalize_ui_language(value: Any) -> str:
    language = str(value or "zh").strip().lower()
    if language not in UI_LANGUAGES:
        raise ValueError(f"unknown UI language: {value!r}")
    return language


def normalize_bgm_track(value: Any) -> str:
    track = str(value or "bgm_01").strip().lower()
    if track not in BGM_TRACKS:
        raise ValueError(f"unknown BGM track: {value!r}")
    return track


def normalize_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


class SettingsStore:
    def __init__(self, root: str | Path | None = None):
        self.root = Path(root) if root is not None else DEFAULT_SETTINGS_ROOT

    def load(self) -> dict[str, Any]:
        settings = default_settings()
        path = self._path()
        if not path.exists():
            return settings
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return settings
        if not isinstance(raw, dict):
            return settings
        settings["playerProfile"] = normalize_profile(raw.get("playerProfile"))
        settings["opponentProfile"] = normalize_profile(raw.get("opponentProfile"))
        try:
            settings["opponentAiDifficulty"] = normalize_ai_difficulty(raw.get("opponentAiDifficulty"))
        except ValueError:
            settings["opponentAiDifficulty"] = "deep"
        try:
            settings["uiLanguage"] = normalize_ui_language(raw.get("uiLanguage"))
        except ValueError:
            settings["uiLanguage"] = "zh"
        try:
            settings["bgmTrack"] = normalize_bgm_track(raw.get("bgmTrack"))
        except ValueError:
            settings["bgmTrack"] = "bgm_01"
        settings["developerMode"] = normalize_bool(raw.get("developerMode"))
        settings["reducedMotion"] = normalize_bool(raw.get("reducedMotion"))
        return settings

    def save(self, payload: dict[str, Any]) -> dict[str, Any]:
        current = self.load()
        if isinstance(payload, dict):
            if "playerProfile" in payload:
                current["playerProfile"] = normalize_profile(payload.get("playerProfile"))
            if "opponentProfile" in payload:
                current["opponentProfile"] = normalize_profile(payload.get("opponentProfile"))
            if "opponentAiDifficulty" in payload:
                current["opponentAiDifficulty"] = normalize_ai_difficulty(payload.get("opponentAiDifficulty"))
            if "uiLanguage" in payload:
                current["uiLanguage"] = normalize_ui_language(payload.get("uiLanguage"))
            if "bgmTrack" in payload:
                current["bgmTrack"] = normalize_bgm_track(payload.get("bgmTrack"))
            if "reducedMotion" in payload:
                current["reducedMotion"] = normalize_bool(payload.get("reducedMotion"))
        return self._write(current)

    def set_developer_mode(self, enabled: bool) -> dict[str, Any]:
        current = self.load()
        current["developerMode"] = bool(enabled)
        return self._write(current)

    def _write(self, settings: dict[str, Any]) -> dict[str, Any]:
        self.root.mkdir(parents=True, exist_ok=True)
        path = self._path()
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(settings, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(path)
        return settings

    def _path(self) -> Path:
        path = (self.root / "settings.json").resolve()
        root = self.root.resolve()
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise ValueError("invalid settings root") from exc
        return path
