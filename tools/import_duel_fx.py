"""Import a small, dependency-complete selection from the user's Effekseer pack.

The original SKFE bytes are never patched. Fail on missing model/material/texture
dependencies, even when files.json claims the export was complete.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import shutil
import struct
from pathlib import Path


def resources(path: Path) -> dict[str, list[str]]:
    data = path.read_bytes()
    if data[:4] != b"SKFE":
        raise ValueError(f"Not a runtime SKFE file: {path}")
    version = struct.unpack_from("<i", data, 4)[0]
    if version not in {1500, 1610, 1710}:
        raise ValueError(f"Unsupported resource table version {version}: {path}")
    offset = 8
    result = {}
    for kind in ("texture", "normal", "distortion", "sound", "model", "material"):
        count = struct.unpack_from("<i", data, offset)[0]
        offset += 4
        if not 0 <= count <= 1000:
            raise ValueError(f"Invalid {kind} resource count: {path}")
        paths = []
        for _ in range(count):
            size = struct.unpack_from("<i", data, offset)[0]
            offset += 4
            if not 0 < size < 4096 or offset + size * 2 > len(data):
                raise ValueError(f"Invalid {kind} path length: {path}")
            paths.append(data[offset:offset + size * 2].decode("utf-16-le").rstrip("\0").replace("\\", "/"))
            offset += size * 2
        result[kind] = paths
    return result


# Each color uses different native emitter geometry, not just a tint.
# Values are (original asset, screen scale, playback speed).
SELECTION = {
    "attack-fire": ("eff_011", 42, 2.4),
    "attack-ice": ("eff_122", 40, 2.8),
    "attack-lightning": ("eff_041", 40, 2.8),
    "attack-wind": ("eff_161", 46, 2.6),
    "attack-dark": ("eff_052", 40, 2.4),
    "attack-light": ("eff_806", 180, 1.6),
    "hit": ("eff_431", 33, 2.0),
    "force-hit": ("eff_806", 150, 1.8),
    "heal": ("eff_796", 58, 2.0),
    "activate": ("eff_051", 34, 2.4),
    "target": ("eff_121", 36, 2.0),
    "victory": ("eff_041", 65, 1.5),
}

VARIANTS = {
    "block": {
        "red": ("eff_511", 52, 2.6), "blue": ("eff_512", 52, 2.8),
        "yellow": ("eff_042", 26, 3.2), "green": ("eff_161", 40, 2.8),
        "purple": ("eff_052", 42, 3.0), "white": ("eff_1304", 46, 2.8),
        "colorless": ("eff_051", 40, 2.6),
    },
    "destroy": {
        "red": ("eff_012", 37, 3.2), "blue": ("eff_122", 49, 3.0),
        "yellow": ("eff_043", 29, 3.0), "green": ("eff_013", 40, 2.6),
        "purple": ("eff_513", 56, 1.8), "white": ("eff_807", 4, 2.8),
        "colorless": ("eff_101", 52, 1.2),
    },
    "summon": {
        "red": ("eff_013", 29, 3.2), "blue": ("eff_512", 39, 3.2),
        "yellow": ("eff_041", 26, 3.0), "green": ("eff_161", 34, 3.0),
        "purple": ("eff_052", 37, 3.2), "white": ("eff_1304", 38, 2.8),
        "colorless": ("eff_051", 34, 2.8),
    },
    "mana": {color: ("eff_1304", 24, 3.0) for color in
             ("red", "blue", "yellow", "green", "purple", "white", "colorless")},
}
for event, variants in VARIANTS.items():
    SELECTION.update({f"{event}-{color}": row for color, row in variants.items()})

# Native setAllColor multiplies the export's green channels; it cannot turn a
# green bolt blue. Grade the single active event's RGB in an offscreen GPU pass.
COLOR_FILTERS = {
    "attack-ice": "grayscale(1) sepia(1) saturate(6) hue-rotate(160deg)",
    "attack-lightning": "grayscale(1) sepia(1) saturate(6)",
    "attack-dark": "grayscale(1) sepia(1) saturate(6) hue-rotate(225deg)",
    "attack-light": "grayscale(1) brightness(1.3)",
    "hit": "grayscale(1) sepia(1) saturate(3) hue-rotate(325deg)",
    "force-hit": "grayscale(1) brightness(1.15)",
    "activate": "grayscale(1) sepia(1) saturate(5)",
    "target": "grayscale(1) sepia(1) saturate(5) hue-rotate(135deg)",
    "victory": "grayscale(1) sepia(1) saturate(5)",
}
PALETTE_FILTERS = {
    "red": "grayscale(1) sepia(1) saturate(5) hue-rotate(325deg)",
    "blue": "grayscale(1) sepia(1) saturate(5) hue-rotate(160deg)",
    "yellow": "grayscale(1) sepia(1) saturate(5)",
    "green": "none", "purple": "grayscale(1) sepia(1) saturate(5) hue-rotate(225deg)",
    "white": "grayscale(1) brightness(1.2)", "colorless": "grayscale(1)",
}
for event, variants in VARIANTS.items():
    for color in variants:
        COLOR_FILTERS[f"{event}-{color}"] = PALETTE_FILTERS[color]
# Preserve the authored fire colors; green placement needs a green light plane.
for name in ("destroy-red", "summon-red"):
    COLOR_FILTERS.pop(name)
COLOR_FILTERS["mana-green"] = "grayscale(1) sepia(1) saturate(4) hue-rotate(65deg)"
COLOR_FILTERS["destroy-green"] = "grayscale(1) sepia(1) saturate(4) hue-rotate(65deg)"


def color_matrix(grade: str) -> list[float]:
    """One linear RGB grade; retain native alpha and additive RGB above alpha."""
    result = [[1., 0., 0.], [0., 1., 0.], [0., 0., 1.]]
    for name, raw in re.findall(r"([a-z-]+)\(([^)]+)\)", grade):
        value = float(raw.removesuffix("deg"))
        if name in {"grayscale", "saturate"}:
            saturation = 1 - value if name == "grayscale" else value
            weights = (.2126, .7152, .0722)
            matrix = [[weights[col] * (1 - saturation) + (saturation if row == col else 0)
                       for col in range(3)] for row in range(3)]
        elif name == "sepia":
            sepia = ((.393, .769, .189), (.349, .686, .168), (.272, .534, .131))
            matrix = [[sepia[row][col] * value + (1 - value if row == col else 0)
                       for col in range(3)] for row in range(3)]
        elif name == "brightness":
            matrix = [[value if row == col else 0 for col in range(3)] for row in range(3)]
        elif name == "hue-rotate":
            c, s = math.cos(math.radians(value)), math.sin(math.radians(value))
            matrix = [[.213 + .787*c - .213*s, .715 - .715*c - .715*s, .072 - .072*c + .928*s],
                      [.213 - .213*c + .143*s, .715 + .285*c + .140*s, .072 - .072*c - .283*s],
                      [.213 - .213*c - .787*s, .715 - .715*c + .715*s, .072 + .928*c + .072*s]]
        else:
            raise ValueError(f"Unsupported FX grade: {name}")
        result = [[sum(matrix[row][k] * result[k][col] for k in range(3))
                   for col in range(3)] for row in range(3)]
    if grade != "none" and not re.fullmatch(r"(?:[a-z-]+\([\d.]+(?:deg)?\)\s*)+", grade):
        raise ValueError(f"Invalid FX grade: {grade}")
    return [round(result[row][col], 7) for col in range(3) for row in range(3)]


def import_assets(source: Path, destination: Path) -> dict:
    destination.mkdir(parents=True, exist_ok=True)
    files: dict[str, str] = {}
    imported = {}
    for asset in sorted({row[0] for row in SELECTION.values()}):
        candidates = sorted(source.rglob(f"{asset}.efkefc"))
        if not candidates or len({p.read_bytes() for p in candidates}) != 1:
            raise ValueError(f"Missing or ambiguous asset: {asset}")
        original = candidates[0]
        refs = resources(original)
        if any(refs[kind] for kind in ("sound", "model", "material")):
            raise ValueError(f"Selection requires unexported resources: {original}")
        mapping = {}
        for ref in set(refs["texture"] + refs["normal"] + refs["distortion"]):
            texture = original.parent / "textures" / Path(ref).name
            if not texture.is_file():
                raise FileNotFoundError(f"{original}: missing {ref}")
            digest = hashlib.sha256(texture.read_bytes()).hexdigest()
            target = f"texture-{digest[:20]}.png"
            shutil.copyfile(texture, destination / target)
            mapping[ref] = target
            files[target] = digest
        name = f"{asset}.efkefc"
        shutil.copyfile(original, destination / name)
        files[name] = hashlib.sha256(original.read_bytes()).hexdigest()
        imported[asset] = {"file": name, "resources": dict(sorted(mapping.items())),
                           "source": original.relative_to(source).as_posix()}
    manifest = {"version": 1, "sourceGame": "Battle Spirits Crossover", "runtimeVersion": "1.80.7",
                "effects": {}, "files": dict(sorted(files.items()))}
    for semantic, (asset, scale, speed) in SELECTION.items():
        manifest["effects"][semantic] = {**imported[asset], "scale": scale, "speed": speed}
        if asset not in {"eff_011", "eff_012", "eff_013", "eff_041", "eff_042", "eff_043", "eff_806", "eff_807"}:
            manifest["effects"][semantic]["rotationX"] = 1.5707963267948966
        if semantic in COLOR_FILTERS:
            manifest["effects"][semantic]["colorMatrix"] = color_matrix(COLOR_FILTERS[semantic])
        if semantic in {"hit", "force-hit"}:
            manifest["effects"][semantic]["durationMs"] = 340
    for name in ("effekseer.min.js", "effekseer.wasm", "effekseer-LICENSE.txt"):
        runtime_file = destination / name
        if not runtime_file.is_file():
            raise FileNotFoundError(f"Install the pinned Effekseer 1.80.7 runtime first: {runtime_file}")
        manifest["files"][name] = hashlib.sha256(runtime_file.read_bytes()).hexdigest()
    (destination / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    manifest = import_assets(args.source, args.destination)
    print(f"Imported {len(manifest['files'])} files for {len(manifest['effects'])} semantic mappings")
