from __future__ import annotations

import base64
import copy
import hashlib
import html as html_escape
import importlib.util
import json
import os
import re
import shutil
import subprocess
from http.server import ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from urllib.parse import urlparse

import pytest

from zz.web.server import ServerState, ZenonzardHandler
from zz.web.session import GameSession


BROWSER = next((path for path in (
    shutil.which("google-chrome"), shutil.which("chromium"),
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
) if path and Path(path).is_file()), None)

_fx_import_spec = importlib.util.spec_from_file_location(
    "zz_test_import_duel_fx", Path(__file__).parents[1] / "tools" / "import_duel_fx.py"
)
assert _fx_import_spec and _fx_import_spec.loader
_fx_import_module = importlib.util.module_from_spec(_fx_import_spec)
_fx_import_spec.loader.exec_module(_fx_import_module)
resources = _fx_import_module.resources


def _fx_root() -> Path:
    return Path(__file__).parents[1] / "zz" / "web" / "static" / "fx"


def _package_path(root: Path, name: str) -> Path:
    relative = Path(name)
    assert not relative.is_absolute() and ".." not in relative.parts, name
    resolved_root = root.resolve()
    resolved = (root / relative).resolve()
    assert resolved.is_relative_to(resolved_root), name
    return resolved


def test_duel_fx_manifest_resources_are_closed_and_hashed():
    root = _fx_root()
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    packaged_files = manifest["files"]
    assert packaged_files, "FX manifest must list packaged assets and runtime files"

    for name, expected_digest in packaged_files.items():
        path = _package_path(root, name)
        assert path.is_file(), f"manifest file is missing: {name}"
        actual_digest = hashlib.sha256(path.read_bytes()).hexdigest()
        assert actual_digest == expected_digest, f"SHA-256 mismatch for {name}"

    effect_files = {definition["file"] for definition in manifest["effects"].values()}
    assert len(effect_files) == 20, f"expected twenty original effects, got {sorted(effect_files)}"
    colors = ("red", "blue", "yellow", "green", "purple", "white", "colorless")
    effects = manifest["effects"]
    for event in ("block", "destroy", "summon"):
        assert len({effects[f"{event}-{color}"]["file"] for color in colors}) == 7, event
    for color in colors:
        assert effects[f"block-{color}"]["file"] != effects[f"destroy-{color}"]["file"], color
    destruction_files = {effects[f"destroy-{color}"]["file"] for color in colors}
    for name in ("hit", "force-hit"):
        assert effects[name]["file"] not in destruction_files
        assert effects[name]["durationMs"] == 340
    for name, definition in manifest["effects"].items():
        effect_path = _package_path(root, definition["file"])
        assert definition["file"] in packaged_files, f"effect binary is not hashed: {name}"
        assert effect_path.is_file(), f"effect binary is missing: {name}"
        references = resources(effect_path)
        for kind in ("sound", "model", "material"):
            assert not references[kind], f"{name} unexpectedly references {kind}: {references[kind]}"

        source_resources = {
            reference
            for kind in ("texture", "normal", "distortion")
            for reference in references[kind]
        }
        mapped_resources = definition["resources"]
        assert set(mapped_resources) == source_resources, (
            f"resource mapping mismatch for {name}: "
            f"missing={sorted(source_resources - set(mapped_resources))}, "
            f"extra={sorted(set(mapped_resources) - source_resources)}"
        )
        for source, packaged in mapped_resources.items():
            target = _package_path(root, packaged)
            assert target.is_file(), f"{name} resource {source} is missing: {packaged}"
            assert packaged in packaged_files, f"{name} resource is not hashed: {packaged}"

    assert not any(Path(name).suffix.lower() in {".efkmodel", ".model"} for name in packaged_files), (
        "FX package must not contain model files"
    )


