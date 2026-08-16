from __future__ import annotations

import json
import os
import re
from pathlib import Path
from urllib.parse import quote, urlparse


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ASSET_ROOT = PROJECT_ROOT / "asserts"
DEFAULT_OFFICIAL_CARDLIST = PROJECT_ROOT / "data" / "official_cardlist.tsv"
DEFAULT_CLEAN_GRAPH_ROOT = PROJECT_ROOT / "asserts" / "images" / "clean_graph"
LEGACY_CLEAN_GRAPH_ROOT = PROJECT_ROOT / "data" / "apk_images" / "clean_graph"
LEGACY_BATTLE_SFX_AUDIO_ROOT = PROJECT_ROOT / "data" / "audio" / "battle_sfx"
FORCE_IMAGE_NAMES = {
    asset_id: [f"{asset_id}.png"]
    for asset_id in (
        "force_e",
        "force_kon",
        "force_kai",
        "force_so",
        "force_sei",
        "force_chi",
        "force_li",
        "force_sho",
        "force_so2",
        "force_rin",
    )
}

CARD_COLOR_DIRS = ["RED", "YELLOW", "WHITE", "GREEN", "BLUE", "PURPLE", "COLORLESS"]
ENGLISH_CARD_DIR = "Eng-cards"
ENGLISH_CARD_MANIFEST = "manifest.json"
PLAYMAT_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
PLAYMAT_EXCLUDED_STEMS = {"contact_sheet"}
CHARACTER_PORTRAIT_DIR = "codeman_portraits"
HOME_GUIDE_CHARACTER_ID = "home_guide_operator"
HOME_GUIDE_CHARACTER_FILES = ("operator.png",)
KOUHOU_AI_MINA_CHARACTER_ID = "kouhou_ai_mina"
KOUHOU_AI_MINA_CHARACTER_FILES = (f"{CHARACTER_PORTRAIT_DIR}/mina.png",)

CARD_IMAGE_NAMES: dict[str, list[str]] = {}

TOKEN_IMAGE_NAMES = {
    "s_golem_token": ["red_01_04_00_00.png"],
    "merfolk_token": ["blue_02_04_00_00.png"],
    "slime_block_token": ["colorless_01_04_00_00.png"],
    "s_aryushinashion_token": ["purple_02_04_00_00.png"],
}

AUDIO_NAMES = {
    f"bgm_{index:02d}": [Path("audio") / "bgm" / f"bgm_{index:02d}.wav"]
    for index in range(1, 21)
}

BATTLE_SFX_AUDIO_NAMES = {
    "sfx_heal": "heal.wav",
    "sfx_force_damage": "force_damage.wav",
    "sfx_player_damage": "player_damage.wav",
    "sfx_base_minion_place": "base_minion_place.wav",
    "sfx_minion_summon": "minion_summon.wav",
    "sfx_minion_rest": "minion_rest.wav",
    "sfx_minion_clash": "minion_clash.wav",
    "sfx_draw_card": "draw_card.wav",
    "sfx_shuffle": "shuffle.wav",
}


def resolve_asset_root(value: str | os.PathLike | None = None) -> Path | None:
    if value:
        configured = Path(value).expanduser().resolve()
        for candidate in (configured, configured / "asserts"):
            if _looks_like_asset_root(candidate):
                return candidate.resolve()
        raise FileNotFoundError(
            f"asset root not found or incomplete: {configured} "
            "(expected ZENONZARD_CARDLIST/, audio/, and video/)"
        )
    env_value = os.environ.get("ZENONZARD_ASSET_ROOT")
    if env_value:
        configured = Path(env_value).expanduser().resolve()
        for candidate in (configured, configured / "asserts"):
            if _looks_like_asset_root(candidate):
                return candidate.resolve()
        raise FileNotFoundError(
            f"ZENONZARD_ASSET_ROOT is not a complete asset root: {configured}"
        )
    for candidate in (DEFAULT_ASSET_ROOT, DEFAULT_ASSET_ROOT / "asserts"):
        if _looks_like_asset_root(candidate):
            return candidate.resolve()
    return None


