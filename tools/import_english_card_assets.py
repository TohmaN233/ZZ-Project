from __future__ import annotations

import argparse
import csv
import json
import re
import shutil
import unicodedata
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CARD_COLORS = {"red", "yellow", "white", "green", "blue", "purple", "colorless"}

FORCE_IMAGES = {
    "Force of Fusion - Chimera": "force_kon",
    "Force of Insight - Chiron": "force_chi",
    "Force of Sin - Cyclops": "force_e",
    "Force of Triumph - Minotaur": "force_kai",
    "Force of Harmony - Orthrus": "force_so",
    "Force of Eternity - Ouroboros": "force_rin",
    "Force of Ascension - Pegasus": "force_sho",
    "Force of Rebirth - Phoenix": "force_so2",
    "Force of Temptation - Siren": "force_li",
    "Force of Sanctity - Sphynx": "force_sei",
}

MANA_IMAGES = {
    "COLORLESS": "Neutral Mana",
    "RED": "Red Mana",
    "YELLOW": "Yellow Mana",
    "WHITE": "White Mana",
    "GREEN": "Green Mana",
    "BLUE": "Blue Mana",
    "PURPLE": "Purple Mana",
}

# These rows had no English name in the merged Japanese/Chinese database. The
# mapping is explicit because there is no trustworthy textual key to infer it.
UNNAMED_CARD_IMAGES = {
    "colorless_03_01_EX04c_00": "Axela - Mask of Blue Flames",
    "blue_0_00_06_00": "Barl of the Ghost Fleet",
    "blue_7_02_06_00": "Blind Spot",
    "colorless_04_01_EX04c_00": "Byrt - Dragon Blaster",
    "blue_0_01_06_00": "Gran - Guardian of Poseido",
    "colorless_010_02_EX02_00": "Hex - The Saber God",
    "yellow_011_03_EX02_00": "Holy Judgment",
    "colorless_010_02_01_00": "Lord Alabaster - The Embattled",
    "colorless_010_02_02_00": "Lord Empyrean - The Celestial",
    "yellow_07_02_EX02_1": "Lucia - The Angelic Blade",
    "blue_010_03_02_00": "Maelstrom",
    "white_0_00_06_00": "Mercenary Operator",
    "white_0_01_06_00": "Piastre - Harmony Mercenaries Captain",
    "colorless_010_02_01r_00": "Qilin - Of the Five",
    "white_010_01_06_00": "Rosetta - Mecha Maid of Machinas",
    "colorless_010_01_06_00": "Shivarys - Ice Witch",
    "purple_0_01_06_00": "Symon - Horseman of Thanatos",
    "red_04_04_00_00": "Token Golem M",
    "colorless_07_01_EX04c_00": "Vulc01 - Rampaging Mode",
    "red_0_01_06_00": "Vyce - Twilight Sky Pirate Captain",
    "red_0_00_06_00": "Walke the Sky Pirate",
    "colorless_012_02_01_00": "Yggdrawalker - Bearer of Golden Fruit",
}

# The old merged database used generic placeholder names for this cycle. Color
# and the supplied English card faces establish the six exact identities.
DRAGON_SORCERESS_IMAGES = {
    "red_03_02_02_00": "Jain - Sorceress of Blazefires",
    "yellow_04_02_02_00": "Selika - Sorceress of Thunderstrikes",
    "white_03_02_02_01": "Matilda - Sorceress of Dreadfrosts",
    "green_03_02_02_01": "Chloe - Sorceress of Sunflares",
    "blue_03_02_02_00": "Sophia - Sorceress of Jawcrushers",
    "purple_04_02_02_00": "Francesca - Sorceress of Annihilators",
}


@dataclass(frozen=True)
class XmlCard:
    name: str
    text: str


def normalized_name(value: str) -> str:
    ascii_value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "", ascii_value.casefold().replace("?", "e"))


def name_tokens(value: str) -> list[str]:
    ascii_value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    return re.findall(r"[a-z0-9]+", ascii_value.casefold().replace("?", "e"))


def level_number(value: str) -> str | None:
    match = re.search(r"lv\.?\s*([123])", value.casefold())
    return match.group(1) if match else None


def alias_score(left: str, right: str) -> float:
    left_norm = normalized_name(left)
    right_norm = normalized_name(right)
    left_tokens = name_tokens(left)
    right_tokens = name_tokens(right)
    sequence = SequenceMatcher(None, left_norm, right_norm).ratio()
    union = set(left_tokens) | set(right_tokens)
    overlap = len(set(left_tokens) & set(right_tokens)) / max(1, len(union))
    score = max(sequence, 0.55 * sequence + 0.45 * overlap)
    if left_norm in right_norm or right_norm in left_norm:
        score += 0.35 * min(len(left_norm), len(right_norm)) / max(len(left_norm), len(right_norm))
    if left_tokens and right_tokens and left_tokens[0] == right_tokens[0]:
        score += 0.45
    left_level = level_number(left)
    right_level = level_number(right)
    if left_level or right_level:
        score += 0.35 if left_level == right_level else -0.6
    return score