@pytest.fixture(scope="module")
def duel_fx_fixture(tmp_path_factory):
    temporary = tmp_path_factory.mktemp("duel-fx-fixture")
    session = GameSession(seed=123, mode="god", opponent_ai_difficulty="easy")
    session.choose(session.prompt["id"], "keep")
    session.choose(session.prompt["id"], "keep")
    session.choose(session.prompt["id"], session.prompt["options"][0]["id"])

    main = copy.deepcopy(session.state_dto())
    human = main["players"]["human"]
    opponent = main["players"]["opponent"]
    assert human["hand"], "the deterministic main snapshot must have a human hand card"

    public_card = copy.deepcopy(human["hand"][0])
    public_card["iid"] = max(int(card["iid"]) for card in human["hand"] if card.get("iid")) + 100000
    public_card["area"] = "field"
    public_card["faceDown"] = False
    human["field"].append(public_card)

    for index, hidden in enumerate(opponent["hand"]):
        opponent["hand"][index] = {
            "ownerSide": opponent["side"],
            "faceDown": True,
            "assetId": "card_back",
            "assetUrl": "/assets/card_back",
            "area": "hand",
            "rested": bool(hidden.get("rested", False)),
        }

    # Keep a rendered board animation layer beside an effect overlay so the
    # integration check can verify both event-owned roots across a real rerender.
    main["pendingAttack"] = {
        "side": human["side"],
        "attackerIid": public_card["iid"],
        "targetSide": opponent["side"],
        "targetKind": "player",
        "attacker": public_card,
    }

    app_state = ServerState(
        session=session,
        deck_root=temporary / "decks",
        settings_root=temporary / "settings",
        ai_data_root=temporary,
    )
    catalog = app_state.catalog()
    catalog["uiAssets"]["button_turn_end"] = (
        "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='110' height='110'/%3E"
    )

    class Handler(ZenonzardHandler):
        test_document = ""

        def do_GET(self) -> None:
            if urlparse(self.path).path == "/__duel_fx_test__":
                body = self.test_document.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)
                return
            super().do_GET()

    Handler.app = app_state
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        origin = f"http://127.0.0.1:{server.server_port}"
        yield {
            "origin": origin,
            "fixture": {
                "catalog": catalog,
                "main": main,
                "publicFieldCardIid": public_card["iid"],
                "publicFieldCardBp": public_card.get("effectiveBp", public_card.get("bp")),
                "publicFieldCardDp": public_card.get("effectiveDp", public_card.get("dp")),
                "hiddenHandCount": len(opponent["hand"]),
            },
            "handler": Handler,
        }
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _run_chrome(duel_fx_fixture, tmp_path, *, motion_flag: str) -> dict:
    origin = duel_fx_fixture["origin"]
    fixture = json.dumps(duel_fx_fixture["fixture"], ensure_ascii=False).replace("<", "\\u003c")
    child = r'''<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<base href="ORIGIN/"><link rel="stylesheet" href="/static/styles.css">
<link rel="stylesheet" href="/static/fx.css"></head>
<body><main id="app" class="app duel-app"></main>
<script>window.ZZ_DEFER_BOOT=true;</script>
<script src="/static/api-client.js"></script>
<script src="/static/multiplayer-card-policy.js"></script>
<script src="/static/duel-layout.js"></script>
<script src="/static/duel-dom.js"></script>
<script src="/static/fx-core.js"></script>
<script src="/static/app.js"></script>
<script>
window.__browserErrors = [];
window.addEventListener("error", event => {
  if (event.target === window) window.__browserErrors.push(event.message || String(event.error || "script error"));
}, true);
window.addEventListener("unhandledrejection", event => {
  window.__browserErrors.push(String(event.reason && event.reason.stack || event.reason));
});
const postResult = value => parent.postMessage({
  fxPayload: btoa(unescape(encodeURIComponent(JSON.stringify(value))))
}, "*");
(async () => {
  const fixture = FIXTURE;
  const assert = (condition, message) => { if (!condition) throw new Error(message); };
  const delay = milliseconds => new Promise(resolve => setTimeout(resolve, milliseconds));
  const waitFor = async (predicate, message, timeout = 22000) => {
    const started = performance.now();
    while (performance.now() - started < timeout) {
      const inspect = window.ZZFx.inspect();
      if (inspect.errors.length) throw new Error("FX runtime errors: " + inspect.errors.join(" | "));
      if (predicate(inspect)) return inspect;
      await delay(35);
    }
    throw new Error("Timed out waiting for " + message + ": " + JSON.stringify({
      inspect: window.ZZFx.inspect(),
      reduced: matchMedia("(prefers-reduced-motion: reduce)").matches,
      hidden: document.hidden,
      visibility: document.visibilityState,
      board: Boolean(app.querySelector(".duel-board")),
      fxClass: app.className,
    }));
  };
  const cardByIid = iid => document.querySelector('[data-board-card-anchor="' +
    fixture.main.humanSide + ':card:' + iid + '"]');
  catalog = fixture.catalog;
  state = fixture.main;
  appView = "duel";
  settings.duelScale = 100;
  settings.reducedMotion = false;
  setAppHtml(renderDuelView());
  await document.fonts.ready;

  const publicField = cardByIid(fixture.publicFieldCardIid);
  assert(publicField, "copied public field card must render from the real main snapshot");
  const hidden = Array.from(app.querySelectorAll('.cockpit.top .card[data-fx-face="down"]'));
  assert(hidden.length === fixture.hiddenHandCount, "opponent hand must render as face-down cards");
  assert(hidden.every(card => card.getAttribute("data-rarity") === "" &&
    !card.querySelector(".card-fx") && !card.hasAttribute("data-board-card-anchor") &&
    !card.hasAttribute("data-card-iid")),
    "hidden opponent cards must contain no rarity, foil node, or IID anchor");
  assert(hidden.every(card => card.querySelector("img")?.alt === "CARD"),
    "hidden opponent cards must only render the neutral card-back label");
  const visibleStats = publicField.querySelector(".card-field-stats, .card-stats");
  assert(visibleStats && visibleStats.textContent.includes(String(fixture.publicFieldCardBp)) &&
    visibleStats.textContent.includes(String(fixture.publicFieldCardDp)) &&
    getComputedStyle(visibleStats).display !== "none",
    "public BP/DP values must remain statically readable");

  await waitFor(inspect => inspect.ready && inspect.loadedEffects === 20,
    "Effekseer runtime and twenty original effect binaries");
  const initialFx = window.ZZFx.inspect();
  assert(initialFx.errors.length === 0, "FX runtime errors must be empty");
  assert(matchMedia("(prefers-reduced-motion: reduce)").matches === false,
    "full-motion browser run must use no-preference mode");

  const event = {
    type: "effect", side: fixture.main.humanSide,
    card: fixture.main.players.human.field.find(card => card.iid === fixture.publicFieldCardIid),
    effectText: "FX integration event",
  };
  ZZFx.onEventStart(event, 2200);
  activeAnimationEvent = event;
  setAppHtml(renderDuelView());
  const board = app.querySelector(".duel-board");
  const layer = app.querySelector(".board-animation-layer");
  const overlay = app.querySelector(".visual-overlay");
  const canvas = app.querySelector("canvas.fx-canvas[data-fx-owned]");
  assert(board && layer && overlay && canvas, "live duel must mount the board, both event roots and owned canvas");
  assert(layer.getAttribute("data-fx-event") &&
    layer.getAttribute("data-fx-event") === overlay.getAttribute("data-fx-event"),
    "board animation layer and overlay must belong to the same active event");
  await delay(550);
  const beforeSelectionHtml = app.innerHTML;
  selectedCardIid = fixture.publicFieldCardIid;
  setAppHtml(renderDuelView());
  assert(app.innerHTML !== beforeSelectionHtml && app.querySelector(".card-detail-modal"),
    "opening a card detail must change rendered HTML during the active event");
  assert(app.querySelector(".duel-board") === board &&
    app.querySelector(".board-animation-layer") === layer &&
    app.querySelector(".visual-overlay") === overlay &&
    app.querySelector("canvas.fx-canvas[data-fx-owned]") === canvas,
    "same-event rerender and selection must preserve canvas, animation layer and overlay references");
  assert(layer.querySelector(".board-attack.persistent"),
    "event animation layer subtree must remain present through the rerender");
  assert(!ZZFx.inspect().activeHandles, "effect explanation must not play activation particles");
  ZZFx.onEventEnd(event);
  const targetEvent = {type: "effect_target", side: fixture.main.humanSide,
    targetSide: event.card.ownerSide, targetKind: "card", targetCardIid: event.card.iid};
  ZZFx.onEventStart(targetEvent, 2200); activeAnimationEvent = targetEvent; setAppHtml(renderDuelView());
  const activeFx = await waitFor(inspect => inspect.activeHandles > 0 && inspect.running,
    "an active particle handle to queue and wake the renderer");
  assert(activeFx.activeHandles > 0, "active event must own a live effect handle before ending");

  ZZFx.onEventEnd(targetEvent);
  activeAnimationEvent = null;
  animationEventQueue.length = 0;
  stagedDuelStateQueue.length = 0;
  visualStateStaged = false;
  selectedCardIid = null;
  state.pendingAttack = null;
  setAppHtml(renderDuelView());
  const endedFx = ZZFx.inspect();
  assert(endedFx.activeHandles === 0 && endedFx.running === false,
    "onEventEnd and queue cleanup must stop active handles and the FX rAF loop");

  const drawEvent = { type: "draw", side: fixture.main.humanSide, count: 1 };
  ZZFx.onEventStart(drawEvent, 1800);
  activeAnimationEvent = drawEvent;
  setAppHtml(renderDuelView());
  const interruptedFlight = app.querySelector(".board-draw-card");
  assert(interruptedFlight && interruptedFlight.classList.contains("fx-flight") &&
    interruptedFlight.getAnimations().some(animation => animation.playState === "running"),
    "draw event must start a real browser card flight before interruption");
  ZZFx.onEventEnd(drawEvent);
  assert(interruptedFlight.style.opacity === "0",
    "an interrupted flight must be hidden before cancellation can reveal its source position");
  activeAnimationEvent = null;
  animationEventQueue.length = 0;
  state.pendingAttack = null;
  setAppHtml(renderDuelView());
  assert(!interruptedFlight.isConnected && !app.querySelector(".board-draw-card.fx-flight") &&
    ZZFx.inspect().activeHandles === 0 && ZZFx.inspect().running === false,
    "an interrupted draw flight must not return to its source or leave active work");

  // The real DTO uses enum names (RED/BLUE/...), not catalog filter keys.
  const attackColors = ["RED", "BLUE", "YELLOW", "GREEN", "PURPLE", "WHITE", "COLORLESS"];
  const effectManifest = await (await fetch("/static/fx/manifest.json")).json();
  assert(attackColors.includes(event.card.manaColor), "fixture must preserve the backend color enum contract");
  for (const manaColor of attackColors) {
    const attackEvent = {type: "attack", side: fixture.main.humanSide,
      attackerIid: event.card.iid, attacker: {...event.card, manaColor},
      targetSide: fixture.main.players.opponent.side, targetKind: "player"};
    ZZFx.onEventStart(attackEvent, 1800);
    activeAnimationEvent = attackEvent;
    setAppHtml(renderDuelView());
    await delay(60);
    assert(!ZZFx.inspect().activeHandles, manaColor + " attack declaration must not invent a hit");
    assert(app.querySelector(".board-attack-projectile.fx-flight"), manaColor + " keeps its real card flight");
    assert(app.querySelector(".board-animation-layer").dataset.fxColor === manaColor.toLowerCase(),
      manaColor + " preserves its public attack color");
    ZZFx.onEventEnd(attackEvent);
  }
  activeAnimationEvent = null;
  setAppHtml(renderDuelView());

  for (const type of ["block", "destroy", "zone_move"]) {
    for (const manaColor of attackColors) {
      const card = {...event.card, manaColor};
      const themed = {type, side: fixture.main.humanSide,
        card: type === "destroy" ? {...card, manaColor: manaColor === "YELLOW" ? "COLORLESS" : "YELLOW"} : card,
        sourceCard: {...card, iid: card.iid + 999, ownerSide: fixture.main.players.opponent.side}, cause: "battle",
        cardIid: card.iid,
        blocker: card, blockerIid: card.iid, attacker: card, attackerIid: card.iid,
        attackerSide: fixture.main.humanSide, fromArea: "hand", toArea: "field", summonFx: "hand"};
      const expected = (type === "zone_move" ? "summon" : type) + "-" + manaColor.toLowerCase();
      ZZFx.onEventStart(themed, 1200); activeAnimationEvent = themed; setAppHtml(renderDuelView());
      if (type === "zone_move") {
        await delay(60);
        assert(!ZZFx.inspect().activeHandles, "summoning keeps only its card flight, without landing particles");
        assert(app.querySelector(".board-zone-move-card.fx-flight"), "summoning keeps its real card flight");
        ZZFx.onEventEnd(themed);
        continue;
      }
      await waitFor(inspect => inspect.activeHandles > 0, expected);
      assert(ZZFx.inspect().activeEffects.join(",") === expected, expected + " route");
      assert(app.querySelector(".board-animation-layer").dataset.fxColor === manaColor.toLowerCase(),
        expected + " card and particle color must agree");
      assert(!canvas.style.filter && JSON.stringify(ZZFx.inspect().colorGrade) ===
        JSON.stringify(effectManifest.effects[expected].colorMatrix || [1,0,0,0,1,0,0,0,1]), expected + " grade");
      if (type === "destroy") assert(app.querySelector(".board-destroy-card.fx-dissolving"), expected + " disappearance");
      if (type === "block") {
        const bounds = board.getBoundingClientRect(), anchor = cardByIid(card.iid).getBoundingClientRect();
        const shell = app.querySelector(".board-clash");
        assert(Math.abs(parseFloat(shell.style.getPropertyValue("--mid-x")) / 100 * bounds.width -
          (anchor.left + anchor.width / 2 - bounds.left)) < 1,
          "block cards and particles must share the measured clash center");
      }
      ZZFx.onEventEnd(themed);
    }
  }
  for (const quiet of [
    {type: "zone_move", fromArea: "base", toArea: "field"},
    {type: "zone_move", fromArea: "field", toArea: "base"},
    {type: "zone_move", fromArea: "field", toArea: "field"},
    {type: "zone_move", fromArea: "blessing", toArea: "base"},
    {type: "zone_move", fromArea: "hand", toArea: "trash"},
    {type: "destroy", cause: "replacement"},
    {type: "destroy", cause: "rule"},
  ]) {
    const quietEvent = {...quiet, side: fixture.main.humanSide, card: {...event.card, manaColor: "YELLOW",
      type: quiet.toArea === "base" ? "base_minion" : "field_minion"}};
    const before = ZZFx.inspect().renderedEvents;
    ZZFx.onEventStart(quietEvent, 1200); activeAnimationEvent = quietEvent; setAppHtml(renderDuelView());
    await delay(600);
    assert(ZZFx.inspect().renderedEvents === before && !ZZFx.inspect().activeHandles,
      JSON.stringify(quiet) + " must not invent a summon, mana placement or offensive destruction");
    ZZFx.onEventEnd(quietEvent);
  }
  const hiddenMove = {type: "zone_move", side: fixture.main.humanSide, fromArea: "hand", toArea: "base",
    card: {...event.card, faceDown: true, manaColor: "PURPLE"}, cardIid: event.card.iid};
  ZZFx.onEventStart(hiddenMove, 1200); activeAnimationEvent = hiddenMove; setAppHtml(renderDuelView());
  await delay(60);
  assert(!ZZFx.inspect().activeHandles, "face-down placement has no landing particles");
  assert(app.querySelector(".board-animation-layer").dataset.fxColor === "colorless", "face-down card must not reveal its color");
  ZZFx.onEventEnd(hiddenMove);
  for (const targetKind of ["player", "force"]) {
    const damage = {type: "damage", side: fixture.main.humanSide, targetKind, amount: 2,
      forceId: fixture.main.players.human.forces[0].id, targetSide: fixture.main.humanSide};
    ZZFx.onEventStart(damage, 1200); activeAnimationEvent = damage; setAppHtml(renderDuelView());
    await waitFor(inspect => inspect.activeHandles > 0, targetKind + " damage");
    assert(ZZFx.inspect().activeEffects.join(",") === (targetKind === "force" ? "force-hit" : "hit"), "damage route");
    ZZFx.onEventEnd(damage);
  }
  activeAnimationEvent = null;
  setAppHtml(renderDuelView());

  const beforeReducedRenderCount = ZZFx.inspect().renderedEvents;
  settings.reducedMotion = true;
  const reducedEvent = { type: "effect_target", side: fixture.main.humanSide,
    targetKind: "card", targetSide: event.card.ownerSide, targetCardIid: event.card.iid };
  ZZFx.onEventStart(reducedEvent, 1200);
  activeAnimationEvent = reducedEvent;
  setAppHtml(renderDuelView());
  const handCard = app.querySelector('.cockpit.bottom .hand-fan .card[data-fx-face="up"]');
  assert(handCard, "reduced motion fixture must render a visible hand card: " +
    JSON.stringify({hands: app.querySelectorAll(".hand-fan").length,
      cards: app.querySelectorAll(".card[data-fx-face]").length, body: app.innerHTML.slice(0, 1800)}));
  const handRect = handCard.getBoundingClientRect();
  handCard.dispatchEvent(new PointerEvent("pointermove", {
    bubbles: true, clientX: handRect.left + handRect.width / 2,
    clientY: handRect.top + handRect.height / 2, pointerType: "mouse",
  }));
  await delay(550);
  const reducedFx = ZZFx.inspect();
  const staticStats = cardByIid(fixture.publicFieldCardIid).querySelector(".card-field-stats, .card-stats");
  assert(app.classList.contains("fx-reduced"), "the in-app reduced-motion setting must activate static mode");
  assert(reducedFx.activeHandles === 0 && reducedFx.running === false &&
    reducedFx.renderedEvents === beforeReducedRenderCount,
    "in-app reduced motion must not create or run particles");
  assert(!handCard.classList.contains("fx-tilting") &&
    !handCard.style.getPropertyValue("--fx-rx") && !handCard.style.getPropertyValue("--fx-ry"),
    "in-app reduced motion must not generate card tilt");
  assert(staticStats && staticStats.textContent.includes(String(fixture.publicFieldCardBp)) &&
    staticStats.textContent.includes(String(fixture.publicFieldCardDp)) &&
    getComputedStyle(staticStats).display !== "none",
    "in-app reduced motion must preserve readable static card values");
  assert(window.__browserErrors.length === 0 && ZZFx.inspect().errors.length === 0,
    "browser and FX runtime errors must remain empty: " + window.__browserErrors.join(" | "));

  ZZFx.onEventEnd(reducedEvent);
  activeAnimationEvent = null;
  animationEventQueue.length = 0;
  state.pendingAttack = null;
  selectedCardIid = null;
  appView = "home";
  app.className = "app shell-app";
  setAppHtml("<section class=\"fx-test-home\">home</section>");
  const framesOnExit = ZZFx.inspect().frames;
  await delay(180);
  const exitedFx = ZZFx.inspect();
  assert(!app.querySelector("canvas.fx-canvas") && !canvas.isConnected,
    "leaving duel must remove the player-owned FX canvas");
  assert(exitedFx.activeHandles === 0 && exitedFx.running === false && exitedFx.frames === framesOnExit,
    "leaving duel must leave no FX handles or running rAF frames");

  return {
    ok: true,
    loadedEffects: initialFx.loadedEffects,
    ready: initialFx.ready,
    renderedEvents: activeFx.renderedEvents,
    activeHandlesAfterEnd: endedFx.activeHandles,
    fxFramesAfterExit: exitedFx.frames,
    hiddenCards: hidden.length,
  };
})().then(postResult).catch(error => postResult({error: String(error && error.stack || error)}));
</script></body></html>'''
    child = child.replace("ORIGIN", origin).replace("const fixture = FIXTURE;", f"const fixture = {fixture};")
    outer = '''<!doctype html><html><head><meta charset="utf-8"><script>
addEventListener("message", ({data}) => {
  if (!data.fxPayload) return;
  const result = document.createElement("script");
  result.id = "fx-result"; result.type = "application/json";
  result.textContent = data.fxPayload; document.body.append(result);
});
</script></head><body><iframe width="1280" height="900" style="border:0" srcdoc="CHILD"></iframe></body></html>'''
    outer = outer.replace("CHILD", html_escape.escape(child, quote=True))
    duel_fx_fixture["handler"].test_document = outer

    profile = tmp_path / "chrome-profile"
    profile.mkdir(parents=True, exist_ok=True)
    command = [
        BROWSER,
        "--headless=new", "--no-first-run", "--no-default-browser-check",
        "--disable-breakpad", "--disable-crash-reporter", "--disable-extensions", "--no-sandbox",
        "--enable-webgl", "--ignore-gpu-blocklist", "--use-gl=angle",
        "--use-angle=swiftshader", "--enable-unsafe-swiftshader",
        "--force-device-scale-factor=1", "--window-size=1280,900",
        "--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1",
        *(["--force-prefers-reduced-motion=reduce"] if motion_flag == "reduce" else []),
        f"--user-data-dir={profile}", "--virtual-time-budget=30000", "--dump-dom",
        f"{duel_fx_fixture['origin']}/__duel_fx_test__?run={tmp_path.name}",
    ]
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=70,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    assert result.returncode == 0, result.stdout[-3000:] + result.stderr[-1500:]
    match = re.search(r'<script id="fx-result" type="application/json">([^<]+)</script>', result.stdout)
    assert match, result.stdout[-3000:] + result.stderr[-1500:]
    payload = json.loads(base64.b64decode(match[1]).decode("utf-8"))
    assert "error" not in payload, payload["error"]
    assert payload.get("ok") is True, payload
    return payload


