from __future__ import annotations

import ast
import hashlib
import json
import re
import shutil
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

ROOT_FILES = (
    "README.md", "README.en.md", "README.ja.md", "INSTALL.md",
    "RELEASE_NOTES.md", "THIRD_PARTY_NOTICES.md", "PUBLIC_RELEASE_MANIFEST.json",
    "ASSET_PACK_MANIFEST.json", "pyproject.toml", "requirements-runtime.txt",
)
DEPLOY_FILES = (
    "deploy/zz-multiplayer.env.example", "deploy/nginx/zz-multiplayer.conf",
    "deploy/systemd/zz-multiplayer.service", "docs/multiplayer/vm-deployment.md",
    "docs/ONLINE.md", "docs/multiplayer/network-diagnostics.md",
)
TRANSLATIONS = ("GLOSSARY.json", "zz_card_pool_zh.tsv", "zz_force_pool_zh.tsv")
RULEBOOKS = ("zz_rulebook_zh.md", "zz_rulebook_en.md", "zz_rulebook_ja.md")
PACKAGING_FILES = (
    "build_linux_bundle.py", "build_source_package.py", "build_windows_package.py",
    "release_files.py", "runtime_model_export.py", "zz_server_entry.py",
    "build_network_diagnostic.py",
)
SOURCE_TOOLS = (
    "__init__.py", "run_semantic_scenario.py", "card_translation_exchange.py",
    "import_duel_fx.py",
    "build_ex02c_correspondence.py",
    "normalize_japanese_card_text.py", "hidden_multiprocessing_spawn.py",
    "multiplayer_external_smoke.py", "multiplayer_soak.py",
    "multiplayer_network_diagnostic.py",
)
SERVER_ZZ_MODULES = (
    "__init__", "ai", "basic", "cards", "codeman_memory", "deckcode0", "decks",
    "card_identity", "effects", "engine", "enums", "ex01", "ex02", "ex02c", "forces",
    "house_rules", "keyword_rules", "model", "pc01", "pc01r", "pc02", "pc02r",
    "transformations", "triggers",
)
SERVER_WEB_MODULES = (
    "__init__", "assets", "localization", "profiles", "serialize", "session",
    "settings_store",
)
DEEP_SOURCE_RELATIVE = Path("data/ai_training/deep_p2_specialist_v1_latest/best_greedy.pt")
DEEP_RUNTIME_RELATIVE = DEEP_SOURCE_RELATIVE.with_name("best_greedy.runtime.npz")
NORMAL_MODEL_RELATIVE = Path("data/ai_training/quality_tactical_latest/best_league.json")
FORBIDDEN_PARTS = {
    ".git", ".agents", ".codex", ".codegraph", ".pytest_cache", "__pycache__",
    "node_modules", "asserts", "dist", "project_memory", "public_release_work",
    "local_ai_training", "codeman_ai", "ai_challenges",
}


def release_version(root: Path) -> str:
    version = json.loads((root / "package.json").read_text(encoding="utf-8"))["version"]
    if not isinstance(version, str) or not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise ValueError(f"Invalid release version: {version!r}")
    return version


def pc02r_module_names(root: Path) -> tuple[str, ...]:
    tree = ast.parse((root / "zz/pc02r.py").read_text(encoding="utf-8"))
    declaration = next(
        node.value for node in tree.body if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "_MODULES" for target in node.targets)
    )
    names = tuple(module.removeprefix("zz.pc02r_cards.") for _, module in ast.literal_eval(declaration))
    if len(names) != 106 or len(set(names)) != 106:
        raise ValueError(f"Expected 106 distinct PC:02R card modules, got {len(names)}")
    if any(not re.fullmatch(r"[a-z]+_[0-9_]+r_[0-9]+", name) for name in names):
        raise ValueError("Invalid PC:02R release module name")
    return names


def ex02c_module_names(root: Path) -> tuple[str, ...]:
    tree = ast.parse((root / "zz/ex02c.py").read_text(encoding="utf-8"))
    declaration = next(
        node.value for node in tree.body if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "_MODULES" for target in node.targets)
    )
    modules = tuple(module.removeprefix("zz.ex02c_cards.") for _, module in ast.literal_eval(declaration))
    if len(modules) != 70 or len(modules) != len(set(modules)):
        raise ValueError(f"Expected distinct EX02C card modules, got {len(modules)}")
    if any(not name.isidentifier() for name in modules):
        raise ValueError("Invalid EX02C release module name")
    return modules


