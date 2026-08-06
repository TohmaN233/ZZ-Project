from __future__ import annotations

from zz.ex01 import EX01_CARD_IDS
from zz.pc01 import PC01_CARD_IDS
from zz.pc01r import PC01R_CARD_IDS
from zz.pc02 import PC02_CARD_IDS


def test_published_card_pack_inventory_is_complete() -> None:
    assert len(EX01_CARD_IDS) == 12
    assert len(PC01_CARD_IDS) == 143
    assert len(PC01R_CARD_IDS) == 70
    assert len(PC02_CARD_IDS) == 100
    assert len(set(EX01_CARD_IDS + PC01_CARD_IDS + PC01R_CARD_IDS + PC02_CARD_IDS)) == 325