def test_duel_fx_runtime_identity_lifecycle_and_reduced_setting(duel_fx_fixture, tmp_path):
    if BROWSER is None:
        pytest.skip("headless Chrome/Chromium is required for real browser FX integration")
    result = _run_chrome(duel_fx_fixture, tmp_path, motion_flag="no-preference")
    assert result["ready"] is True and result["loadedEffects"] == 20, result
    assert result["activeHandlesAfterEnd"] == 0, result
    assert result["hiddenCards"] == duel_fx_fixture["fixture"]["hiddenHandCount"], result


@pytest.mark.parametrize("check", ["damage", "rested"])
def test_one_damage_impact_and_opaque_rested_cards(duel_fx_fixture, tmp_path, check):
    if BROWSER is None:
        pytest.skip("headless Chrome/Chromium is required for real browser FX integration")
    child = r'''<!doctype html><html><head><meta charset="utf-8"><base href="ORIGIN/">
<link rel="stylesheet" href="/static/styles.css"><link rel="stylesheet" href="/static/fx.css"></head>
<body><main id="app" class="app duel-app"></main><script>window.ZZ_DEFER_BOOT=true;
window.requestAnimationFrame=callback=>setTimeout(()=>callback(performance.now()),16);
window.cancelAnimationFrame=clearTimeout;</script>
<script src="/static/api-client.js"></script><script src="/static/multiplayer-card-policy.js"></script>
<script src="/static/duel-layout.js"></script><script src="/static/duel-dom.js"></script>
<script src="/static/fx-core.js"></script><script src="/static/app.js"></script><script>
const postResult=value=>parent.postMessage({fxPayload:btoa(unescape(encodeURIComponent(JSON.stringify(value))))},"*");
(async()=>{
  const fixture=FIXTURE,check="CHECK";
  const assert=(condition,message)=>{if(!condition)throw new Error(message);};
  const delay=ms=>new Promise(resolve=>setTimeout(resolve,ms));
  catalog=fixture.catalog;state=fixture.main;appView="duel";settings.reducedMotion=false;state.pendingAttack=null;
  const human=state.players.human,card=human.field[0];
  if(check==="rested"){
    card.rested=true;human.base[0].rested=true;human.forces[0].rested=true;
  }
  setAppHtml(renderDuelView());await ZZFx.prepare();
  if(check==="rested"){
    for(const reduced of [false,true]){
      settings.reducedMotion=reduced;setAppHtml(renderDuelView());
      const rested=app.querySelectorAll(".card.rested, .force.rested:not(.destroyed)");
      assert(rested.length>=3,"field, Base and Force must all render rested");
      for(const el of rested){
        assert(getComputedStyle(el).opacity==="1","rested cards must keep full opacity: "+el.className);
        assert(getComputedStyle(el).transform!=="none","rested rotation remains visible");
      }
      const preview=document.createElement("div");
      preview.innerHTML=renderEffectPromptCard({...card,rested:true},{id:"rested-preview"},0);
      app.append(preview);
      assert(getComputedStyle(preview.querySelector("img")).opacity==="1","rested choice preview must keep full opacity");
      preview.remove();
    }
    return {ok:true};
  }
  const start=event=>{ZZFx.onEventStart(event,1200);activeAnimationEvent=event;setAppHtml(renderDuelView());};
  const end=event=>{ZZFx.onEventEnd(event);activeAnimationEvent=null;setAppHtml(renderDuelView());};
  for(const targetKind of ["player","force"]){
    const attack={type:"attack",side:human.side,attacker:card,attackerIid:card.iid,targetKind,
      targetSide:human.side,targetForceId:human.forces[0].id};
    start(attack);await delay(450);
    assert(ZZFx.inspect().activeHandles===0,"attack declaration must not hit the life target before damage resolves");
    assert(!app.querySelector(".board-attack:not(.persistent) .board-attack-impact, .board-attack:not(.persistent) .board-attack-target-ring"),
      "attack declaration must not substitute a CSS impact flash");
    assert(app.querySelector(".board-attack-projectile"),"attack declaration keeps its card flight");
    end(attack);
    for(let hit=0;hit<2;hit++){
      const before=ZZFx.inspect().renderedEvents;
      const damage={type:"damage",side:human.side,targetKind,forceId:human.forces[0].id,amount:1};
      start(damage);await delay(100);
      assert(ZZFx.inspect().activeEffects.join(",")===(targetKind==="force"?"force-hit":"hit"),"damage owns one localized hit");
      assert(ZZFx.inspect().renderedEvents===before+1,"each real damage event must play once");
      setAppHtml(renderDuelView());await delay(80);
      assert(ZZFx.inspect().renderedEvents===before+1,"rerender must not replay the same damage");
      assert(app.querySelectorAll(".board-life-float.damage").length===1,"one exact damage number stays visible");
      end(damage);
    }
  }
  return {ok:true};
})().then(postResult).catch(error=>postResult({error:String(error&&error.stack||error)}));
</script></body></html>'''
    _run_fx_test_page(duel_fx_fixture, tmp_path, child.replace("CHECK", check))