def release_files(root: Path, kind: str) -> list[Path]:
    if kind not in {"linux", "source", "multiplayer"}:
        raise ValueError(f"Unknown release package kind: {kind!r}")
    server = kind == "multiplayer"
    paths = {Path(name) for name in ROOT_FILES + DEPLOY_FILES}
    paths.update(Path("zz") / f"{name}.py" for name in (SERVER_ZZ_MODULES if server else ZZ_MODULES))
    paths.update(Path("zz/web") / f"{name}.py" for name in (SERVER_WEB_MODULES if server else WEB_MODULES))
    paths.update(Path("zz/multiplayer") / f"{name}.py" for name in MULTIPLAYER_MODULES)
    paths.update(Path("zz/pc02r_cards") / f"{name}.py" for name in ("__init__", *pc02r_module_names(root)))
    paths.update(Path("zz/ex02c_cards") / f"{name}.py" for name in ("__init__", *ex02c_module_names(root)))
    paths.update(Path("zz/web/translations") / name for name in TRANSLATIONS)
    paths.update(Path("data") / name for name in PUBLIC_TSVS)
    paths.update(Path("docs/rules") / name for name in RULEBOOKS)
    paths.update((Path("zz/pc02r_data.tsv"), Path("zz/ex02c_data.tsv"), Path("zz/multiplayer/compatibility.json")))
    if not server:
        paths.update(Path(name) for name in ("image.png", "launch-electron.sh", "launch-electron.cmd", "package.json", "package-lock.json", "docs/index.html"))
        paths.update(Path("electron") / name for name in ELECTRON_FILES)
        paths.update(Path("zz/web/static") / name for name in STATIC_FILES)
        paths.update(duel_fx_files(root))
        paths.update(Path("docs/assets") / name for name in SITE_ASSETS)
        paths.update(Path("data/decks") / name for name in DEFAULT_DECKS)
        paths.add(NORMAL_MODEL_RELATIVE)
    if kind == "source":
        paths.add(Path("docs/DUEL_FX.md"))
        paths.update(Path(name) for name in ("CONTRIBUTING.md", "smoke_clean_release.py", "ai_training/__init__.py", "ai_training/codeman_training.py", "build/installer.nsh"))
        paths.update(Path("packaging") / name for name in PACKAGING_FILES)
        paths.update(Path("tools") / name for name in SOURCE_TOOLS)
        paths.update(Path("tests") / name for name in (*FOCUSED_TESTS, "test_release_archive_inventory.py"))
        paths.add(Path("tests/test_ex02c_cards.py"))
        paths.add(Path("tests/test_ex02_cards.py"))
        paths.update(Path("tests") / name for name in ("test_frontend_duel_dom.py", "test_frontend_fx.py", "test_frontend_fx_arrival.py"))
        paths.update(Path("tests") / name for name in (
            "test_effect_resolution_order_oct29.py", "test_eugeo_reactive_shield_combat.py",
            "test_ex02c_link_activation_combat.py", "test_ex02c_standby_deadline.py",
            "test_frontend_magic_prompt.py", "test_frontend_oct29_feedback.py",
            "test_oct29_magic_engine.py", "test_oct29_phase_continuation.py",
            "test_oct29_shared_rules.py", "test_oct29_switch_mana.py",
        ))
        paths.update(Path("tests/semantic_scenarios/pc02r") / f"{name}-{case}.json" for name in pc02r_module_names(root) for case in ("positive", "boundary"))
        paths.update(Path("tests/semantic_scenarios/ex02c") / f"{name}-{case}.json" for name in ex02c_module_names(root) for case in ("positive", "boundary"))
        paths.add(Path("tests/semantic_scenarios/ex02c/green_08_02_02c_01-trash-boundary.json"))
        paths.add(DEEP_SOURCE_RELATIVE)
    files = sorted(paths, key=lambda path: path.as_posix())
    for relative in files:
        if relative.is_absolute() or ".." in relative.parts or FORBIDDEN_PARTS.intersection(relative.parts):
            raise ValueError(f"Forbidden release path: {relative}")
        source = root / relative
        if not source.is_file():
            raise FileNotFoundError(f"Required {kind} release file is missing: {source}")
        if source.is_symlink() or not source.resolve().is_relative_to(root.resolve()):
            raise ValueError(f"Release file escapes workspace: {source}")
    return files


