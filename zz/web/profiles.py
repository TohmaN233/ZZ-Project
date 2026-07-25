from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from zz.web.assets import AssetIndex, DEFAULT_CLEAN_GRAPH_ROOT


DEFAULT_CHARACTERS_PATH = DEFAULT_CLEAN_GRAPH_ROOT / "characters" / "characters.json"
SELECTABLE_CHARACTER_ROLES = {"codeman", "guest_character"}
HOME_GUIDE_CHARACTER_ID = "home_guide_operator"
KOUHOU_AI_MINA_CHARACTER_ID = "kouhou_ai_mina"


def _safe_id(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or "/" in text or "\\" in text or ".." in text:
        return None
    return text


def normalize_profile(raw: Any) -> dict[str, str | None]:
    if not isinstance(raw, dict):
        raw = {}
    return {
        "codemanId": _safe_id(raw.get("codemanId")),
        "playmatId": _safe_id(raw.get("playmatId")),
    }


def _load_character_entries(path: Path | None = None) -> list[dict[str, Any]]:
    source_path = path or DEFAULT_CHARACTERS_PATH
    if not source_path.exists():
        return []
    try:
        data = json.loads(source_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    characters = data.get("characters") if isinstance(data, dict) else None
    if not isinstance(characters, list):
        return []
    return [item for item in characters if isinstance(item, dict)]


def _character_asset_url(asset_index: AssetIndex, character_id: str, *kinds: str) -> str | None:
    for kind in kinds:
        url = asset_index.character_asset_url(character_id, kind)
        if url:
            return url
    return None


def character_catalog(asset_index: AssetIndex) -> list[dict[str, Any]]:
    characters: list[dict[str, Any]] = []
    character_path = (
        asset_index.clean_graph_root / "characters" / "characters.json"
        if asset_index.clean_graph_root is not None
        else DEFAULT_CHARACTERS_PATH
    )
    for entry in _load_character_entries(character_path):
        character_id = _safe_id(entry.get("id"))
        role = str(entry.get("role") or "").strip()
        if character_id is None or role not in SELECTABLE_CHARACTER_ROLES:
            continue
        portrait_url = _character_asset_url(asset_index, character_id, "portrait")
        characters.append({
            "id": character_id,
            "role": role,
            "number": entry.get("official_number"),
            "nameJp": str(entry.get("name_ja") or character_id),
            "nameZh": str(entry.get("name_zh") or ""),
            "nameEn": str(entry.get("name_en") or ""),
            "catchphraseJp": str(entry.get("catchphrase_ja") or ""),
            "catchphraseZh": str(entry.get("catchphrase_zh") or ""),
            "catchphraseEn": str(entry.get("catchphrase_en") or ""),
            "profileJp": str(entry.get("profile_ja") or entry.get("profile_note") or ""),
            "profileEn": str(entry.get("profile_en") or ""),
            "color": str(entry.get("color") or ""),
            "assetUrl": portrait_url,
            "portraitUrl": portrait_url,
            "thumbnailUrl": portrait_url,
        })
    if not any(item["id"] == KOUHOU_AI_MINA_CHARACTER_ID for item in characters):
        mina = kouhou_ai_mina_catalog(asset_index)
        if mina is not None:
            characters.append(mina)
    characters.sort(key=lambda item: (
        0 if item["role"] == "codeman" else 1,
        item["number"] or "99",
        item["nameJp"],
        item["id"],
    ))
    return characters


def kouhou_ai_mina_catalog(asset_index: AssetIndex) -> dict[str, Any] | None:
    asset_url = _character_asset_url(asset_index, KOUHOU_AI_MINA_CHARACTER_ID, "portrait")
    if not asset_url:
        return None
    return {
        "id": KOUHOU_AI_MINA_CHARACTER_ID,
        "role": "guest_character",
        "number": "mina",
        "nameJp": "広報AIミーナ",
        "nameZh": "宣传 AI ミーナ",
        "nameEn": "Publicity AI Mina",
        "catchphraseJp": "ZENONZARD ナビゲーター",
        "catchphraseZh": "ZENONZARD 导航员",
        "catchphraseEn": "ZENONZARD navigator",
        "profileJp": "",
        "profileEn": "",
        "color": "#32d5c8",
        "assetUrl": asset_url,
        "portraitUrl": asset_url,
        "thumbnailUrl": asset_url,
    }


def home_guide_catalog(asset_index: AssetIndex) -> dict[str, Any] | None:
    asset_url = _character_asset_url(asset_index, HOME_GUIDE_CHARACTER_ID, "portrait")
    if not asset_url:
        return None
    return {
        "id": HOME_GUIDE_CHARACTER_ID,
        "nameJp": "広報AIミーナ",
        "nameZh": "宣传 AI ミーナ",
        "role": "home_guide",
        "assetUrl": asset_url,
        "portraitUrl": asset_url,
    }


def profile_dto(raw: Any, asset_index: AssetIndex) -> dict[str, Any]:
    profile = normalize_profile(raw)
    characters_by_id = {item["id"]: item for item in character_catalog(asset_index)}
    codeman = characters_by_id.get(profile["codemanId"] or "")
    if codeman is None:
        profile["codemanId"] = None
    playmat_url = asset_index.playmat_url(profile["playmatId"])
    if playmat_url is None:
        profile["playmatId"] = None
    return {
        "codemanId": profile["codemanId"],
        "codeman": codeman,
        "playmatId": profile["playmatId"],
        "playmatUrl": playmat_url,
    }