def normalized_effect_text(value: str) -> str:
    lines = []
    for raw_line in value.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = re.sub(r"\s+", " ", raw_line).strip()
        if line:
            lines.append(line)
    return "\\n".join(lines)


def read_xml_cards(path: Path) -> dict[str, XmlCard]:
    root = ET.parse(path).getroot()
    cards: dict[str, XmlCard] = {}
    for node in root.findall("./cards/card"):
        name = (node.findtext("name") or "").strip()
        if not name:
            raise ValueError("db1.xml contains a card without a name")
        key = normalized_name(name)
        if key in cards:
            raise ValueError(f"duplicate normalized db1.xml card name: {name}")
        cards[key] = XmlCard(name=name, text=normalized_effect_text(node.findtext("text") or ""))
    return cards


def read_tsv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        rows = [dict(row) for row in reader]
        fieldnames = list(reader.fieldnames or [])
    if "image_id" not in fieldnames or "name_en" not in fieldnames or "ability_en" not in fieldnames:
        raise ValueError("cards_bilingual_v4.tsv is missing required English columns")
    return fieldnames, rows


def write_tsv(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def source_images(path: Path) -> dict[str, Path]:
    images: dict[str, Path] = {}
    for image in sorted(path.glob("*.png"), key=lambda item: item.name.casefold()):
        key = normalized_name(image.stem)
        if key in images:
            raise ValueError(f"duplicate normalized English image name: {image.stem}")
        images[key] = image
    return images


def bind_card_images(rows: list[dict[str, str]], images: dict[str, Path]) -> dict[str, Path]:
    rows_by_id = {row["image_id"]: row for row in rows}
    force_keys = {normalized_name(name) for name in FORCE_IMAGES}
    available = {key: image for key, image in images.items() if key not in force_keys}
    bindings: dict[str, Path] = {}

    for row in rows:
        name = (row.get("name_en") or "").strip()
        key = normalized_name(name) if name else ""
        if key and key in available:
            bindings[row["image_id"]] = available.pop(key)

    for card_id, image_name in DRAGON_SORCERESS_IMAGES.items():
        if card_id not in rows_by_id:
            raise ValueError(f"missing Dragon Sorceress row: {card_id}")
        if card_id in bindings:
            continue
        image = available.pop(normalized_name(image_name), None)
        if image is None:
            raise ValueError(f"missing Dragon Sorceress image: {image_name}")
        bindings[card_id] = image

    unmatched_rows = {
        row["image_id"]: row
        for row in rows
        if row.get("name_en") and row["image_id"] not in bindings
    }
    while unmatched_rows:
        candidates = [
            (alias_score(row["name_en"], image.stem), card_id, key)
            for card_id, row in unmatched_rows.items()
            for key, image in available.items()
        ]
        if not candidates:
            raise ValueError("not enough English images to bind all named database rows")
        score, card_id, key = max(candidates)
        if score < 0.70:
            raise ValueError(
                f"low-confidence English image alias for {card_id}: "
                f"{unmatched_rows[card_id]['name_en']} -> {available[key].stem} ({score:.3f})"
            )
        bindings[card_id] = available.pop(key)
        unmatched_rows.pop(card_id)

    for card_id, image_name in UNNAMED_CARD_IMAGES.items():
        row = rows_by_id.get(card_id)
        if row is None:
            raise ValueError(f"missing unnamed English card row: {card_id}")
        if card_id in bindings:
            continue
        image = available.pop(normalized_name(image_name), None)
        if image is None:
            raise ValueError(f"missing unnamed English card image: {image_name}")
        bindings[card_id] = image

    if available:
        names = ", ".join(sorted(image.stem for image in available.values()))
        raise ValueError(f"unmapped English card images: {names}")
    if len(bindings) != 1297:
        raise ValueError(f"expected 1297 English card bindings, found {len(bindings)}")
    return bindings


def update_english_text(
    rows: list[dict[str, str]],
    bindings: dict[str, Path],
    xml_cards: dict[str, XmlCard],
    *,
    verify_only: bool,
) -> None:
    rows_by_id = {row["image_id"]: row for row in rows}
    mismatches: list[str] = []
    for card_id, image in bindings.items():
        xml_card = xml_cards.get(normalized_name(image.stem))
        if xml_card is None:
            raise ValueError(f"db1.xml has no text entry for {image.stem}")
        row = rows_by_id[card_id]
        if verify_only and (
            row.get("name_en") != xml_card.name or row.get("ability_en") != xml_card.text
        ):
            mismatches.append(card_id)
        row["name_en"] = xml_card.name
        row["ability_en"] = xml_card.text
    if mismatches:
        sample = ", ".join(mismatches[:10])
        raise ValueError(
            f"English TSV text is not synchronized for {len(mismatches)} cards: {sample}"
        )


def copy_outputs(
    output_root: Path,
    bindings: dict[str, Path],
    rows: list[dict[str, str]],
    images: dict[str, Path],
    mana_root: Path,
) -> dict[str, object]:
    rows_by_id = {row["image_id"]: row for row in rows}
    temp_root = output_root.with_name(f"{output_root.name}.build")
    if temp_root.exists():
        shutil.rmtree(temp_root)
    temp_root.mkdir(parents=True)

    card_manifest: dict[str, str] = {}
    source_names: dict[str, str] = {}
    for card_id, source in sorted(bindings.items()):
        color = rows_by_id[card_id].get("color", "").split("|")[0].lower()
        if color not in CARD_COLORS:
            raise ValueError(f"unsupported English card color for {card_id}: {color}")
        relative = Path(color.upper()) / f"{card_id}.png"
        destination = temp_root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        card_manifest[card_id] = relative.as_posix()
        source_names[card_id] = source.stem

    force_manifest: dict[str, str] = {}
    for name, force_id in FORCE_IMAGES.items():
        source = images.get(normalized_name(name))
        if source is None:
            raise ValueError(f"missing English Force image: {name}")
        relative = Path("FORCE") / f"{force_id}.png"
        destination = temp_root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        force_manifest[force_id] = relative.as_posix()

    mana_manifest: dict[str, str] = {}
    for color, source_name in MANA_IMAGES.items():
        source = mana_root / f"{source_name}.png"
        if not source.is_file():
            raise ValueError(f"missing Mana image: {source}")
        relative = Path("MANA") / f"{color}.png"
        destination = temp_root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        mana_manifest[color] = relative.as_posix()

    manifest: dict[str, object] = {
        "schemaVersion": 1,
        "generatedBy": "tools/import_english_card_assets.py",
        "cards": card_manifest,
        "forces": force_manifest,
        "mana": mana_manifest,
        "sourceNames": source_names,
    }
    (temp_root / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    if output_root.exists():
        manifest_path = output_root / "manifest.json"
        if not manifest_path.is_file():
            raise ValueError(f"refusing to replace unowned output directory: {output_root}")
        existing = json.loads(manifest_path.read_text(encoding="utf-8"))
        if existing.get("generatedBy") != "tools/import_english_card_assets.py":
            raise ValueError(f"refusing to replace unowned output directory: {output_root}")
        shutil.rmtree(output_root)
    temp_root.replace(output_root)
    return manifest


def run(project_root: Path, *, check_only: bool) -> dict[str, int]:
    source_root = project_root / "asserts" / "card images"
    xml_path = project_root / "asserts" / "db1.xml"
    tsv_path = project_root / "data" / "cards_bilingual_v4.tsv"
    mana_root = project_root / "asserts" / "ZENONZARD_CARDLIST" / "MANA"
    output_root = project_root / "asserts" / "Eng-cards"

    xml_cards = read_xml_cards(xml_path)
    fieldnames, rows = read_tsv(tsv_path)
    images = source_images(source_root)
    bindings = bind_card_images(rows, images)
    update_english_text(rows, bindings, xml_cards, verify_only=check_only)

    expected_xml_names = {
        normalized_name(image.stem) for image in images.values()
    } | {normalized_name(name) for name in MANA_IMAGES.values()}
    if set(xml_cards) != expected_xml_names:
        missing = sorted(xml_cards.keys() - expected_xml_names)
        extra = sorted(expected_xml_names - xml_cards.keys())
        raise ValueError(f"db1.xml/image inventory mismatch: missing={missing}, extra={extra}")

    if not check_only:
        copy_outputs(output_root, bindings, rows, images, mana_root)
        write_tsv(tsv_path, fieldnames, rows)

    return {
        "xmlEntries": len(xml_cards),
        "cardImages": len(bindings),
        "forceImages": len(FORCE_IMAGES),
        "manaImages": len(MANA_IMAGES),
        "englishTextRows": len(bindings),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Import community English Zenonzard cards and text.")
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--check", action="store_true", help="validate the full mapping without writing files")
    args = parser.parse_args()
    report = run(args.project_root.resolve(), check_only=args.check)
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