def duel_fx_files(root: Path) -> list[Path]:
    """Use the declared inventory, never sweep a local effect/export directory."""
    directory = Path("zz/web/static/fx")
    manifest = json.loads((root / directory / "manifest.json").read_text(encoding="utf-8"))
    declared = manifest["files"]
    required = {"effekseer.min.js", "effekseer.wasm", "effekseer-LICENSE.txt"}
    if not required.issubset(declared):
        raise ValueError("Duel FX manifest must include the pinned runtime and license")
    result = [directory / "manifest.json"]
    for name, expected in declared.items():
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", name):
            raise ValueError(f"Invalid duel FX asset path: {name}")
        source = root / directory / name
        if sha256(source) != expected:
            raise ValueError(f"Duel FX asset checksum mismatch: {source}")
        result.append(directory / name)
    return result


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def copy_release_tree(root: Path, destination: Path, files: list[Path]) -> None:
    for relative in files:
        source = root / relative
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        before = sha256(source)
        shutil.copy2(source, target)
        if sha256(target) != before or sha256(source) != before:
            raise RuntimeError(f"Release input changed while copying: {relative}")


def prepare_embedded_manifest(destination: Path) -> None:
    path = destination / "PUBLIC_RELEASE_MANIFEST.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    for key in ("windowsInstaller", "linuxBundle", "sourcePackage", "multiplayerServer"):
        artifact = manifest.get(key)
        if artifact is not None:
            if not isinstance(artifact, dict) or not isinstance(artifact.get("filename"), str):
                raise ValueError(f"Invalid release artifact manifest: {key}")
            artifact.pop("bytes", None)
            artifact.pop("sha256", None)
    manifest["artifactIntegrity"] = {
        "checksumFile": "SHA256SUMS-PC02.txt",
        "location": "alongside the distributed release archives",
    }
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


@contextmanager
def release_staging(root: Path, kind: str) -> Iterator[tuple[Path, Path, str]]:
    root = root.resolve()
    version = release_version(root)
    output = root / "dist/releases" / f"v{version}"
    if not output.resolve().is_relative_to(root):
        raise ValueError(f"Release output escapes workspace: {output}")
    output.mkdir(parents=True, exist_ok=True)
    # TemporaryDirectory owns only this unique, verified child. Existing version
    # artifacts and other builders' staging directories are never removed.
    with tempfile.TemporaryDirectory(prefix=f".{kind}-stage-", dir=output) as temporary:
        yield Path(temporary), output, version


def archive_filter(info):
    info.mode = 0o755 if info.isdir() or info.name.endswith("/launch-electron.sh") else 0o644
    info.uid = info.gid = 0
    info.uname = info.gname = ""
    return info

# Exact product allowlists are independent of Git tracking status. New runtime
# surfaces require an explicit release-contract change instead of broad copying.
ZZ_MODULES = ('__init__', 'action_q_residual_critic', 'action_records', 'action_set_dataset', 'action_set_listwise_model', 'action_set_model', 'action_set_runtime_scores', 'action_set_scoring_contracts', 'action_set_teacher_rebuild', 'action_set_training', 'action_set_ygo_policy', 'action_value_group_key', 'action_value_row_refresh', 'ai', 'ai_deck_analysis', 'ai_league', 'ai_registry', 'ai_runtime_stack', 'basic', 'batched_eval_profile', 'card_identity', 'card_profiles', 'card_slot_refs', 'cards', 'codeman_memory', 'codeman_replay_correction', 'codeman_semantic_audit', 'codeman_training', 'counterfactual_transition', 'current_policy_actor_contract', 'current_policy_runtime', 'deck_ai', 'deck_profiles', 'deckcode0', 'decks', 'deep_rl', 'deep_runtime', 'deep_v2_understanding', 'effects', 'engine', 'enums', 'ex01', 'ex02', 'ex02c', 'forces', 'greedy_ai', 'house_rules', 'keyword_rules', 'model', 'pc01', 'pc01r', 'pc02', 'pc02r', 'player_correction_model', 'policy_factories', 'rl_action_vocab', 'rl_ai', 'rl_tensor_schema', 'rl_training', 'rollout_store', 'rollout_task_specs', 'runtime_aux_compose', 'runtime_profile', 'sim', 'trace_counterfactual_transition', 'training_fast_path', 'transformations', 'triggers', 'turn_planner', 'ygo_failed_direct_guard', 'ygo_vector_actor_rollout')

WEB_MODULES = ('__init__', 'assets', 'catalog', 'debug_tools', 'deck_store', 'filter_localization', 'localization', 'profiles', 'serialize', 'server', 'session', 'settings_store')

MULTIPLAYER_MODULES = ('__init__', 'actions', 'client', 'compatibility', 'controllers', 'deployment', 'deployment_server', 'hashing', 'match', 'observability', 'protocol', 'rooms', 'service', 'transport', 'views', 'websocket_server')

