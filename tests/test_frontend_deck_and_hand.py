from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from test_frontend_fx import BROWSER, _run_fx_test_page, duel_fx_fixture


ROOT = Path(__file__).resolve().parents[1]
APP_SOURCE = (ROOT / "zz" / "web" / "static" / "app.js").read_text(encoding="utf-8")
STYLE_SOURCE = (ROOT / "zz" / "web" / "static" / "styles.css").read_text(encoding="utf-8")


def _function_source(name: str) -> str:
    start = APP_SOURCE.index(f"function {name}(")
    end = APP_SOURCE.find("\nfunction ", start + 1)
    return APP_SOURCE[start:] if end < 0 else APP_SOURCE[start:end]


def test_home_exposes_deck_builder_through_existing_route() -> None:
    home = _function_source("renderHome")

    assert 'data-view="deckbuilder"' in home
    assert 't("deckBuilder")' in home
    assert 'else if (view === "deckbuilder") startDeckBuilder();' in APP_SOURCE


def test_clear_deck_starts_an_empty_editor_without_deleting_saved_decks(duel_fx_fixture, tmp_path):
    if BROWSER is None:
        pytest.skip("Chrome is required for the deck builder interaction test")
    child = r'''<!doctype html><html><head><meta charset="utf-8"><base href="ORIGIN/">
<link rel="stylesheet" href="/static/styles.css"></head><body><main id="app"></main>
<script>window.ZZ_DEFER_BOOT=true;</script>
<script src="/static/api-client.js"></script><script src="/static/multiplayer-card-policy.js"></script>
<script src="/static/duel-layout.js"></script><script src="/static/duel-dom.js"></script>
<script src="/static/fx-core.js"></script><script src="/static/app.js"></script><script>
const postResult=value=>parent.postMessage({fxPayload:btoa(unescape(encodeURIComponent(JSON.stringify(value))))},"*");
(async()=>{
  const fixture=FIXTURE, assert=(condition,message)=>{if(!condition)throw new Error(message);};
  catalog=fixture.catalog;
  const saved={...catalog.defaultDecks[0],id:"saved-deck",name:"First deck"};
  savedDecks=[saved];
  const savedBefore=JSON.stringify(savedDecks);
  let deletes=0;ZZApi.delete=()=>{deletes++;return Promise.resolve({ok:true});};
  startDeckBuilder(saved);
  deckEditor.search="old search";deckEditor.filters={series:"old filter"};
  showLobby();startDeckBuilder();
  assert(deckTotal()===40,"returning to the editor keeps its existing draft");
  const labels={zh:"清空卡组",ja:"デッキをクリア",en:"Clear deck"};
  for(const [lang,label] of Object.entries(labels)){
    settings.uiLanguage=lang;render();
    const button=app.querySelector('.deck-list-panel [data-new-deck]');
    assert(button&&button.textContent.trim()===label,"clear button is visible in "+lang);
    const buttonRect=button.getBoundingClientRect(),panelRect=app.querySelector('.deck-list-panel').getBoundingClientRect();
    assert(buttonRect.width>0&&buttonRect.right<=panelRect.right,"clear button fits inside its panel");
  }
  settings.uiLanguage="zh";render();
  app.querySelector('.deck-list-panel [data-new-deck]').click();
  assert(deckTotal()===0&&deckEditor.selectedForceIds.length===0,"cards and forces are cleared");
  assert(deckEditor.id===null&&deckEditor.name==="New Deck","the next save creates a new deck");
  assert(deckEditor.search===""&&!Object.keys(deckEditor.filters).length,"search and filters reset");
  assert(JSON.stringify(savedDecks)===savedBefore&&deletes===0,"saved decks stay unchanged");
  assert(app.querySelector('[data-save-deck]').disabled,"empty deck cannot be saved");
  const add=app.querySelector('.card-catalog-list [data-deck-add]:not([disabled])');
  assert(add,"a new deck can be built immediately");add.click();
  assert(deckTotal()===1,"adding to the new deck works");

  loadDeckIntoEditor(saved);render();
  let finishSave;
  ZZApi.request=(path,body=null)=>{
    if(path==="/api/decks"&&body)return new Promise(resolve=>{finishSave=resolve;});
    if(path==="/api/decks")return Promise.resolve({ok:true,decks:savedDecks});
    throw new Error("unexpected request: "+path);
  };
  const saving=saveCurrentDeck();
  assert(finishSave,"valid saved deck starts saving");
  app.querySelector('.deck-list-panel [data-new-deck]').click();
  finishSave({ok:true,deck:saved});await saving;
  assert(deckTotal()===0&&deckEditor.id===null,"a late save must not replace the new editor");
  assert(JSON.stringify(savedDecks)===savedBefore,"saving and clearing do not delete saved decks");
  loadDeckIntoEditor(saved);render();
  ZZApi.request=(path,body=null)=>Promise.resolve(body
    ? {ok:true,deck:{...saved,name:"Saved normally"}} : {ok:true,decks:savedDecks});
  await saveCurrentDeck();
  assert(deckEditor.id===saved.id&&deckEditor.name==="Saved normally","saving the same editor still applies");

  let remaining=15;const partial={};
  for(const [id,count] of Object.entries(saved.recipe)){
    const take=Math.min(count,remaining);if(take)partial[id]=take;
    remaining-=take;if(!remaining)break;
  }
  loadDeckIntoEditor({name:"Partial",recipe:partial,forces:saved.forces});render();
  assert(deckCanAiComplete(),"partial deck can request AI completion");
  let finishCompletion;
  ZZApi.request=()=>new Promise(resolve=>{finishCompletion=resolve;});
  const completing=requestDeckAiCompletion();
  assert(finishCompletion,"AI completion starts");
  app.querySelector('.deck-list-panel [data-new-deck]').click();
  finishCompletion({ok:true,completion:{recipe:saved.recipe,forces:saved.forces}});await completing;
  assert(deckTotal()===0&&deckEditor.selectedForceIds.length===0,"late completion must not refill a cleared deck");
  loadDeckIntoEditor({name:"Partial",recipe:partial,forces:saved.forces});render();
  ZZApi.request=()=>Promise.resolve({ok:true,completion:{recipe:saved.recipe,forces:saved.forces}});
  await requestDeckAiCompletion();
  assert(deckTotal()===40,"completion still applies to the same editor");
  return {ok:true};
})().then(postResult).catch(error=>postResult({error:String(error&&error.stack||error)}));
</script></body></html>'''
    _run_fx_test_page(duel_fx_fixture, tmp_path, child)