def test_effect_explanations_are_quiet_and_target_fx_use_exact_public_anchors(duel_fx_fixture, tmp_path):
    if BROWSER is None:
        pytest.skip("headless Chrome/Chromium is required for real browser FX integration")
    child = r'''<!doctype html><html><head><meta charset="utf-8"><base href="ORIGIN/">
<link rel="stylesheet" href="/static/styles.css"><link rel="stylesheet" href="/static/fx.css"></head>
<body><main id="app" class="app duel-app"></main><script>window.ZZ_DEFER_BOOT=true;</script>
<script src="/static/api-client.js"></script><script src="/static/multiplayer-card-policy.js"></script>
<script src="/static/duel-layout.js"></script><script src="/static/duel-dom.js"></script>
<script src="/static/fx-core.js"></script><script src="/static/app.js"></script><script>
const postResult=value=>parent.postMessage({fxPayload:btoa(unescape(encodeURIComponent(JSON.stringify(value))))},"*");
(async()=>{
  const fixture=FIXTURE;
  const assert=(condition,message)=>{if(!condition)throw new Error(message);};
  const delay=ms=>new Promise(resolve=>setTimeout(resolve,ms));
  catalog=fixture.catalog;state=fixture.main;appView="duel";settings.duelScale=100;settings.reducedMotion=false;
  state.pendingAttack=null;setAppHtml(renderDuelView());
  await ZZFx.prepare();
  const start=event=>{ZZFx.onEventStart(event,1800);activeAnimationEvent=event;setAppHtml(renderDuelView());};
  const end=event=>{ZZFx.onEventEnd(event);activeAnimationEvent=null;setAppHtml(renderDuelView());};
  const field=state.players.human.field[0],base=state.players.human.base[0];
  for(const area of ["hand","field","trash"]){
    const event={type:"effect",side:field.ownerSide,card:{...field,type:"magic",area},
      effectTextZh:"Read this effect",effectTextJp:"Read this effect",effectTextEn:"Read this effect"};
    const before=ZZFx.inspect().renderedEvents;
    start(event);await delay(120);
    assert(app.querySelector(".effect-trigger-copy").textContent.includes("Read this effect"),"effect explanation stays readable");
    assert(!ZZFx.inspect().activeHandles&&ZZFx.inspect().renderedEvents===before,
      area+": explaining an effect must not activate particles on the card or the field center");
    end(event);
  }
  const enemy={...field,iid:field.iid+20000,ownerSide:state.players.opponent.side};
  state.players.opponent.field.push(enemy);setAppHtml(renderDuelView());
  for(const card of [field,base,enemy]){
    const event={type:"effect_target",side:field.ownerSide,sourceCard:{...field,type:"magic",area:"trash"},
      targetKind:"card",targetCardIid:card.iid,targetSide:card.ownerSide,targetArea:card.area};
    start(event);await delay(120);
    const origin=ZZFx.inspect().activeOrigins?.[0];
    assert(origin?.name==="target","a real affected card must receive the target effect");
    const board=app.querySelector(".duel-board").getBoundingClientRect();
    const target=app.querySelector(`[data-board-card-anchor="${card.ownerSide}:card:${card.iid}"]`).getBoundingClientRect();
    assert(Math.abs(origin.x-(target.left+target.width/2-board.left)/board.width)<.002&&
      Math.abs(origin.y-(target.top+target.height/2-board.top)/board.height)<.002,
      "target particle origin must match the affected card's measured center");
    const marker=app.querySelector(".board-effect-target").getBoundingClientRect();
    assert(Math.abs(marker.left+marker.width/2-target.left-target.width/2)<1&&
      Math.abs(marker.top+marker.height/2-target.top-target.height/2)<1,"CSS target marker shares the same actual card center");
    assert(!app.querySelector(".effect-trigger-overlay"),"target resolution does not replay the effect explanation");
    end(event);
  }
  const before=ZZFx.inspect().renderedEvents;
  const missing={type:"effect_target",side:field.ownerSide,targetKind:"card",targetSide:field.ownerSide,targetCardIid:999999};
  start(missing);await delay(120);
  assert(!ZZFx.inspect().activeHandles&&ZZFx.inspect().renderedEvents===before,"missing target never falls back to the field center");
  assert(!app.querySelector(".board-effect-target"),"missing target must not leave a CSS marker at the field center");
  assert(ZZFx.inspect().errors.some(error=>error.includes("effect target anchor")),"missing target anchor must be observable");
  end(missing);return {ok:true};
})().then(postResult).catch(error=>postResult({error:String(error&&error.stack||error)}));
</script></body></html>'''
    _run_fx_test_page(duel_fx_fixture, tmp_path, child)


