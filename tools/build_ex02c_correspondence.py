"""Build the explicit EX02/EX02C same-name correspondence from official rows."""
from __future__ import annotations

import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROMO_PAIRS = {
    "colorless_05_02_EX02_04": "colorless_05_02_cp_00",
    "colorless_06_02_EX02_01": "colorless_06_02_cp_00",
}
FIELDS = (
    "canonical_card_id", "variant_card_id", "ex02_name_jp", "ex02c_name_jp",
    "variant_pack", "card_type", "attribute", "total_cost", "colored_cost",
    "free_cost", "bp", "dp", "race_jp", "combined_copy_limit",
    "ex02_source_url", "ex02c_source_url", "equivalence_authority",
)


def build_correspondence(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    originals = {row["image_id"]: row for row in rows if row["pack_jp_official"] == "EX:02 幻影の剣士"}
    variants = {row["image_id"]: row for row in rows if row["pack_jp_official"] == "EXCODE:02C SAO"}
    by_id = {row["image_id"]: row for row in rows}
    expected = set(variants) | set(PROMO_PAIRS.values())
    if len(originals) != 70 or len(variants) != 68:
        raise ValueError(f"Unexpected official inventories: EX02={len(originals)}, EX02C={len(variants)}")
    result = []
    for card_id, original in sorted(originals.items(), key=lambda item: int(item[1]["official_order"])):
        variant_id = PROMO_PAIRS.get(card_id, card_id.replace("_EX02_", "_02c_"))
        if variant_id not in expected or variant_id not in by_id:
            raise ValueError(f"Missing confirmed counterpart: {card_id} -> {variant_id}")
        variant = by_id[variant_id]
        for key in ("card_type", "attribute", "cost", "colored_cost", "free_cost", "bp", "dp", "race_jp"):
            if original[key] != variant[key]:
                raise ValueError(f"Printed {key} differs for {card_id}/{variant_id}: {original[key]!r}/{variant[key]!r}")
        result.append(dict(zip(FIELDS, (
            card_id, variant_id, original["name_jp"], variant["name_jp"], variant["pack_jp_official"],
            original["card_type"], original["attribute"], original["cost"], original["colored_cost"],
            original["free_cost"], original["bp"], original["dp"], original["race_jp"], "3",
            original["official_image_url_jp"], variant["official_image_url_jp"],
            "user_confirmed_EX02_EX02C_same_name_2026-10-22",
        ))))
    ids = [row["variant_card_id"] for row in result]
    if len(ids) != len(set(ids)) or set(ids) != expected:
        raise ValueError("Correspondence must cover every variant exactly once")
    return result


def main() -> None:
    with (ROOT / "data/cards_bilingual_v4.tsv").open(encoding="utf-8-sig", newline="") as handle:
        pairs = build_correspondence(list(csv.DictReader(handle, delimiter="\t")))
    output = ROOT / "data/ex02_ex02c_equivalences.tsv"
    with output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, FIELDS, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(pairs)
    print(f"{output}: {len(pairs)} one-to-one same-name pairs (68 EX02C + 2 SAO campaign cards)")


if __name__ == "__main__":
    main()