def test_new_game_keeps_selected_decks_when_payload_is_partial_or_empty() -> None:
    start_new = _function_source("startNew")

    assert "...selectedBattlePayload()," in start_new
    assert "...(launchPayload || {})," in start_new
    assert "activeMatchPayload = cloneLaunchPayload(payload);" in start_new
    assert 'startNew(newGame.dataset.new, activeMatchPayload);' in APP_SOURCE


def test_player_hand_uses_a_fixed_fan_with_real_hit_areas() -> None:
    hand = _function_source("renderHandFan")

    assert 'class="hand-slot"' in hand
    assert '"hand-card"' in hand
    assert '"opponent-hand-card"' in hand
    assert "--n:${handCount}" in hand
    assert "--hand-count:${Math.max(2, handCount)}" in hand

    assert "--hand-w: clamp(72px, 6vw, 104px);" in STYLE_SOURCE
    assert ".hand-fan.bottom .hand-cards" in STYLE_SOURCE
    assert "overflow: visible;" in STYLE_SOURCE
    assert "--hand-overlap: clamp(" in STYLE_SOURCE
    assert "margin-left: calc(-1 * var(--hand-overlap));" in STYLE_SOURCE
    assert "transform: rotate(var(--fan-angle, 0deg));" in STYLE_SOURCE
    assert "translateY(-10px) rotate(0deg)" in STYLE_SOURCE
    assert "scroll-snap-type: x proximity;" not in STYLE_SOURCE
    assert "transform: scale(1.8);" not in STYLE_SOURCE


def test_floating_pass_gets_a_dedicated_command_row() -> None:
    assert ".cockpit-command-row:has(.prompt.has-floating-actions)" in STYLE_SOURCE
    assert ".cockpit-command-row .prompt.has-floating-actions" in STYLE_SOURCE
    assert "min-height: clamp(88px, 7.2vw, 110px);" in STYLE_SOURCE
    assert "bottom: 0;" in STYLE_SOURCE

def test_catalog_card_detail_keeps_deck_builder_scroll() -> None:
    functions = "\n".join(_function_source(name) for name in (
        "captureDeckBuilderScroll", "restoreDeckBuilderScroll",
        "renderPreservingDeckBuilderScroll", "renderPreservingActiveViewScroll",
        "openCatalogCardDetail", "closeCatalogCardDetail",
    ))
    harness = r"""
const assert = require('node:assert/strict');
let appView = 'deckbuilder', selectedCatalogCardId = null, catalogDetailSwipeStart = null;
const CODEMAN_MEMORY_VIEW = 'memory', CODEMAN_REPLAY_VIEW = 'replay';
let catalogList = {scrollTop: 840}, deckList = {scrollTop: 290};
const document = {querySelector: selector => selector === '.card-catalog-list' ? catalogList : deckList};
const window = {scrollX: 16, scrollY: 430, scrollTo(x,y) {this.scrollX=x; this.scrollY=y;}};
const requestAnimationFrame = callback => callback();
let renders = 0;
function render() {
  renders++;
  catalogList = {scrollTop: 0}; deckList = {scrollTop: 0};
  window.scrollX = 0; window.scrollY = 0;
}
function focusCatalogCardDetail() {}
function renderPreservingCodemanReplayScroll() {throw new Error('wrong view');}
eval(process.argv[1]);
for (const action of [() => openCatalogCardDetail('source'), () => closeCatalogCardDetail()]) {
  action();
  assert.equal(catalogList.scrollTop, 840);
  assert.equal(deckList.scrollTop, 290);
  assert.equal(window.scrollX, 16);
  assert.equal(window.scrollY, 430);
}
assert.equal(selectedCatalogCardId, null);
assert.equal(renders, 2);
appView = 'duel';
openCatalogCardDetail('form');
assert.equal(selectedCatalogCardId, 'form');
closeCatalogCardDetail();
assert.equal(selectedCatalogCardId, null);
assert.equal(renders, 4);
"""
    result = subprocess.run(["node", "-e", harness, functions], cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr

