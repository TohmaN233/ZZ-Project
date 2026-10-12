from __future__ import annotations

import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_JS = ROOT / "zz" / "web" / "static" / "app.js"


def test_mock_catalog_filters_and_browses_transformations_through_frontend_events() -> None:
    harness = r"""
const fs = require("node:fs");
const vm = require("node:vm");
const assert = require("node:assert/strict");

const listeners = new Map();
const focusCalls = [];
const detailPanel = { focus(options) { focusCalls.push(options); } };
const appElement = {
  innerHTML: "",
  addEventListener(type, listener) {
    const entries = listeners.get(type) || [];
    entries.push(listener);
    listeners.set(type, entries);
  },
  querySelector(selector) {
    return selector === ".catalog-detail-panel" ? detailPanel : null;
  },
  querySelectorAll() { return []; },
  classList: { add() {}, remove() {}, toggle() {} },
};
const context = {
  console,
  listeners,
  assert,
  focusCalls,
  document: {
    getElementById: () => appElement,
    querySelector: () => null,
    querySelectorAll: () => [],
  },
  window: {
    ZZMultiplayerCardPolicy: {
      isCardInteractive: (card) => !card.faceDown,
      actionOptionsForCard: () => [],
      canMulliganSelect: () => false,
    },
    ZZDuelLayout: { normalizeScale: Number, observe: () => null },
    ZZ_DEFER_BOOT: true,
    addEventListener() {},
    location: { hash: "", origin: "http://localhost", pathname: "/" },
    history: { replaceState() {} },
  },
  navigator: {},
  requestAnimationFrame(callback) { callback(); },
  setTimeout,
  clearTimeout,
  performance: { now: () => 0 },
};
vm.createContext(context);
const appSource = fs.readFileSync(process.argv[1], "utf8");
const behaviorAssertions = `
const makeCard = (id, zh, jp, en, buildable, transformations = undefined) => ({
  id,
  copyIdentity: id,
  nameZh: zh,
  nameJp: jp,
  nameEn: en,
  assetUrl: "/art/" + id + "-localized",
  assetUrlEn: "/art/" + id + "-en",
  type: "f_minion",
  officialCost: "3",
  totalCost: 3,
  bp: 300,
  dp: 2,
  manaColor: "RED",
  abilityZh: "效果 " + id,
  abilityJp: "効果 " + id,
  abilityEn: "Effect " + id,
  ...(buildable === undefined ? {} : { deckBuildable: buildable }),
  ...(transformations === undefined ? {} : { transformationIds: transformations }),
});
const anjuFormIds = Array.from({ length: 6 }, (_, index) => "anju-form-" + (index + 1));
catalog.cards = [
  makeCard("anju-base", "安居", "アンジュ", "Anju", true, anjuFormIds),
  ...anjuFormIds.map((id, index) => makeCard(
    id,
    "安居・第" + (index + 1) + "形态",
    "アンジュ・第" + (index + 1) + "形態",
    "Anju Form " + (index + 1),
    false,
    anjuFormIds.filter((formId) => formId !== id),
  )),
  makeCard("ordinary-card", "普通卡", "通常カード", "Ordinary Card"),
  makeCard("anju-final-dragon", "最终龙", "最終龍", "Final Dragon", false),
];
catalog.filters = [];
settings.uiLanguage = "zh";
deckEditor.search = "";
deckEditor.filters = {};
deckEditor.recipe = {};
deckEditor.selectedForceIds = [];
catalog.devMode = true;
renderPreservingDeckBuilderScroll = () => {};

assert.deepEqual(filteredDeckCatalogCards().map((card) => card.id), ["anju-base", "ordinary-card"]);
assert.equal(canAddDeckCard("anju-form-1"), false);
assert.equal(canAddDeckCard("ordinary-card"), true);
for (const zone of ["hand", "base", "deck", "field", "trash"]) {
  battleDebugZone = zone;
  assert.deepEqual(battleDebugCards().map((card) => card.id), ["anju-base", "ordinary-card"]);
}
battleDebugZone = "hand";
let debugAddCalls = 0;
battleDebugApi = async () => { debugAddCalls += 1; return {}; };
addBattleDebugCard("anju-form-1");
assert.equal(debugAddCalls, 0);

const click = (selector, dataset = {}) => {
  const target = {
    closest(candidate) {
      return candidate === selector ? { dataset, disabled: false } : null;
    },
  };
  const event = { target, preventDefault() { this.defaultPrevented = true; } };
  for (const listener of listeners.get("click") || []) listener(event);
  return event;
};
const keydown = (key) => {
  const target = { closest: () => null };
  const event = { key, target, preventDefault() { this.defaultPrevented = true; } };
  for (const listener of listeners.get("keydown") || []) listener(event);
  return event;
};
const pointer = (type, target, x, y) => {
  const event = {
    type,
    target,
    pointerType: "touch",
    pointerId: 7,
    clientX: x,
    clientY: y,
    button: 0,
    preventDefault() { this.defaultPrevented = true; },
  };
  for (const listener of listeners.get(type) || []) listener(event);
  return event;
};

const gameCard = (id, properties = {}) => {
  const { id: cardId, ...card } = cardById(id);
  return { ...card, cardId, ...properties };
};
const ownHandCard = gameCard("anju-base", { iid: 21, area: "hand", ownerSide: "human" });
const publicFieldCard = gameCard("anju-base", { iid: 22, area: "field", ownerSide: "opponent" });
const hiddenOpponentHandCard = {
  ...gameCard("anju-base", { iid: 23, area: "hand", ownerSide: "opponent" }), faceDown: true,
};
const ownHandDetail = renderCardDetailPanel(ownHandCard, { showDebugTools: false });
const publicFieldDetail = renderCardDetailPanel(publicFieldCard, { showDebugTools: false });
const transformedFieldDetail = renderCardDetailPanel(
  gameCard("anju-form-1", { iid: 24, area: "field", ownerSide: "human" }),
  { showDebugTools: false },
);
const lastTransformedFieldDetail = renderCardDetailPanel(
  gameCard("anju-form-6", { iid: 25, area: "field", ownerSide: "human" }),
  { showDebugTools: false },
);
assert.ok(ownHandDetail.includes('data-card-transformation-preview="anju-form-1"'));
assert.ok(publicFieldDetail.includes('data-card-transformation-preview="anju-form-1"'));
assert.ok(transformedFieldDetail.includes('data-card-transformation-preview="anju-form-2"'));
assert.ok(lastTransformedFieldDetail.includes('data-card-transformation-preview="anju-form-1"'));
assert.ok(!renderCardDetailPanel(cardById("anju-final-dragon"), { showDebugTools: false }).includes("data-card-transformation-preview"));
assert.ok(!renderCardDetailPanel(hiddenOpponentHandCard, { showDebugTools: false }).includes("data-card-transformation-preview"));
assert.ok(!renderCard(hiddenOpponentHandCard).includes('data-card-iid="23"'));
assert.ok(ownHandDetail.includes("变形后"));
const buffedDetail = renderCardDetailPanel({
  ...publicFieldCard,
  activeEffects: [
    { kind: "battle_stat_modifier", bpDelta: 200, dpDelta: 1 },
    { kind: "blessing_stats", sourceCardId: "anju-base", bpDelta: 100, dpDelta: 0 },
    { kind: "blessing_aura", sourceCardId: "anju-base", bpDelta: 200, dpDelta: 0 },
  ],
}, { showDebugTools: false });
assert.ok(buffedDetail.includes("本次战斗能力修正 / BP +200 / DP +1"));
assert.ok(buffedDetail.includes("安居: 加护能力修正 / BP +100"));
assert.ok(buffedDetail.includes("安居: 加护持续效果 / BP +200"));
settings.uiLanguage = "en";
assert.ok(renderCardDetailPanel(ownHandCard, { showDebugTools: false }).includes("Transformed form"));
settings.uiLanguage = "ja";
assert.ok(renderCardDetailPanel(ownHandCard, { showDebugTools: false }).includes("変形後"));
settings.uiLanguage = "zh";
selectedCatalogCardId = "anju-base";
assert.ok(renderCatalogCardDetail().includes('data-card-transformation-preview="anju-form-1"'));
selectedCatalogCardId = null;

state = {
  players: {
    human: { side: "human", hand: [ownHandCard], field: [], base: [], trash: [], forces: [] },
    opponent: { side: "opponent", hand: [hiddenOpponentHandCard], field: [], base: [], trash: [], forces: [] },
  },
};
selectedCardIid = ownHandCard.iid;
selectedCatalogCardId = "anju-form-1";
selectedForceKey = null;
selectedPlayerSide = null;
selectedTrashSide = null;
renderCockpit = () => "";
renderArena = () => "";
renderBoardAnimationLayer = () => "";
renderCardDetail = () => "<div data-source-card-detail></div>";
renderForceDetail = () => "";
renderPlayerDetail = () => "";
renderTrashDetail = () => "";
renderFieldReplaceEditor = () => "";
renderBaseReplaceEditor = () => "";
renderColorlessBaseReplaceEditor = () => "";
renderPaymentEditor = () => "";
renderEffectPromptModal = () => "";
renderPublicRevealModal = () => "";
renderBattleLogModal = () => "";
renderAnimationOverlay = () => "";
const duelShell = renderDuelBoardShell();
assert.ok(duelShell.includes("data-source-card-detail"));
assert.ok(duelShell.includes("catalog-detail-modal"));
renderPreservingActiveViewScroll = () => {};
click("[data-catalog-detail-close]");
assert.equal(selectedCatalogCardId, null);
assert.equal(selectedCardIid, ownHandCard.iid);

let apiCalls = 0;
api = async () => { apiCalls += 1; return {}; };
renderPreservingActiveViewScroll = () => {};
selectedCardIid = ownHandCard.iid;
selectedCatalogCardId = null;
const cardStateBeforePreview = JSON.stringify(state);
click("[data-card-transformation-preview]", { cardTransformationPreview: "anju-form-1" });
assert.equal(selectedCatalogCardId, "anju-form-1");
assert.equal(selectedCardIid, ownHandCard.iid);
assert.equal(JSON.stringify(state), cardStateBeforePreview);
assert.equal(apiCalls, 0);
const transformationDetail = renderCatalogCardDetail();
assert.ok(transformationDetail.includes("效果 anju-form-1"));

const focusCallsBeforeCatalogOpen = focusCalls.length;
openCatalogCardDetail("anju-base");
assert.equal(focusCalls.length, focusCallsBeforeCatalogOpen + 1);
assert.equal(focusCalls[0].preventScroll, true);
let detail = renderCatalogCardDetail();
assert.ok(detail.includes("安居"));
assert.ok(detail.includes('src="/art/anju-base-localized"'));
assert.ok(detail.includes("效果 anju-base"));
assert.ok(detail.includes('data-catalog-detail-step="1"'));
assert.ok(detail.includes("形态 1 / 7"));

click("[data-catalog-detail-step]", { catalogDetailStep: "1" });
assert.equal(selectedCatalogCardId, "anju-form-1");
assert.ok(focusCalls.length >= 2);
detail = renderCatalogCardDetail();
assert.ok(detail.includes("形态 2 / 7"));
const firstPreviousControlStart = detail.indexOf('data-catalog-detail-step="-1"');
const firstPreviousControlEnd = detail.indexOf(">", firstPreviousControlStart);
assert.ok(!detail.slice(firstPreviousControlStart, firstPreviousControlEnd).includes("disabled"));
click("[data-catalog-detail-step]", { catalogDetailStep: "-1" });
assert.equal(selectedCatalogCardId, "anju-base");
click("[data-catalog-detail-step]", { catalogDetailStep: "1" });
assert.equal(selectedCatalogCardId, "anju-form-1");
detail = renderCatalogCardDetail();
assert.ok(detail.includes("安居・第1形态"));
assert.ok(detail.includes('src="/art/anju-form-1-localized"'));
assert.ok(detail.includes("效果 anju-form-1"));
assert.ok(detail.includes("变形后的卡牌不能加入卡组。"));
assert.ok(detail.includes('data-catalog-detail-step="-1"'));
click("[data-deck-add]", { deckAdd: "anju-form-1" });
assert.equal(deckEditor.recipe["anju-form-1"], undefined);

settings.uiLanguage = "en";
detail = renderCatalogCardDetail();
assert.ok(detail.includes("Anju Form 1"));
assert.ok(detail.includes('src="/art/anju-form-1-en"'));
assert.ok(detail.includes("Effect anju-form-1"));
assert.ok(detail.includes("Transformed cards cannot be added to decks."));
settings.uiLanguage = "ja";
detail = renderCatalogCardDetail();
assert.ok(detail.includes("アンジュ・第1形態"));
assert.ok(detail.includes("効果 anju-form-1"));

const rightKey = keydown("ArrowRight");
assert.equal(rightKey.defaultPrevented, true);
assert.equal(selectedCatalogCardId, "anju-form-2");
detail = renderCatalogCardDetail();
assert.ok(detail.includes("アンジュ・第2形態"));
assert.ok(detail.includes("形態 3 / 7"));
for (let index = 0; index < 4; index += 1) keydown("ArrowRight");
assert.equal(selectedCatalogCardId, "anju-form-6");
detail = renderCatalogCardDetail();
assert.ok(detail.includes("アンジュ・第6形態"));
assert.ok(detail.includes("形態 7 / 7"));
const finalNextControlStart = detail.indexOf('data-catalog-detail-step="1"');
const finalNextControlEnd = detail.indexOf(">", finalNextControlStart);
assert.ok(detail.slice(finalNextControlStart, finalNextControlEnd).includes("disabled"));

const swipeTarget = { closest: (selector) => selector === "[data-catalog-detail-swipe]" ? {} : null };
pointer("pointerdown", swipeTarget, 240, 140);
pointer("pointerup", { closest: () => null }, 320, 143);
assert.equal(selectedCatalogCardId, "anju-form-5");
pointer("pointerdown", swipeTarget, 310, 140);
pointer("pointerup", { closest: () => null }, 230, 142);
assert.equal(selectedCatalogCardId, "anju-form-6");
assert.equal(deckEditor.recipe["anju-form-6"], undefined);

for (let index = 0; index < 6; index += 1) keydown("ArrowLeft");
assert.equal(selectedCatalogCardId, "anju-base");
click("[data-deck-add]", { deckAdd: "anju-base" });
assert.equal(deckEditor.recipe["anju-base"], 1);

deckEditor.recipe = { "anju-base": 39, "anju-form-1": 1 };
deckEditor.selectedForceIds = ["force-a", "force-b"];
assert.equal(deckIsValid(), false);
`;
vm.runInContext(appSource + "\n" + behaviorAssertions, context, { filename: process.argv[1] });
"""
    completed = subprocess.run(
        ["node", "-e", harness, str(APP_JS)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