def _run_fx_test_page(duel_fx_fixture, tmp_path, child_template: str, *, motion_flag: str = "no-preference") -> dict:
    origin = duel_fx_fixture["origin"]
    fixture = json.dumps(duel_fx_fixture["fixture"], ensure_ascii=False).replace("<", "\\u003c")
    child = child_template.replace("ORIGIN", origin).replace("FIXTURE", fixture)
    outer = '''<!doctype html><html><head><meta charset="utf-8"><script>
addEventListener("message", ({data}) => { if (!data.fxPayload) return;
  const result=document.createElement("script"); result.id="fx-result";
  result.type="application/json"; result.textContent=data.fxPayload; document.body.append(result); });
</script></head><body><iframe width="1280" height="900" style="border:0" srcdoc="CHILD"></iframe></body></html>'''
    duel_fx_fixture["handler"].test_document = outer.replace("CHILD", html_escape.escape(child, quote=True))
    profile = tmp_path / "chrome-profile"
    profile.mkdir(parents=True, exist_ok=True)
    command = [
        BROWSER, "--headless=new", "--no-first-run", "--no-default-browser-check",
        "--disable-breakpad", "--disable-crash-reporter", "--disable-extensions", "--no-sandbox",
        "--enable-webgl", "--ignore-gpu-blocklist", "--use-gl=angle",
        "--use-angle=swiftshader", "--enable-unsafe-swiftshader",
        "--force-device-scale-factor=1", "--window-size=1280,900",
        "--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1",
        *( ["--force-prefers-reduced-motion=reduce"] if motion_flag == "reduce" else [] ),
        f"--user-data-dir={profile}", "--virtual-time-budget=30000", "--dump-dom",
        f"{origin}/__duel_fx_test__?run={tmp_path.name}",
    ]
    result = subprocess.run(
        command, capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=70, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    assert result.returncode == 0, result.stdout[-3000:] + result.stderr[-1500:]
    match = re.search(r'<script id="fx-result" type="application/json">([^<]+)</script>', result.stdout)
    assert match, result.stdout[-3000:] + result.stderr[-1500:]
    payload = json.loads(base64.b64decode(match[1]).decode("utf-8"))
    assert "error" not in payload, payload.get("error")
    assert payload.get("ok") is True, payload
    return payload


def test_duel_fx_no_webgl_resize_is_guarded(duel_fx_fixture, tmp_path):
    if BROWSER is None:
        pytest.skip("headless Chrome/Chromium is required for real browser FX integration")
    child = r'''<!doctype html><html><head><meta charset="utf-8"><base href="ORIGIN/">
<link rel="stylesheet" href="/static/styles.css"><link rel="stylesheet" href="/static/fx.css"></head>
<body><main id="app" class="app duel-app"></main>
<script>window.ZZ_DEFER_BOOT=true;
const nativeGetContext=HTMLCanvasElement.prototype.getContext;
HTMLCanvasElement.prototype.getContext=function(type,...args){
  return type==="webgl"||type==="webgl2" ? null : nativeGetContext.call(this,type,...args);
};</script>
<script src="/static/api-client.js"></script><script src="/static/multiplayer-card-policy.js"></script>
<script src="/static/duel-layout.js"></script><script src="/static/duel-dom.js"></script>
<script src="/static/fx-core.js"></script><script src="/static/app.js"></script><script>
window.__browserErrors=[];
window.addEventListener("error",event=>{if(event.target===window)window.__browserErrors.push(event.message||String(event.error));},true);
window.addEventListener("unhandledrejection",event=>window.__browserErrors.push(String(event.reason&&event.reason.stack||event.reason)));
const postResult=value=>parent.postMessage({fxPayload:btoa(unescape(encodeURIComponent(JSON.stringify(value))))},"*");
(async()=>{
  const fixture=FIXTURE;
  const assert=(condition,message)=>{if(!condition)throw new Error(message);};
  const delay=milliseconds=>new Promise(resolve=>setTimeout(resolve,milliseconds));
  catalog=fixture.catalog;state=fixture.main;appView="duel";settings.duelScale=100;settings.reducedMotion=false;
  setAppHtml(renderDuelView());
  const deadline=performance.now()+18000;
  while(!ZZFx.inspect().errors.length&&performance.now()<deadline)await delay(30);
  assert(ZZFx.inspect().errors.some(message=>/WebGL unavailable/i.test(message)),
    "the real browser must report its deliberately unavailable WebGL capability");
  for(let index=0;index<4;index++){
    ZZFx.afterRender(app,{live:true,reducedMotion:false,humanSide:fixture.main.humanSide});
    dispatchEvent(new Event("resize"));
  }
  await delay(100);
  const inspect=ZZFx.inspect();
  assert(!inspect.errors.some(message=>/TypeError|Cannot read properties|null.*(width|height|viewport)/i.test(message)),
    "a missing WebGL context must not make resize throw: "+inspect.errors.join(" | "));
  assert(inspect.activeHandles===0&&inspect.running===false&&!document.querySelector("canvas.fx-canvas"),
    "unsupported WebGL must leave no particles, RAF, or detached player canvas");
  assert(window.__browserErrors.length===0,"browser-level errors: "+window.__browserErrors.join(" | "));
  return {ok:true,webglUnavailable:true,errors:inspect.errors};
})().then(postResult).catch(error=>postResult({error:String(error&&error.stack||error)}));
</script></body></html>'''
    result = _run_fx_test_page(duel_fx_fixture, tmp_path, child)
    assert result["webglUnavailable"] is True, result


def test_duel_fx_gpu_grade_preserves_additive_light_and_smoke_alpha(duel_fx_fixture, tmp_path):
    if BROWSER is None:
        pytest.skip("headless Chrome/Chromium is required for real WebGL pixel checks")
    child = r'''<!doctype html><html><head><meta charset="utf-8"><base href="ORIGIN/">
<link rel="stylesheet" href="/static/styles.css"><link rel="stylesheet" href="/static/fx.css"></head>
<body><main id="app" class="app duel-app"></main><script>window.ZZ_DEFER_BOOT=true;
// Keep the real GPU renderer, but give virtual-time Chrome a deterministic frame clock.
window.requestAnimationFrame=callback=>setTimeout(()=>callback(performance.now()),16);
window.cancelAnimationFrame=clearTimeout;
window.__gpuCounters={draws:0,stateQueries:0};
const append=document.head.append.bind(document.head);document.head.append=(...nodes)=>{
  for(const node of nodes)if(node.tagName==="SCRIPT"&&node.src.endsWith("effekseer.min.js")){
    node.addEventListener("load",()=>{
      const createContext=effekseer.createContext.bind(effekseer);
      effekseer.createContext=()=>{
        const context=createContext(),init=context.init.bind(context),draw=context.draw.bind(context);
        let drawing=false;
        context.init=(gl,...args)=>{
          const result=init(gl,...args),getParameter=gl.getParameter.bind(gl);
          gl.getParameter=parameter=>{
            if(drawing&&[gl.DEPTH_FUNC,gl.CULL_FACE_MODE].includes(parameter))window.__gpuCounters.stateQueries++;
            return getParameter(parameter);
          };
          return result;
        };
        context.draw=(...args)=>{
          drawing=true;window.__gpuCounters.draws++;
          try{return draw(...args);}finally{drawing=false;}
        };
        return context;
      };
    });
  }
  return append(...nodes);
};
</script><script src="/static/api-client.js"></script><script src="/static/multiplayer-card-policy.js"></script>
<script src="/static/duel-layout.js"></script><script src="/static/duel-dom.js"></script>
<script src="/static/fx-core.js"></script><script src="/static/app.js"></script><script>
const postResult=value=>parent.postMessage({fxPayload:btoa(unescape(encodeURIComponent(JSON.stringify(value))))},"*");
(async()=>{
  const fixture=FIXTURE,delay=ms=>new Promise(r=>setTimeout(r,ms));
  const assert=(condition,message)=>{if(!condition)throw Error(message);};
  catalog=fixture.catalog;state=fixture.main;appView="duel";settings.reducedMotion=false;
  setAppHtml(renderDuelView());
  await ZZFx.prepare();
  assert(ZZFx.inspect().ready,"FX readiness: "+JSON.stringify(ZZFx.inspect()));
  const canvas=document.querySelector(".fx-canvas"),gl=canvas.getContext("webgl");
  const bind=gl.bindFramebuffer.bind(gl),draw=gl.drawArrays.bind(gl);
  let raw=null,mode="",light=0,smoke=0,identityPixels=0,maxAlphaError=0,maxRgbError=0,nextRead=0;
  gl.bindFramebuffer=(target,value)=>{
    if(value===null&&gl.getParameter(gl.FRAMEBUFFER_BINDING)){
      // Sample complete native frames throughout both effects. Scanning every
      // full-resolution frame makes readback instrumentation dominate the test.
      raw=null;
      if(performance.now()>=nextRead){
        nextRead=performance.now()+180;
        raw=new Uint8Array(canvas.width*canvas.height*4);
        gl.readPixels(0,0,canvas.width,canvas.height,gl.RGBA,gl.UNSIGNED_BYTE,raw);
      }
    }
    bind(target,value);
  };
  gl.drawArrays=(...args)=>{
    draw(...args);
    if(gl.getParameter(gl.FRAMEBUFFER_BINDING)||!raw)return;
    const out=new Uint8Array(raw.length);
    gl.readPixels(0,0,canvas.width,canvas.height,gl.RGBA,gl.UNSIGNED_BYTE,out);
    let luminous=0,normal=0,identity=0;
    for(let i=0;i<raw.length;i+=4){
      maxAlphaError=Math.max(maxAlphaError,Math.abs(raw[i+3]-out[i+3]));
      if(raw[i+3]===0&&Math.max(raw[i],raw[i+1],raw[i+2])>35&&Math.max(out[i],out[i+1],out[i+2])>35)luminous++;
      if(raw[i+3]>15&&raw[i+3]<240)normal++;
      if(mode==="RED"){
        for(let j=0;j<3;j++)maxRgbError=Math.max(maxRgbError,Math.abs(raw[i+j]-out[i+j]));
        if(Math.max(raw[i],raw[i+1],raw[i+2])>35)identity++;
      }
    }
    light=Math.max(light,luminous);smoke=Math.max(smoke,normal);identityPixels=Math.max(identityPixels,identity);
  };
  const card=state.players.human.field[0];
  for(const color of ["WHITE","RED"]){
    mode=color;nextRead=0;
    const event={type:"destroy",side:fixture.main.humanSide,card,
      cause:"effect",sourceCard:{...card,manaColor:color}};
    ZZFx.onEventStart(event,1200);activeAnimationEvent=event;setAppHtml(renderDuelView());
    await delay(800);ZZFx.onEventEnd(event);
  }
  assert(!canvas.style.filter,"CSS filters must not discard transparent emission");
  assert(light>1000,"native additive rays must survive grading: "+light);
  assert(smoke>100,"native translucent alpha must remain present: "+smoke);
  assert(identityPixels>1000&&maxRgbError<=1,"identity grade must preserve native RGB: "+JSON.stringify({identityPixels,maxRgbError}));
  assert(maxAlphaError===0,"grading must preserve every alpha byte: "+maxAlphaError);
  assert(window.__gpuCounters.draws>10&&window.__gpuCounters.stateQueries===0,
    "native draws must not synchronously read back owned GPU state: "+JSON.stringify(window.__gpuCounters));
  assert(gl.getError()===gl.NO_ERROR,"the shared native/postprocess context must have no GL error");
  assert(ZZFx.inspect().errors.length===0,"FX errors: "+JSON.stringify(ZZFx.inspect()));
  return {ok:true,light,smoke,identityPixels,maxAlphaError,maxRgbError};
})().then(postResult).catch(error=>postResult({error:String(error.stack||error)}));
</script></body></html>'''
    result = _run_fx_test_page(duel_fx_fixture, tmp_path, child)
    assert result["light"] > 1000 and result["maxAlphaError"] == 0, result


def test_duel_fx_hidden_event_does_not_resurrect_after_async_load(duel_fx_fixture, tmp_path):
    if BROWSER is None:
        pytest.skip("headless Chrome/Chromium is required for real browser FX integration")
    child = r'''<!doctype html><html><head><meta charset="utf-8"><base href="ORIGIN/">
<link rel="stylesheet" href="/static/styles.css"><link rel="stylesheet" href="/static/fx.css"></head>
<body><main id="app" class="app duel-app"></main>
<script>window.ZZ_DEFER_BOOT=true;
window.__testHidden=false;Object.defineProperty(document,"hidden",{configurable:true,get:()=>window.__testHidden});
Object.defineProperty(document,"visibilityState",{configurable:true,get:()=>window.__testHidden?"hidden":"visible"});
let releaseManifest;window.__manifestReleased=false;window.__manifestFetches=0;
window.__manifestGate=new Promise(resolve=>releaseManifest=resolve);window.__releaseManifest=()=>{window.__manifestReleased=true;releaseManifest();};
const nativeFetch=window.fetch.bind(window);window.fetch=(input,...args)=>{
  const url=typeof input==="string"?input:input.url;
  if(!window.__manifestReleased&&url.endsWith("/static/fx/manifest.json")){
    window.__manifestFetches++;return window.__manifestGate.then(()=>nativeFetch(input,...args));
  }
  return nativeFetch(input,...args);
};</script>
<script src="/static/api-client.js"></script><script src="/static/multiplayer-card-policy.js"></script>
<script src="/static/duel-layout.js"></script><script src="/static/duel-dom.js"></script>
<script src="/static/fx-core.js"></script><script src="/static/app.js"></script><script>
window.__browserErrors=[];
window.addEventListener("error",event=>{if(event.target===window)window.__browserErrors.push(event.message||String(event.error));},true);
window.addEventListener("unhandledrejection",event=>window.__browserErrors.push(String(event.reason&&event.reason.stack||event.reason)));
const postResult=value=>parent.postMessage({fxPayload:btoa(unescape(encodeURIComponent(JSON.stringify(value))))},"*");
(async()=>{
  const fixture=FIXTURE;
  const assert=(condition,message)=>{if(!condition)throw new Error(message);};
  const delay=milliseconds=>new Promise(resolve=>setTimeout(resolve,milliseconds));
  const waitFor=async(predicate,message)=>{
    const deadline=performance.now()+22000;
    while(performance.now()<deadline){const inspect=ZZFx.inspect();
      if(inspect.errors.length)throw new Error("FX runtime errors: "+inspect.errors.join(" | "));
      if(predicate(inspect))return inspect;await delay(35);}
    throw new Error("Timed out waiting for "+message+": "+JSON.stringify(ZZFx.inspect()));
  };
  catalog=fixture.catalog;state=fixture.main;appView="duel";settings.duelScale=100;settings.reducedMotion=false;
  setAppHtml(renderDuelView());
  const manifestDeadline=performance.now()+3000;
  while(!window.__manifestFetches&&performance.now()<manifestDeadline)await delay(20);
  assert(window.__manifestFetches===1,"runtime manifest request must be blocked before the event is scheduled");
  const event={type:"effect_target",side:fixture.main.humanSide,targetSide:fixture.main.humanSide,
    targetKind:"card",targetCardIid:fixture.publicFieldCardIid};
  ZZFx.onEventStart(event,1800);activeAnimationEvent=event;setAppHtml(renderDuelView());
  assert(app.querySelector(".board-effect-target"),"the queued target event must be present in the real duel DOM");
  await delay(100);
  window.__testHidden=true;document.dispatchEvent(new Event("visibilitychange"));await delay(60);
  window.__testHidden=false;document.dispatchEvent(new Event("visibilitychange"));await delay(60);
  window.__releaseManifest();
  await waitFor(inspect=>inspect.phase==="waiting-for-idle","cold initialization to wait for the canceled event's queue slot");
  assert(!ZZFx.inspect().activeHandles&&!ZZFx.inspect().running,"visibility changes must not resume the canceled event");
  ZZFx.onEventEnd(event);activeAnimationEvent=null;animationEventQueue.length=0;state.pendingAttack=null;
  setAppHtml(renderDuelView());
  const loaded=await waitFor(inspect=>inspect.ready&&inspect.loadedEffects===20,"the delayed real FX assets to finish loading");
  await delay(160);
  const afterLateLoad=ZZFx.inspect();
  assert(afterLateLoad.activeHandles===0&&afterLateLoad.running===false&&afterLateLoad.renderedEvents===0,
    "an event canceled while hidden must not queue particles when async loading completes");
  assert(ZZFx.inspect().activeHandles===0&&ZZFx.inspect().running===false,
    "ending the canceled event must leave the FX runtime idle");
  assert(window.__browserErrors.length===0,"browser-level errors: "+window.__browserErrors.join(" | "));
  return {ok:true,loadedEffects:loaded.loadedEffects,canceledHandles:afterLateLoad.activeHandles,
    canceledRaf:afterLateLoad.running,visibilityTransitions:2};
})().then(postResult).catch(error=>postResult({error:String(error&&error.stack||error)}));
</script></body></html>'''
    result = _run_fx_test_page(duel_fx_fixture, tmp_path, child)
    assert result["loadedEffects"] == 20 and result["canceledHandles"] == 0 and result["canceledRaf"] is False, result


def test_duel_fx_cold_initialization_waits_for_the_animation_batch(duel_fx_fixture, tmp_path):
    if BROWSER is None:
        pytest.skip("headless Chrome/Chromium is required for the initialization race")
    child = r'''<!doctype html><html><head><meta charset="utf-8"><base href="ORIGIN/">
<link rel="stylesheet" href="/static/styles.css"><link rel="stylesheet" href="/static/fx.css"></head>
<body><main id="app" class="app duel-app"></main><script>window.ZZ_DEFER_BOOT=true;
let releaseManifest;const manifestGate=new Promise(resolve=>releaseManifest=resolve);
const fetchOriginal=window.fetch.bind(window);window.fetch=(url,...args)=>String(url).endsWith("/fx/manifest.json")
  ?manifestGate.then(()=>fetchOriginal(url,...args)):fetchOriginal(url,...args);
window.__initCalls=[];window.__wasmReady=false;
const append=document.head.append.bind(document.head);document.head.append=(...nodes)=>{
  for(const node of nodes)if(node.tagName==="SCRIPT"&&node.src.endsWith("effekseer.min.js")){
    node.addEventListener("load",()=>{
      const initRuntime=effekseer.initRuntime.bind(effekseer),createContext=effekseer.createContext.bind(effekseer);
      effekseer.initRuntime=(url,ready,failed)=>initRuntime(url,()=>{window.__wasmReady=true;ready();},failed);
      effekseer.createContext=()=>{
        const context=createContext(),init=context.init.bind(context);
        context.init=(...args)=>{window.__initCalls.push({duringEvent:Boolean(activeAnimationEvent)});return init(...args);};
        return context;
      };
    });
  }
  return append(...nodes);
};</script>
<script src="/static/api-client.js"></script><script src="/static/multiplayer-card-policy.js"></script>
<script src="/static/duel-layout.js"></script><script src="/static/duel-dom.js"></script>
<script src="/static/fx-core.js"></script><script src="/static/app.js"></script><script>
const postResult=value=>parent.postMessage({fxPayload:btoa(unescape(encodeURIComponent(JSON.stringify(value))))},"*");
(async()=>{
  const fixture=FIXTURE,delay=ms=>new Promise(resolve=>setTimeout(resolve,ms));
  const assert=(condition,message)=>{if(!condition)throw Error(message);};
  const waitFor=async predicate=>{for(let i=0;i<300;i++){if(predicate())return;await delay(35);}throw Error("initialization timed out");};
  catalog=fixture.catalog;state=fixture.main;appView="duel";settings.reducedMotion=false;
  setAppHtml(renderDuelView());
  const first={type:"zone_move",side:state.humanSide,fromArea:"hand",toArea:"field",
    card:state.players.human.hand[0],summonFx:"hand"};
  ZZFx.onEventStart(first,900);activeAnimationEvent=first;setAppHtml(renderDuelView());
  assert(app.querySelector(".board-zone-move-card.fx-flight"),"cold card motion must start immediately");
  releaseManifest();await waitFor(()=>window.__wasmReady);await delay(50);
  assert(window.__initCalls.length===0,"synchronous GPU initialization must not interrupt a card flight");
  const second={...first};
  ZZFx.onEventEnd(first);ZZFx.onEventStart(second,900);activeAnimationEvent=second;setAppHtml(renderDuelView());
  await delay(50);
  assert(window.__initCalls.length===0,"the gap between two queued events is not an idle board");
  ZZFx.onEventEnd(second);activeAnimationEvent=null;setAppHtml(renderDuelView());
  await ZZFx.prepare();
  assert(window.__initCalls.length===1&&!window.__initCalls[0].duringEvent,"prepare must initialize exactly once after the batch");
  assert(ZZFx.inspect().phase==="ready"&&ZZFx.inspect().ready,"ready means all effects have completed loading");
  assert(ZZFx.inspect().activeHandles===0&&!ZZFx.inspect().running,"completed cold events must never replay late");
  await ZZFx.prepare();assert(window.__initCalls.length===1,"a second prepare must reuse the same context");
  return {ok:true,calls:window.__initCalls};
})().then(postResult).catch(error=>postResult({error:String(error.stack||error)}));
</script></body></html>'''
    result = _run_fx_test_page(duel_fx_fixture, tmp_path, child)
    assert result["calls"] == [{"duringEvent": False}]


def test_duel_fx_os_reduced_motion_keeps_static_cards(duel_fx_fixture, tmp_path):
    if BROWSER is None:
        pytest.skip("headless Chrome/Chromium is required for real browser FX integration")
    origin = duel_fx_fixture["origin"]
    fixture = json.dumps(duel_fx_fixture["fixture"], ensure_ascii=False).replace("<", "\\u003c")
    child = r'''<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><base href="ORIGIN/">
<link rel="stylesheet" href="/static/styles.css"><link rel="stylesheet" href="/static/fx.css"></head>
<body><main id="app" class="app duel-app"></main><script>window.ZZ_DEFER_BOOT=true;</script>
<script src="/static/api-client.js"></script><script src="/static/multiplayer-card-policy.js"></script>
<script src="/static/duel-layout.js"></script><script src="/static/duel-dom.js"></script>
<script src="/static/fx-core.js"></script><script src="/static/app.js"></script><script>
const postResult = value => parent.postMessage({fxPayload:btoa(unescape(encodeURIComponent(JSON.stringify(value))))}, "*");
(async () => {
  const fixture = FIXTURE;
  const assert = (condition, message) => { if (!condition) throw new Error(message); };
  const delay = milliseconds => new Promise(resolve => setTimeout(resolve, milliseconds));
  assert(matchMedia("(prefers-reduced-motion: reduce)").matches,
    "Chrome must expose its forced OS reduced-motion preference");
  catalog = fixture.catalog; state = fixture.main; appView = "duel";
  settings.duelScale = 100; settings.reducedMotion = false;
  setAppHtml(renderDuelView());
  const event = {type:"effect_target", side:fixture.main.humanSide,targetSide:fixture.main.humanSide,
    targetKind:"card",targetCardIid:fixture.publicFieldCardIid};
  ZZFx.onEventStart(event, 1200); activeAnimationEvent = event; setAppHtml(renderDuelView());
  const handCard = app.querySelector('.cockpit.bottom .hand-fan .card[data-fx-face="up"]');
  assert(handCard, "OS reduced motion fixture must render a visible hand card: " +
    JSON.stringify({hands: app.querySelectorAll(".hand-fan").length,
      cards: app.querySelectorAll(".card[data-fx-face]").length, body: app.innerHTML.slice(0, 1800)}));
  const rect = handCard.getBoundingClientRect();
  handCard.dispatchEvent(new PointerEvent("pointermove", {bubbles:true,
    clientX:rect.left + rect.width/2, clientY:rect.top + rect.height/2, pointerType:"mouse"}));
  await delay(550);
  const inspect = ZZFx.inspect();
  const publicField = document.querySelector('[data-board-card-anchor="' +
    fixture.main.humanSide + ':card:' + fixture.publicFieldCardIid + '"]');
  const stats = publicField.querySelector(".card-field-stats, .card-stats");
  assert(app.classList.contains("fx-reduced"), "OS reduced motion must activate the static FX mode");
  assert(!document.querySelector("canvas.fx-canvas") && inspect.ready === false,
    "OS reduced motion must not initialize a particle canvas/runtime");
  assert(inspect.activeHandles === 0 && inspect.running === false && inspect.renderedEvents === 0,
    "OS reduced motion must not schedule particles or animation frames");
  assert(!handCard.classList.contains("fx-tilting") &&
    !handCard.style.getPropertyValue("--fx-rx") && !handCard.style.getPropertyValue("--fx-ry"),
    "OS reduced motion must not generate card tilt");
  assert(stats && stats.textContent.includes(String(fixture.publicFieldCardBp)) &&
    stats.textContent.includes(String(fixture.publicFieldCardDp)) && getComputedStyle(stats).display !== "none",
    "OS reduced motion must keep public card values readable");
  ZZFx.onEventEnd(event); activeAnimationEvent = null; animationEventQueue.length = 0;
  state.pendingAttack = null; setAppHtml(renderDuelView());
  return {ok:true, reducedPreference:true, ready:inspect.ready,
    activeHandles:inspect.activeHandles, running:inspect.running, renderedEvents:inspect.renderedEvents};
})().then(postResult).catch(error => postResult({error:String(error && error.stack || error)}));
</script></body></html>'''.replace("ORIGIN", origin).replace("const fixture = FIXTURE;", f"const fixture = {fixture};")
    outer = '''<!doctype html><html><head><meta charset="utf-8"><script>
addEventListener("message", ({data}) => { if (!data.fxPayload) return;
  const result=document.createElement("script"); result.id="fx-result";
  result.type="application/json"; result.textContent=data.fxPayload; document.body.append(result); });
</script></head><body><iframe width="1280" height="900" style="border:0" srcdoc="CHILD"></iframe></body></html>'''
    duel_fx_fixture["handler"].test_document = outer.replace("CHILD", html_escape.escape(child, quote=True))
    profile = tmp_path / "chrome-profile"
    profile.mkdir(parents=True, exist_ok=True)
    command = [
        BROWSER, "--headless=new", "--no-first-run", "--no-default-browser-check",
        "--disable-breakpad", "--disable-crash-reporter", "--disable-extensions", "--no-sandbox",
        "--enable-webgl", "--ignore-gpu-blocklist", "--use-gl=angle",
        "--use-angle=swiftshader", "--enable-unsafe-swiftshader",
        "--force-device-scale-factor=1", "--window-size=1280,900",
        "--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1",
        "--force-prefers-reduced-motion=reduce", f"--user-data-dir={profile}",
        "--virtual-time-budget=6000", "--dump-dom",
        f"{origin}/__duel_fx_test__?run={tmp_path.name}",
    ]
    result = subprocess.run(
        command, capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=35,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    assert result.returncode == 0, result.stdout[-3000:] + result.stderr[-1500:]
    match = re.search(r'<script id="fx-result" type="application/json">([^<]+)</script>', result.stdout)
    assert match, result.stdout[-3000:] + result.stderr[-1500:]
    payload = json.loads(base64.b64decode(match[1]).decode("utf-8"))
    assert "error" not in payload, payload.get("error")
    assert payload.get("ok") is True and payload.get("reducedPreference") is True, payload
    assert payload["activeHandles"] == 0 and payload["running"] is False and payload["renderedEvents"] == 0, payload