ELECTRON_FILES = ('adaptive-websocket.js', 'asset-bootstrap.js', 'asset-setup-preload.js', 'asset-setup-renderer.js', 'asset-setup.css', 'asset-setup.html', 'asset-setup.js', 'asset-source.json', 'icon-256.png', 'icon.png', 'lan-manager.js', 'main.js', 'multiplayer-client.js', 'preload.js', 'README.md', 'update-checker.js')

STATIC_FILES = ('api-client.js', 'app.js', 'duel-dom.js', 'duel-layout.js', 'duel.html', 'duel.js', 'fx-core.js', 'fx.css', 'index.html', 'multiplayer-card-policy.js', 'styles.css')

PUBLIC_TSVS = ('base_minion_face_verified.tsv', 'card_ability_face_verified.tsv', 'card_cost_face_verified.tsv', 'card_cost_pips.tsv', 'card_cost_text_verified.tsv', 'card_stat_face_verified.tsv', 'card_transformations.tsv', 'cards_bilingual_v4.tsv', 'ex02_ex02c_equivalences.tsv', 'forces.tsv', 'official_card_search.tsv', 'official_cardlist.tsv', 'official_filters.tsv', 'pc01r_image_reconciliation.tsv', 'pc02_image_reconciliation.tsv', 'seesaa.tsv')

DEFAULT_DECKS = ('aice.json', 'deck-060837.json', 'deck-b70677.json', 'deck-c80751.json', 'deck-e83cf0.json', 'deck-f9b075.json', 'deck.json', 'h.json')

FOCUSED_TESTS = ('electron_renderer_logging.test.js', 'test_multiplayer_network_diagnostic.py', 'electron_adaptive_websocket.test.js', 'electron_asset_bootstrap.test.js', 'electron_asset_setup.test.js', 'electron_asset_transport.test.js', 'electron_lan_manager.test.js', 'electron_multiplayer_client.test.js', 'electron_update_checker.test.js', 'frontend_multiplayer_card_policy.test.js', 'test_ai_vs_ai_mode.py', 'test_base_replacement_interface.py', 'test_card_japanese_text_integrity.py', 'test_card_pack_release.py', 'test_card_translation_exchange.py', 'test_clean_release_assets.py', 'test_codeman_replay_correction_vfx.py', 'test_cyclops_force.py', 'test_deck_reprint_limits.py', 'test_developer_mode_security.py', 'test_duel_scale_settings.py', 'test_duel_visual_timing.py', 'test_effect_target_contracts.py', 'test_electron_multiplayer_bridge.py', 'test_electron_multiplayer_cross_runtime.py', 'test_electron_shutdown.py', 'test_ex02c_correspondence.py', 'test_ex02c_shared_runtime.py', 'test_english_card_assets.py', 'test_force_base_replacement.py', 'test_forces.py', 'test_frontend_atomic_zone_transitions.py', 'test_frontend_deck_and_hand.py', 'test_frontend_duel_status.py', 'test_frontend_duel_layout.py', 'test_frontend_online_opening.py', 'test_frontend_rulebook.py', 'test_frontend_transformation_browser.py', 'test_frontend_visual_settle.py', 'test_game_session_choice_validation.py', 'test_localization_consistency.py', 'test_mana_asset_catalog.py', 'test_match_scoped_ids.py', 'test_multiplayer_client_transport.py', 'test_multiplayer_compatibility.py', 'test_multiplayer_deployment.py', 'test_multiplayer_deployment_artifacts.py', 'test_multiplayer_determinism.py', 'test_multiplayer_hidden_information.py', 'test_multiplayer_in_memory.py', 'test_multiplayer_invalid_actions.py', 'test_multiplayer_observability.py', 'test_multiplayer_protocol.py', 'test_multiplayer_reconnect.py', 'test_multiplayer_rematch_rps.py', 'test_multiplayer_room_queue.py', 'test_multiplayer_rooms.py', 'test_multiplayer_soak.py', 'test_multiplayer_websocket_integration.py', 'test_multiplayer_websocket_transport.py', 'test_pc02r_cards.py', 'test_pc02r_choice_feedback.py', 'test_pc02r_persistent_effects.py', 'test_pc02r_rule_corrections.py', 'test_pc02r_shared_runtime.py', 'test_public_base_rules.py', 'test_release_packaging_contract.py', 'test_shared_event_lifecycle.py', 'test_transformed_card_catalog.py')

SITE_ASSETS = ('battle.webp', 'codemen.webp', 'home.webp', 'lobby.webp', 'site.css', 'site.js', 'zzicon.webp')

