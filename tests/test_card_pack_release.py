from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest

from zz.ex01 import EX01_CARD_IDS
from zz.pc01 import PC01_CARD_IDS
from zz.pc01r import PC01R_CARD_IDS
from zz.pc02 import PC02_CARD_IDS
from zz.ex02c import EX02C_CARD_IDS
from zz.web.assets import AssetIndex
from zz.web.catalog import _series_filter_value, catalog_dto


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def catalog():
    return catalog_dto(AssetIndex(None))


def test_published_card_pack_inventory_is_complete() -> None:
    assert len(EX01_CARD_IDS) == 12
    assert len(PC01_CARD_IDS) == 143
    assert len(PC01R_CARD_IDS) == 70
    assert len(PC02_CARD_IDS) == 100
    assert len(set(EX01_CARD_IDS + PC01_CARD_IDS + PC01R_CARD_IDS + PC02_CARD_IDS)) == 325
    assert len(EX02C_CARD_IDS) == 70
    assert len(set(EX02C_CARD_IDS)) == 70
    assert len(set((*EX01_CARD_IDS, *PC01_CARD_IDS, *PC01R_CARD_IDS, *PC02_CARD_IDS, *EX02C_CARD_IDS))) == 395


def test_catalog_series_values_match_the_actual_dropdown_values(catalog) -> None:
    series = next(group for group in catalog["filters"] if group["id"] == "series")
    allowed = {option["value"] for option in series["options"]}
    for card in catalog["cards"]:
        assert len(card["filterValues"]["series"]) == 1
        assert set(card["filterValues"]["series"]) <= allowed, card["id"]


def test_series_filter_resolves_declared_labels_and_rejects_unknown_packs() -> None:
    filters = [{"id": "series", "options": [{"value": "pack-code", "labelJp": "Printed pack"}]}]
    assert _series_filter_value("Printed pack", filters) == "pack-code"
    assert _series_filter_value("pack-code", filters) == "pack-code"
    assert _series_filter_value("", filters) == ""
    with pytest.raises(ValueError, match="Unknown pack"):
        _series_filter_value("Unknown pack", filters)


def test_ex02c_dropdown_reaches_real_deck_and_debug_search(catalog) -> None:
    harness = r"""
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const catalog = JSON.parse(fs.readFileSync(0, 'utf8'));
const source = fs.readFileSync(process.argv[1], 'utf8');
const names = ['filterGroups', 'localizedCatalogLabel', 'localizedFilterValue',
  'localizedCardSeries', 'activeOfficialFilters', 'cardMatchesOfficialFilters',
  'cardMatchesSearch', 'setDeckFilter', 'filteredDeckCatalogCards',
  'cardMatchesBattleDebugFilters', 'battleDebugCards', 'canAddBattleDebugCard',
  'renderOfficialFilterControls'];
const functions = names.map(name => {
  const start = source.indexOf(`function ${name}(`);
  assert.ok(start >= 0, name);
  const remaining = source.slice(start);
  const next = remaining.search(/\n(?:async )?function /);
  return next < 0 ? remaining : remaining.slice(0, next);
}).join('\n');
const context = { catalog, assert, deckEditor: { filters: {}, search: '' },
  battleDebugFilters: {}, battleDebugSearch: '', render() {},
  currentLanguage: () => 'zh', t: value => value, esc: value => String(value) };
vm.createContext(context);
vm.runInContext(functions + `
const series = catalog.filters.find(group => group.id === 'series');
const sao = series.options.find(option => option.labelJp === 'EXCODE:02C SAO');
assert.ok(renderOfficialFilterControls().includes('value="' + sao.value + '"'));
setDeckFilter('series', sao.value);
const found = filteredDeckCatalogCards();
assert.equal(found.length, 65, 'EX02C dropdown must find all buildable cards');
assert.ok(found.every(card => card.id.includes('_02c_')));
battleDebugFilters = { series: sao.value };
assert.equal(battleDebugCards().length, 65);
for (const language of ['zh', 'ja', 'en']) {
  currentLanguage = () => language;
  const key = { zh: 'labelZh', ja: 'labelJp', en: 'labelEn' }[language];
  assert.equal(localizedCardSeries(found[0]), sao[key]);
}
setDeckFilter('series', 'CAMPAIGN');
assert.equal(filteredDeckCatalogCards().length, 2);
assert.ok(filteredDeckCatalogCards().every(card => card.id.includes('_cp_')));
setDeckFilter('series', 'PC:02R DIVINE');
assert.ok(filteredDeckCatalogCards().length > 0);
assert.ok(filteredDeckCatalogCards().every(card => !card.id.includes('_02c_')));
setDeckFilter('series', sao.value);
deckEditor.search = 'colorless_05_02_cp_00';
assert.equal(filteredDeckCatalogCards().length, 0, 'other packs stay excluded');
deckEditor.search = 'red_00_01_02c_00';
assert.equal(filteredDeckCatalogCards().length, 1);
assert.ok(catalog.cards.filter(card => card.id.includes('_02c_') && !card.deckBuildable)
  .every(card => !found.some(candidate => candidate.id === card.id)));
`, context);
"""
    result = subprocess.run(
        ["node", "-e", harness, str(ROOT / "zz/web/static/app.js")],
        input=json.dumps(catalog, ensure_ascii=False),
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