def _looks_like_asset_root(path: Path) -> bool:
    return path.is_dir() and all((path / name).is_dir() for name in ("ZENONZARD_CARDLIST", "audio", "video"))


def resolve_official_cardlist(value: str | os.PathLike | None = None) -> Path | None:
    if value:
        path = Path(value).expanduser().resolve()
        return path if path.exists() else None
    env_value = os.environ.get("ZENONZARD_OFFICIAL_CARDLIST")
    if env_value:
        path = Path(env_value).expanduser().resolve()
        return path if path.exists() else None
    if DEFAULT_OFFICIAL_CARDLIST.exists():
        return DEFAULT_OFFICIAL_CARDLIST.resolve()
    return None


class AssetIndex:
    def __init__(
        self,
        root: str | os.PathLike | None,
        official_cardlist_path: str | os.PathLike | None = None,
        clean_graph_root: str | os.PathLike | None = None,
    ):
        self.root = resolve_asset_root(root)
        self.clean_graph_root = self._resolve_clean_graph_root(clean_graph_root)
        self._manifest: dict[str, Path] = {}
        self._audio_manifest: dict[str, Path] = {}
        self._ui_asset_ids: set[str] = set()
        self._playmat_asset_ids: set[str] = set()
        self._playmat_catalog: list[dict[str, object]] = []
        self._character_asset_ids: set[str] = set()
        self._english_asset_ids: dict[str, str] = {}
        self._mana_asset_ids: dict[str, str] = {}
        if self.root is not None:
            self._build_manifest()
        self._build_local_audio_manifest()
        if self.clean_graph_root is not None:
            self._build_clean_graph_manifest()

    def _resolve_clean_graph_root(self, value: str | os.PathLike | None) -> Path | None:
        if value:
            path = Path(value).expanduser().resolve()
            return path if path.exists() else None
        if self.root is not None:
            path = self.root / "images" / "clean_graph"
            if path.exists():
                return path.resolve()
        if LEGACY_CLEAN_GRAPH_ROOT.exists():
            return LEGACY_CLEAN_GRAPH_ROOT.resolve()
        return None

    def _build_manifest(self) -> None:
        assert self.root is not None
        self._add_if_exists("card_back", self.root / "card_back" / "XGT01_000_F.png")
        force_dir = self.root / "ZENONZARD_CARDLIST" / "FORCE"
        for asset_id, names in FORCE_IMAGE_NAMES.items():
            for name in names:
                if self._add_if_exists(asset_id, force_dir / name):
                    break
        card_root = self.root / "ZENONZARD_CARDLIST"
        for color_dir_name in CARD_COLOR_DIRS:
            color_dir = card_root / color_dir_name
            if not color_dir.is_dir():
                continue
            for path in color_dir.glob("*.png"):
                self._add_if_exists(path.stem, path)
        token_dir = card_root / "tokens"
        if token_dir.is_dir():
            for path in token_dir.glob("*.png"):
                self._add_if_exists(path.stem, path)
            for asset_id, names in TOKEN_IMAGE_NAMES.items():
                for name in names:
                    if self._add_if_exists(asset_id, token_dir / name):
                        break
        red_dir = card_root / "RED"
        for asset_id, names in CARD_IMAGE_NAMES.items():
            for name in names:
                if self._add_if_exists(asset_id, red_dir / name):
                    break
        for audio_id, names in AUDIO_NAMES.items():
            for name in names:
                if self._add_audio_if_exists(audio_id, self.root / name):
                    break
        self._build_english_card_manifest()

    def _build_english_card_manifest(self) -> None:
        assert self.root is not None
        english_root = self.root / ENGLISH_CARD_DIR
        data = self._load_json(english_root / ENGLISH_CARD_MANIFEST)
        if data is None:
            return
        if not isinstance(data, dict) or data.get("schemaVersion") != 1:
            raise ValueError("invalid English card asset manifest")
        for group_name in ("cards", "forces"):
            entries = data.get(group_name)
            if not isinstance(entries, dict):
                raise ValueError(f"English card asset manifest is missing {group_name}")
            for card_id, relative_path in entries.items():
                synthetic_id = self._register_manifest_asset(
                    english_root, "english", card_id, relative_path
                )
                self._english_asset_ids[card_id] = synthetic_id
        mana_entries = data.get("mana")
        if not isinstance(mana_entries, dict):
            raise ValueError("English card asset manifest is missing mana")
        for color, relative_path in mana_entries.items():
            normalized_color = str(color).upper()
            synthetic_id = self._register_manifest_asset(
                english_root, "mana", normalized_color, relative_path
            )
            self._mana_asset_ids[normalized_color] = synthetic_id

    def _register_manifest_asset(
        self,
        base: Path,
        namespace: str,
        asset_id: object,
        relative_path: object,
    ) -> str:
        if not isinstance(asset_id, str) or not self._safe_asset_id(asset_id):
            raise ValueError(f"invalid {namespace} asset id: {asset_id!r}")
        if not isinstance(relative_path, str) or urlparse(relative_path).scheme:
            raise ValueError(f"invalid {namespace} asset path for {asset_id}")
        path = Path(relative_path)
        if path.is_absolute():
            raise ValueError(f"absolute {namespace} asset path for {asset_id}")
        resolved = (base / path).resolve()
        try:
            resolved.relative_to(base.resolve())
        except ValueError as exc:
            raise ValueError(f"{namespace} asset escapes its root: {asset_id}") from exc
        synthetic_id = f"{namespace}:{asset_id}"
        if not self._add_if_exists(synthetic_id, resolved):
            raise FileNotFoundError(f"missing {namespace} asset for {asset_id}: {resolved}")
        return synthetic_id

    def _build_local_audio_manifest(self) -> None:
        if self.root is not None:
            audio_root = self.root / "audio" / "battle_sfx"
            for audio_id, relative_name in BATTLE_SFX_AUDIO_NAMES.items():
                if self._add_audio_if_exists(audio_id, audio_root / relative_name):
                    continue
        for audio_id, relative_name in BATTLE_SFX_AUDIO_NAMES.items():
            if audio_id in self._audio_manifest:
                continue
            self._add_audio_if_exists(audio_id, LEGACY_BATTLE_SFX_AUDIO_ROOT / relative_name)

    def _build_clean_graph_manifest(self) -> None:
        assert self.clean_graph_root is not None
        self._build_ui_manifest()
        self._build_playmat_manifest()
        self._build_character_manifest()

    def _build_ui_manifest(self) -> None:
        assert self.clean_graph_root is not None
        ui_base = self.clean_graph_root / "ui"
        manifest_path = ui_base / "ui_manifest.json"
        data = self._load_json(manifest_path)
        if not isinstance(data, dict):
            return
        assets = data.get("assets")
        items = assets.items() if isinstance(assets, dict) else ()
        for asset_id, relative_path in items:
            if not isinstance(asset_id, str) or not isinstance(relative_path, str):
                continue
            path = self._resolve_clean_graph_path(ui_base, relative_path)
            if path is not None and self._add_clean_graph_asset(asset_id, path):
                self._ui_asset_ids.add(asset_id)

    def _build_playmat_manifest(self) -> None:
        assert self.clean_graph_root is not None
        playmat_base = self.clean_graph_root / "playmats"
        data = self._load_json(playmat_base / "manifest.json")
        registered_paths: set[Path] = set()
        if isinstance(data, list):
            for entry in data:
                if not isinstance(entry, dict):
                    continue
                filename = entry.get("file")
                if not isinstance(filename, str):
                    continue
                path = self._resolve_clean_graph_path(playmat_base, filename)
                if path is None:
                    continue
                explicit_id = entry.get("id")
                asset_id = explicit_id if isinstance(explicit_id, str) and explicit_id else path.stem
                if self._register_playmat_asset(asset_id, path, entry.get("width"), entry.get("height")):
                    registered_paths.add(path.resolve())
        if playmat_base.is_dir():
            for path in sorted(playmat_base.iterdir(), key=lambda item: item.name.lower()):
                if not self._is_discoverable_playmat_file(path):
                    continue
                resolved = path.resolve()
                if resolved in registered_paths:
                    continue
                asset_id = self._unique_playmat_asset_id(self._playmat_asset_id(path))
                self._register_playmat_asset(asset_id, path, None, None)
        self._playmat_catalog.sort(key=lambda item: str(item["id"]))

    def _build_character_manifest(self) -> None:
        assert self.clean_graph_root is not None
        chara_base = self.clean_graph_root / "characters"
        data = self._load_json(chara_base / "characters.json")
        if isinstance(data, dict):
            characters = data.get("characters")
            if isinstance(characters, list):
                for character in characters:
                    if not isinstance(character, dict):
                        continue
                    character_id = character.get("id")
                    assets = character.get("assets")
                    if not isinstance(character_id, str) or not self._safe_asset_id(character_id):
                        continue
                    if not isinstance(assets, dict):
                        continue
                    for kind, relative_path in assets.items():
                        self._register_character_asset(chara_base, character_id, kind, relative_path)
        self._register_home_guide_character_asset(chara_base)
        self._register_kouhou_ai_mina_character_asset(chara_base)

    def _register_playmat_asset(self, asset_id: str, path: Path, width: object, height: object) -> bool:
        if self._add_clean_graph_asset(asset_id, path):
            self._playmat_asset_ids.add(asset_id)
            self._playmat_catalog.append({
                "id": asset_id,
                "file": path.name,
                "width": width,
                "height": height,
                "assetUrl": self.asset_url(asset_id),
            })
            return True
        return False

    def _is_discoverable_playmat_file(self, path: Path) -> bool:
        return (
            path.is_file()
            and path.suffix.lower() in PLAYMAT_IMAGE_SUFFIXES
            and path.stem.lower() not in PLAYMAT_EXCLUDED_STEMS
        )

    def _playmat_asset_id(self, path: Path) -> str:
        slug = re.sub(r"[^\w]+", "_", path.stem, flags=re.UNICODE).strip("_").lower()
        if not slug:
            slug = "image"
        return slug if slug.startswith("playmat_") else f"playmat_{slug}"

    def _unique_playmat_asset_id(self, asset_id: str) -> str:
        if asset_id not in self._manifest and asset_id not in self._playmat_asset_ids:
            return asset_id
        suffix = 2
        while f"{asset_id}_{suffix}" in self._manifest or f"{asset_id}_{suffix}" in self._playmat_asset_ids:
            suffix += 1
        return f"{asset_id}_{suffix}"

    def _register_home_guide_character_asset(self, chara_base: Path) -> None:
        for filename in HOME_GUIDE_CHARACTER_FILES:
            if self._register_character_asset(chara_base, HOME_GUIDE_CHARACTER_ID, "portrait", filename):
                return

    def _register_kouhou_ai_mina_character_asset(self, chara_base: Path) -> None:
        for filename in KOUHOU_AI_MINA_CHARACTER_FILES:
            if self._register_character_asset(chara_base, KOUHOU_AI_MINA_CHARACTER_ID, "portrait", filename):
                return

    def _register_character_asset(self, base: Path, character_id: str, kind: str, relative_path: object) -> bool:
        if not isinstance(character_id, str) or not self._safe_asset_id(character_id):
            return False
        if not isinstance(kind, str) or not self._safe_asset_id(kind):
            return False
        if not isinstance(relative_path, str) or urlparse(relative_path).scheme:
            return False
        asset_id = self._character_asset_id(character_id, kind)
        path = self._resolve_clean_graph_path(base, relative_path)
        if path is None or not self._add_clean_graph_asset(asset_id, path):
            return False
        self._character_asset_ids.add(asset_id)
        return True

    def _load_json(self, path: Path) -> object | None:
        if not path.exists():
            return None
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    def _resolve_clean_graph_path(self, base: Path, relative_path: str) -> Path | None:
        if self.clean_graph_root is None:
            return None
        path = Path(relative_path)
        if path.is_absolute():
            return None
        resolved = (base / path).resolve()
        try:
            resolved.relative_to(self.clean_graph_root)
        except ValueError:
            return None
        return resolved

    def _add_if_exists(self, asset_id: str, path: Path) -> bool:
        if path.exists() and self._is_under_root(path):
            self._manifest[asset_id] = path.resolve()
            return True
        return False

    def _add_clean_graph_asset(self, asset_id: str, path: Path) -> bool:
        if not self._safe_asset_id(asset_id) or asset_id in self._manifest:
            return False
        return self._add_if_exists(asset_id, path)

    def _add_audio_if_exists(self, audio_id: str, path: Path) -> bool:
        if path.exists() and self._is_under_root(path):
            self._audio_manifest[audio_id] = path.resolve()
            return True
        return False

    def _is_under_root(self, path: Path) -> bool:
        roots = [
            root
            for root in (
                self.root,
                self.clean_graph_root,
                LEGACY_BATTLE_SFX_AUDIO_ROOT,
            )
            if root is not None
        ]
        try:
            resolved = path.resolve()
        except OSError:
            return False
        for root in roots:
            try:
                resolved.relative_to(root)
            except ValueError:
                continue
            return True
        return False

    def resolve_asset_id(self, asset_id: str) -> Path | None:
        if not self._safe_asset_id(asset_id):
            return None
        path = self._manifest.get(asset_id)
        if path is None or not self._is_under_root(path):
            return None
        return path

    def _local_asset_url(self, asset_id: str) -> str:
        return f"/assets/{quote(asset_id)}"

    def asset_url(self, asset_id: str | None) -> str | None:
        if not asset_id or not self._safe_asset_id(asset_id):
            return None
        if self.resolve_asset_id(asset_id) is not None:
            return self._local_asset_url(asset_id)
        english_id = self._english_asset_ids.get(asset_id)
        if english_id is not None:
            return self._local_asset_url(english_id)
        return self._local_asset_url(asset_id)

    def asset_url_en(self, asset_id: str | None) -> str | None:
        if not asset_id or not self._safe_asset_id(asset_id):
            return None
        local_id = self._english_asset_ids.get(asset_id)
        if local_id is not None:
            return self._local_asset_url(local_id)
        return self.asset_url(asset_id)

    def mana_asset_url(self, color: str | None) -> str | None:
        normalized = str(color or "COLORLESS").upper()
        local_id = self._mana_asset_ids.get(normalized)
        if local_id is None:
            return None
        return self.asset_url(local_id)

    def mana_asset_catalog(self) -> dict[str, str]:
        return {
            color: url
            for color in sorted(self._mana_asset_ids)
            if (url := self.mana_asset_url(color)) is not None
        }

    def ui_asset_url(self, asset_id: str | None) -> str | None:
        if not asset_id or asset_id not in self._ui_asset_ids:
            return None
        return self.asset_url(asset_id)

    def ui_asset_catalog(self) -> dict[str, str]:
        return {
            asset_id: url
            for asset_id in sorted(self._ui_asset_ids)
            if (url := self.ui_asset_url(asset_id)) is not None
        }

    def playmat_url(self, playmat_id: str | None) -> str | None:
        if not playmat_id or playmat_id not in self._playmat_asset_ids:
            return None
        return self.asset_url(playmat_id)

    def playmat_catalog(self) -> list[dict[str, object]]:
        return [dict(item) for item in self._playmat_catalog]

    def character_asset_url(self, character_id: str | None, kind: str = "official_image") -> str | None:
        if not character_id or not self._safe_asset_id(character_id) or not self._safe_asset_id(kind):
            return None
        asset_id = self._character_asset_id(character_id, kind)
        if asset_id not in self._character_asset_ids:
            return None
        return self.asset_url(asset_id)

    def resolve_audio_id(self, audio_id: str) -> Path | None:
        if not self._safe_asset_id(audio_id):
            return None
        path = self._audio_manifest.get(audio_id)
        if path is None or not self._is_under_root(path):
            return None
        return path

    def audio_url(self, audio_id: str | None) -> str | None:
        if not audio_id or not self._safe_asset_id(audio_id):
            return None
        if self.resolve_audio_id(audio_id) is None:
            return None
        return f"/audio/{quote(audio_id)}"

    def _safe_asset_id(self, asset_id: str) -> bool:
        return bool(asset_id) and "/" not in asset_id and "\\" not in asset_id and ".." not in asset_id

    def _character_asset_id(self, character_id: str, kind: str) -> str:
        return f"character:{character_id}:{kind}"

