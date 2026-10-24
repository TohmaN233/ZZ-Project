import csv
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools.build_ex02c_correspondence import build_correspondence
from zz.card_identity import explicitly_equivalent_card_ids
from zz.decks import deck_card_copy_identity
from zz.ex02c_cards.colorless_08_02_02c_00 import _is_sword_golem

ROOT = Path(__file__).resolve().parents[1]


def source_rows():
    with (ROOT / "data/cards_bilingual_v4.tsv").open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def test_correspondence_is_complete_unique_and_reproducible():
    expected = build_correspondence(source_rows())
    with (ROOT / "data/ex02_ex02c_equivalences.tsv").open(encoding="utf-8", newline="") as handle:
        assert list(csv.DictReader(handle, delimiter="\t")) == expected
    assert len(expected) == len({r["canonical_card_id"] for r in expected}) == len({r["variant_card_id"] for r in expected}) == 70
    assert sum(r["variant_pack"] == "CAMPAIGN" for r in expected) == 2
    assert all(r["combined_copy_limit"] == "3" for r in expected)


@pytest.mark.parametrize("field", ["race_jp", "card_type", "attribute", "cost", "colored_cost", "free_cost", "bp", "dp"])
def test_correspondence_rejects_printed_metadata_mismatch(field):
    rows = source_rows()
    row = next(r for r in rows if r["image_id"] == "colorless_05_02_cp_00")
    row[field] = "wrong"
    with pytest.raises(ValueError, match="differs"):
        build_correspondence(rows)


def test_correspondence_does_not_silently_omit_missing_campaign_partner():
    rows = [r for r in source_rows() if r["image_id"] != "colorless_06_02_cp_00"]
    with pytest.raises(ValueError, match="Missing confirmed counterpart"):
        build_correspondence(rows)


def test_explicit_reprint_pairs_share_deck_identity_without_name_matching():
    pairs = (
        ("colorless_08_02_EX02_00", "colorless_08_02_02c_00"),
        ("colorless_05_02_EX02_04", "colorless_05_02_cp_00"),
    )
    for canonical, variant in pairs:
        assert explicitly_equivalent_card_ids(canonical, variant)
        assert deck_card_copy_identity(canonical) == deck_card_copy_identity(variant)
    assert not explicitly_equivalent_card_ids(pairs[0][0], pairs[1][1])
    assert _is_sword_golem(SimpleNamespace(card=SimpleNamespace(id=pairs[0][0])))
    assert _is_sword_golem(SimpleNamespace(card=SimpleNamespace(id=pairs[0][1])))
    assert not _is_sword_golem(SimpleNamespace(card=SimpleNamespace(id=pairs[1][1])))
