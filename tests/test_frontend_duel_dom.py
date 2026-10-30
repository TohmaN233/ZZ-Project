from __future__ import annotations

import base64
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest


BROWSER = next((path for path in (
    shutil.which("google-chrome"), shutil.which("chromium"),
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
) if path and Path(path).is_file()), None)
pytestmark = pytest.mark.skipif(BROWSER is None, reason="headless Chrome/Chromium is required")


def test_duel_dom_patch_preserves_board_identity_and_animation(tmp_path):
    source_path = Path(__file__).parents[1] / "zz" / "web" / "static" / "duel-dom.js"
    module_source = source_path.read_text(encoding="utf-8")
    browser_script = r"""
const app = document.getElementById("app");
const assert = (condition, message) => {
  if (!condition) throw new Error(message);
};
const makeFrame = (eventId, eventText, eventStyle, overlayId, overlayText, overlayStyle,
                   fieldCards, handCards, hiddenCards, extraStyle, inputValue) => {
  const field = fieldCards.join("");
  const hand = handCards.map((markup, index) =>
    '<div class="hand-slot" style="--i:' + index + '; --n:' + handCards.length +
      '; --fan-angle:' + ((index - (handCards.length - 1) / 2) * 1.6).toFixed(2) +
      'deg">' + markup + '</div>').join("");
  const hidden = hiddenCards;
  return '<header class="topbar"><input id="duel-name" value="' +
    (inputValue || "before") + '"></header>' +
    '<div class="duel-board">' +
      '<section class="cockpit top">' +
        '<section class="arena">' +
          '<div class="zone-cards field-zone" data-board-anchor="P1:field" style="' +
            extraStyle + '">' + field +
            '<div class="force" data-board-anchor="P1:force" ' +
              'data-board-force-anchor="P1:force:f-1">force</div>' +
          '</div>' +
        '</section>' +
      '</section>' +
      '<section class="cockpit bottom">' +
        '<div class="zone-cards hand-zone" data-board-anchor="P1:hand">' +
          '<div class="hand-fan bottom" data-board-anchor="P1:hand-fan">' +
            '<div class="hand-cards" style="--hand-count:' +
              Math.max(2, handCards.length) + '; --old-template:stale">' + hand + hidden + '</div>' +
          '</div>' +
        '</div>' +
      '</section>' +
      '<div class="board-animation-layer" data-fx-event="' + eventId +
        '" style="' + eventStyle + '"><span class="event-copy">' + eventText + '</span></div>' +
      '<div class="visual-overlay" data-fx-event="' + overlayId +
        '" style="' + overlayStyle + '"><span class="overlay-copy">' + overlayText + '</span></div>' +
      '<div id="scroll-box" style="overflow:auto; width:20px; height:10px">' +
        '<div style="height:200px">scroll content</div></div>' +
    '</div>';
};
const card = (anchor, text, className) =>
  '<div class="' + className + '" data-board-card-anchor="' + anchor + '">' + text + '</div>';
const hiddenCards = (label, count) => Array.from({length: count}, (_, index) =>
  '<div class="card hidden"><span>' + label + '-' + index + '</span></div>').join("");

const firstHtml = makeFrame(
  "attack-1", "event one", "animation-name: attack; --fx-phase: one",
  "damage-1", "overlay one", "color: rgb(1, 2, 3)",
  [card("P1:card:move", "moving", "card field-card"),
   card("P1:card:stay", "staying", "card field-card")],
  [card("P1:card:hand-stay", "hand stays", "card hand-card"),
   card("P1:card:remove", "removed", "card hand-card")],
  hiddenCards("first", 8),
  "--field-w: 18px; --field-h: 19px; --template-stale: old; color: red"
);
const first = window.ZZDuelDom.patch(app, firstHtml);
assert(first.mounted === true, "first board mount must be reported");
assert(first.board === app.querySelector(".duel-board"), "patch must return the mounted board");

const board = first.board;
const cockpit = app.querySelector(".cockpit.top");
const arena = app.querySelector(".arena");
const fieldZone = app.querySelector('[data-board-anchor="P1:field"]');
const handZone = app.querySelector('[data-board-anchor="P1:hand"]');
const hand = app.querySelector(".hand-fan");
const movedCard = app.querySelector('[data-board-card-anchor="P1:card:move"]');
const stayingCard = app.querySelector('[data-board-card-anchor="P1:card:stay"]');
const handCard = app.querySelector('[data-board-card-anchor="P1:card:hand-stay"]');
const removedCard = app.querySelector('[data-board-card-anchor="P1:card:remove"]');
const force = app.querySelector('[data-board-force-anchor="P1:force:f-1"]');
const eventLayer = app.querySelector(".board-animation-layer");
const eventChild = eventLayer.querySelector(".event-copy");
const overlay = app.querySelector(".visual-overlay");
const overlayChild = overlay.querySelector(".overlay-copy");
const focusedInput = app.querySelector("#duel-name");
const scrollBox = app.querySelector("#scroll-box");

fieldZone.style.setProperty("--field-w", "77px");
fieldZone.style.setProperty("--field-h", "calc(77px * 1.42)");
fieldZone.style.setProperty("--mini-w", "31px");
fieldZone.style.setProperty("--mini-h", "calc(31px * 1.42)");
hand.style.setProperty("--hand-w", "91px");
hand.style.setProperty("--hand-h", "calc(91px * 1.42)");
hand.style.setProperty("--mini-w", "56px");
hand.style.setProperty("--mini-h", "calc(56px * 1.42)");
app.querySelector(".hand-cards").style.setProperty("--hand-overlap", "13px");
app.querySelector(".hand-cards").style.setProperty("--opponent-hand-overlap", "17px");
focusedInput.focus();
focusedInput.setSelectionRange(2, 4);
scrollBox.scrollTop = 50;

const nextFieldStyle =
  "--field-w: 21px; --field-h: 22px; --mini-w: 23px; --mini-h: 24px; " +
  "--template-current: new; color: blue";
const secondHtml = makeFrame(
  "attack-1", "changed event text", "animation-name: changed; --fx-phase: changed",
  "damage-1", "changed overlay text", "color: rgb(9, 8, 7)",
  [card("P1:card:stay", "staying updated", "card field-card")],
  [card("P1:card:move", "moved", "card hand-card"),
   card("P1:card:hand-stay", "hand stays updated", "card hand-card"),
   card("P1:card:new", "new", "card hand-card")],
  hiddenCards("second", 8),
  nextFieldStyle,
  "after"
);
const second = window.ZZDuelDom.patch(app, secondHtml);
assert(second.mounted === false && second.board === board, "board reference must remain stable");
assert(app.querySelector(".cockpit.top") === cockpit, "cockpit reference must remain stable");
assert(app.querySelector(".arena") === arena, "arena reference must remain stable");
assert(app.querySelector('[data-board-anchor="P1:field"]') === fieldZone,
  "field zone reference must remain stable");
assert(app.querySelector('[data-board-anchor="P1:hand"]') === handZone,
  "hand zone reference must remain stable");
assert(app.querySelector(".hand-fan") === hand, "hand reference must remain stable");
assert(app.querySelector('[data-board-card-anchor="P1:card:move"]') === movedCard,
  "card identity must follow its key when it moves zones");
assert(!fieldZone.contains(movedCard), "moved card must leave its old source zone");
assert(app.querySelectorAll('[data-board-card-anchor="P1:card:move"]').length === 1,
  "moved card key must appear once");
assert(app.querySelector('[data-board-card-anchor="P1:card:stay"]') === stayingCard,
  "unmoved card reference must remain stable");
assert(app.querySelector('[data-board-card-anchor="P1:card:hand-stay"]') === handCard,
  "hand card reference must remain stable");
assert(stayingCard.isConnected &&
  app.querySelector('[data-board-card-anchor="P1:card:stay"]') === stayingCard,
  "card lookup must resolve to the original connected node");
assert(app.querySelector('[data-board-force-anchor="P1:force:f-1"]') === force,
  "force reference must remain stable");
assert(!app.querySelector('[data-board-card-anchor="P1:card:remove"]') &&
  !removedCard.isConnected, "removed card must be deleted");
assert(app.querySelector('[data-board-card-anchor="P1:card:new"]'),
  "new card must be inserted");
assert(app.querySelectorAll(".hand-cards .hidden").length === 8,
  "hidden cards without iid anchors must not stall reconciliation");
assert(fieldZone.style.getPropertyValue("--field-w") === "77px",
  "DuelLayout field size must survive template updates");
assert(fieldZone.style.getPropertyValue("--field-h") === "calc(77px * 1.42)",
  "DuelLayout field height must survive template updates");
assert(fieldZone.style.getPropertyValue("--mini-w") === "31px",
  "DuelLayout mini size must survive template updates");
assert(hand.style.getPropertyValue("--hand-w") === "91px" &&
  hand.style.getPropertyValue("--hand-h") === "calc(91px * 1.42)",
  "DuelLayout hand size must survive template updates");
assert(hand.style.getPropertyValue("--mini-w") === "56px" &&
  hand.style.getPropertyValue("--mini-h") === "calc(56px * 1.42)",
  "DuelLayout hand mini size must survive template updates");
assert(app.querySelector(".hand-cards").style.getPropertyValue("--hand-overlap") === "13px" &&
  app.querySelector(".hand-cards").style.getPropertyValue("--opponent-hand-overlap") === "17px",
  "DuelLayout overlap variables must survive template updates");
assert(app.querySelector(".hand-cards").style.getPropertyValue("--hand-count") === "3",
  "template hand count must update when the rendered hand size changes");
assert(fieldZone.style.getPropertyValue("--template-current") === "new",
  "new template style must be applied");
assert(!fieldZone.style.getPropertyValue("--template-stale"),
  "stale template style must be discarded");
assert(fieldZone.style.color === "blue", "ordinary inline styles must follow the new template");
assert(app.querySelector("#duel-name") === focusedInput &&
  document.activeElement === focusedInput,
  "focused input identity and focus must survive");
assert(focusedInput.value === "after", "input value property must match template attributes");
assert(focusedInput.selectionStart === 2 && focusedInput.selectionEnd === 4,
  "focused input selection must survive");
assert(scrollBox.scrollTop === 50, "scroll position must survive template updates");
assert(eventLayer === app.querySelector(".board-animation-layer"),
  "identical board event must keep its animation root");
assert(eventLayer.querySelector(".event-copy") === eventChild &&
  eventChild.textContent === "event one",
  "identical board event must keep its entire old subtree");
assert(eventLayer.getAttribute("style") === "animation-name: attack; --fx-phase: one",
  "identical board event must keep its animation styles");
assert(overlay === app.querySelector(".visual-overlay") &&
  overlay.querySelector(".overlay-copy") === overlayChild &&
  overlayChild.textContent === "overlay one",
  "identical overlay event must keep its entire old subtree");
assert(overlay.getAttribute("style") === "color: rgb(1, 2, 3)",
  "identical overlay event must keep its styles");

const canvas = document.createElement("canvas");
canvas.setAttribute("data-fx-owned", "effekseer");
board.appendChild(canvas);
const observer = new MutationObserver(() => {});
observer.observe(app, {subtree: true, childList: true, attributes: true, characterData: true});
const sameHtml = window.ZZDuelDom.patch(app, secondHtml);
const unchangedWrites = observer.takeRecords().length;
observer.disconnect();
assert(sameHtml.board === board && sameHtml.mounted === false,
  "same HTML must return the existing board");
assert(unchangedWrites === 0, "same HTML must perform no DOM writes");
assert(board.contains(canvas), "player-owned canvas must survive patching");

const bannerHtml = secondHtml.replace('<div class="duel-board">',
  '<div class="connection-banner">reconnecting</div><div class="duel-board">')
  .replace('<section class="arena">', '<section class="arena-notice">notice</section><section class="arena">');
window.ZZDuelDom.patch(app, bannerHtml);
assert(app.querySelector(".duel-board") === board && board.contains(canvas),
  "inserting a same-tag banner must preserve the board and runtime canvas");
assert(app.querySelector(".arena") === arena && app.querySelector(".cockpit.top") === cockpit,
  "inserting a same-tag notice must preserve layout roots");
assert(app.querySelector(".board-animation-layer") === eventLayer,
  "inserting a banner must not restart an active animation");
window.ZZDuelDom.patch(app, secondHtml);
assert(app.querySelector(".duel-board") === board && app.querySelector(".arena") === arena &&
  !app.querySelector(".connection-banner"), "removing banners must preserve layout roots");

const thirdHtml = makeFrame(
  "attack-2", "event two", "animation-name: attack-two; --fx-phase: two",
  "damage-2", "overlay two", "color: rgb(3, 2, 1)",
  [card("P1:card:stay", "staying updated", "card field-card")],
  [card("P1:card:move", "moved", "card hand-card"),
   card("P1:card:hand-stay", "hand stays updated", "card hand-card"),
   card("P1:card:new", "new", "card hand-card")],
  hiddenCards("third", 8),
  nextFieldStyle
);
const third = window.ZZDuelDom.patch(app, thirdHtml);
const newEventLayer = app.querySelector(".board-animation-layer");
const newOverlay = app.querySelector(".visual-overlay");
assert(newEventLayer !== eventLayer && !app.contains(eventLayer),
  "changed board event must rebuild its animation subtree");
assert(newEventLayer.querySelector(".event-copy").textContent === "event two",
  "changed board event content must be rendered");
assert(newOverlay !== overlay && !app.contains(overlay),
  "changed overlay event must rebuild its subtree");
assert(newOverlay.querySelector(".overlay-copy").textContent === "overlay two",
  "changed overlay content must be rendered");
assert(board.contains(canvas), "player-owned canvas must survive changed events");
assert(third.board === board && third.mounted === false, "event changes must not remount the board");

const emptyEventHtml = makeFrame(
  "", "empty event patched", "color: green",
  "", "empty overlay patched", "color: purple",
  [card("P1:card:stay", "staying updated", "card field-card")],
  [card("P1:card:move", "moved", "card hand-card"),
   card("P1:card:hand-stay", "hand stays updated", "card hand-card"),
   card("P1:card:new", "new", "card hand-card")],
  hiddenCards("empty", 8),
  nextFieldStyle
);
window.ZZDuelDom.patch(app, emptyEventHtml);
const emptyLayer = app.querySelector(".board-animation-layer");
const emptyOverlay = app.querySelector(".visual-overlay");
assert(emptyLayer !== newEventLayer &&
  emptyLayer.querySelector(".event-copy").textContent === "empty event patched",
  "changing an event to empty must rebuild its prior animation subtree");
assert(emptyOverlay !== newOverlay &&
  emptyOverlay.querySelector(".overlay-copy").textContent === "empty overlay patched",
  "changing an event to empty must rebuild its prior overlay subtree");
const emptyUpdateHtml = makeFrame(
  "", "empty event updated", "color: teal",
  "", "empty overlay updated", "color: orange",
  [card("P1:card:stay", "staying updated", "card field-card")],
  [card("P1:card:move", "moved", "card hand-card"),
   card("P1:card:hand-stay", "hand stays updated", "card hand-card"),
   card("P1:card:new", "new", "card hand-card")],
  hiddenCards("empty-update", 8),
  nextFieldStyle
);
window.ZZDuelDom.patch(app, emptyUpdateHtml);
assert(emptyLayer === app.querySelector(".board-animation-layer") &&
  emptyLayer.querySelector(".event-copy").textContent === "empty event updated",
  "an empty board event must receive a normal patch");
assert(emptyOverlay === app.querySelector(".visual-overlay") &&
  emptyOverlay.querySelector(".overlay-copy").textContent === "empty overlay updated",
  "an empty overlay event must receive a normal patch");

const handOrderFrame = (order) => makeFrame(
  "", "slot event", "", "", "slot overlay", "",
  [], order.map((name) => card("P1:card:slot-" + name, name, "card hand-card")),
  "", "", "slots"
);
window.ZZDuelDom.patch(app, handOrderFrame(["A", "B", "C"]));
const oldSlots = new Map(Array.from(app.querySelectorAll(".hand-slot"), (slot) => {
  const anchor = slot.querySelector("[data-board-card-anchor]").getAttribute("data-board-card-anchor");
  return [anchor, slot];
}));
const oldCards = new Map(Array.from(app.querySelectorAll(".hand-slot [data-board-card-anchor]"),
  (node) => [node.getAttribute("data-board-card-anchor"), node]));
window.ZZDuelDom.patch(app, handOrderFrame(["C", "B"]));
const currentSlots = Array.from(app.querySelectorAll(".hand-slot"));
const currentAnchors = currentSlots.map((slot) =>
  slot.querySelector("[data-board-card-anchor]").getAttribute("data-board-card-anchor"));
assert(currentAnchors.join(",") === "P1:card:slot-C,P1:card:slot-B",
  "hand slots must follow the new card order after first-card deletion");
assert(currentSlots[0] === oldSlots.get("P1:card:slot-C") &&
  currentSlots[1] === oldSlots.get("P1:card:slot-B"),
  "each keyed hand slot reference must follow its card through deletion and reorder");
assert(currentSlots[0].querySelector("[data-board-card-anchor]") ===
  oldCards.get("P1:card:slot-C") &&
  currentSlots[1].querySelector("[data-board-card-anchor]") ===
  oldCards.get("P1:card:slot-B"),
  "hand cards and their independent slots must retain matching identities");
assert(!app.querySelector('[data-board-card-anchor="P1:card:slot-A"]') &&
  !oldSlots.get("P1:card:slot-A").isConnected,
  "deleted first card and slot must be removed");
assert(currentSlots[0].style.getPropertyValue("--i") === "0" &&
  currentSlots[1].style.getPropertyValue("--i") === "1",
  "reused hand slots must receive current fan positions");

const hiddenSlots = (label, count) => Array.from({length: count}, (_, index) =>
  '<div class="hand-slot" style="--i:' + index + '"><div class="card hidden"><span>' +
  label + '-' + index + '</span></div></div>').join("");
const hiddenHtml = (label) =>
  '<div class="duel-board"><section class="cockpit bottom"><section class="arena">' +
  '<div class="zone-cards" data-board-anchor="P1:hidden-zone"><div class="hand-fan">' +
  '<div class="hand-cards">' + hiddenSlots(label, 8) +
  '</div></div></div></section></section></div>';
const hiddenFrameA = hiddenHtml("a");
window.ZZDuelDom.patch(app, hiddenFrameA);
const unkeyedHidden = app.querySelector(".hidden");
const unkeyedSlots = Array.from(app.querySelectorAll(".hand-slot"));
for (let iteration = 0; iteration < 5; iteration += 1) {
  window.ZZDuelDom.patch(app, hiddenHtml("frame-" + iteration));
}
assert(app.querySelectorAll(".hidden").length === 8,
  "repeated hidden cards with no iid must complete each patch");
assert(app.querySelector(".hidden") === unkeyedHidden,
  "unkeyed hidden card reference must remain stable at its position");
assert(Array.from(app.querySelectorAll(".hand-slot")).every((slot, index) =>
  slot === unkeyedSlots[index]),
  "hand slots without card anchors must use positional identity");
assert(window.ZZDuelDom.patch(app, hiddenHtml("frame-4")).mounted === false,
  "identical hidden frame must use the no-write path");

return {ok: true, checks: 40};
"""
    html = (
        "<!doctype html><html><head><meta charset=\"utf-8\"></head><body>"
        "<main id=\"app\"></main><pre id=\"result\"></pre>"
        "<script>" + module_source + "</script><script>"
        "try { const result = (function () {" + browser_script + "})();"
        "document.getElementById('result').dataset.payload = "
        "btoa(unescape(encodeURIComponent(JSON.stringify(result))));"
        "} catch (error) { const result = document.getElementById('result');"
        "result.dataset.error = String(error && error.stack || error); }"
        "</script></body></html>"
    )
    page = tmp_path / "duel-dom.html"
    page.write_text(html, encoding="utf-8")
    result = subprocess.run(
        [
            BROWSER, "--headless=new", "--disable-gpu", "--no-first-run",
            "--no-default-browser-check", f"--user-data-dir={tmp_path / 'chrome-profile'}",
            "--disable-breakpad", "--disable-crash-reporter", "--no-sandbox",
            "--allow-file-access-from-files", "--force-device-scale-factor=1",
            "--virtual-time-budget=1500", "--dump-dom", page.as_uri(),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    assert result.returncode == 0, result.stdout[-3000:] + result.stderr[-1000:]
    error = re.search(r'<pre id="result" data-error="([^"]+)"', result.stdout)
    assert error is None, result.stdout[-3000:] + result.stderr[-1000:]
    payload = re.search(r'<pre id="result" data-payload="([^"]+)"', result.stdout)
    assert payload, result.stdout[-3000:] + result.stderr[-1000:]
    decoded = base64.b64decode(payload[1]).decode("utf-8")
    assert '"ok":true' in decoded, decoded
