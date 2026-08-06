from __future__ import annotations

import csv
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACK = "PC:02 CONTRACT"
CARDS_PATH = ROOT / "data" / "cards_bilingual_v4.tsv"
SEESAA_PATH = ROOT / "data" / "seesaa.tsv"
RECONCILIATION_PATH = ROOT / "data" / "pc02_image_reconciliation.tsv"
SOURCE_ASSET_ROOT = ROOT.parent / "asserts" / "ZENONZARD_CARDLIST"
ASSET_ROOT = ROOT / "asserts" / "ZENONZARD_CARDLIST"
TOKEN_IDS = (
    "colorless_04_04_00_00",
    "colorless_01_04_00_01",
    "colorless_03_04_00_00",
    "colorless_04_04_00_01",
    "colorless_05_04_00_00",
)


SEESAA_NAME_OVERRIDES = {
    "ツパ=チョカ": "ツパ＝チョカ",
    "「太陽公」ハトト=ラキア": "「太陽公」ハトト＝ラキア",
    "「暗黒騎士団隊長」イザーク": "「暗黒騎士団長」イザーク",
    "「暴竜」グラン=レックス": "「暴竜」グラン＝レックス",
    "R-A7 ラハルコフ": "R-A7ラハルコフ",
    "R-A4 ヴォーギン": "R-A4ヴォーギン",
    "エクス=キャノン": "エクス＝キャノン",
}


def _read_tsv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    if not path.exists():
        raise FileNotFoundError(path)
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        if reader.fieldnames is None:
            raise RuntimeError(f"TSV has no header: {path}")
        return list(reader.fieldnames), [dict(row) for row in reader]


def _write_tsv(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _asset_path(card: dict[str, str], root: Path) -> Path:
    color = (card.get("attribute") or card.get("color") or "").upper()
    if not color:
        raise RuntimeError(f"missing color for {card.get('image_id')}")
    return root / color / f"{card['image_id']}.png"


def main() -> None:
    card_fields, cards = _read_tsv(CARDS_PATH)
    _, seesaa_rows = _read_tsv(SEESAA_PATH)
    seesaa_by_name = {row["name_jp"].strip(): row for row in seesaa_rows if row.get("name_jp")}
    pack_rows = [row for row in cards if row.get("pack_jp_official") == PACK]
    if len(pack_rows) != 100 or len({row["image_id"] for row in pack_rows}) != 100:
        raise RuntimeError(f"PC02 source inventory mismatch: rows={len(pack_rows)}")

    reconciliation: list[dict[str, str]] = []
    for card in pack_rows:
        name = card.get("official_name_jp") or card.get("name_jp") or ""
        seesaa_name = SEESAA_NAME_OVERRIDES.get(name, name)
        source = seesaa_by_name.get(seesaa_name)
        if source is None:
            raise RuntimeError(f"no Seesaa face row for {card['image_id']} {name}")
        if card.get("card_type") in {"field_minion", "base_minion"}:
            if not source.get("bp") or not source.get("dp"):
                raise RuntimeError(f"missing BP/DP for {card['image_id']} {name}")
            card["bp"] = source["bp"].strip()
            card["dp"] = source["dp"].strip()
        else:
            card["bp"] = ""
            card["dp"] = ""
        if card.get("card_type") == "base_minion":
            card["cost"] = ""
        else:
            card["cost"] = source.get("cost", "").strip()
        if not card.get("ability_jp"):
            card["ability_jp"] = source.get("ability_jp", "").strip()
            card["ability_jp_source"] = "card_image+seesaa"
        if card.get("ability_jp") in {"（効果なし）", "(効果なし)"}:
            card["ability_jp"] = "効果なし"
        if not card.get("ability_jp"):
            raise RuntimeError(f"missing Japanese rule text for {card['image_id']} {name}")

        source_asset = _asset_path(card, SOURCE_ASSET_ROOT)
        target_asset = _asset_path(card, ASSET_ROOT)
        if not source_asset.exists():
            raise FileNotFoundError(source_asset)
        target_asset.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_asset, target_asset)
        reconciliation.append({
            "image_id": card["image_id"],
            "name_jp": name,
            "cost_image": source.get("cost", "").strip(),
            "bp_image": card["bp"],
            "dp_image": card["dp"],
            "ability_jp": card["ability_jp"],
            "image_path": target_asset.relative_to(ROOT).as_posix(),
            "secondary_source": f"data/seesaa.tsv::{seesaa_name}",
        })

    for token_id in TOKEN_IDS:
        source_asset = next(SOURCE_ASSET_ROOT.rglob(f"{token_id}.png"), None)
        if source_asset is None:
            raise FileNotFoundError(f"missing token image: {token_id}")
        target_asset = ASSET_ROOT / "tokens" / source_asset.name
        target_asset.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_asset, target_asset)

    _write_tsv(CARDS_PATH, card_fields, cards)
    _write_tsv(
        RECONCILIATION_PATH,
        ["image_id", "name_jp", "cost_image", "bp_image", "dp_image", "ability_jp", "image_path", "secondary_source"],
        reconciliation,
    )
    print(
        f"reconciled {len(reconciliation)} PC02 cards and copied "
        f"{len(reconciliation) + len(TOKEN_IDS)} images"
    )


if __name__ == "__main__":
    main()
