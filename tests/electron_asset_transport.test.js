"use strict";

const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { spawnSync } = require("node:child_process");

async function runElectronHarness(root, modulePath, sevenZipPath) {
  const { app, net } = require("electron");
  const assert = require("node:assert/strict");
  const fs = require("node:fs");
  const path = require("node:path");
  const http = require("node:http");
  const { execFileSync } = require("node:child_process");
  const { installAssetBundle, assetRootLooksValid, createElectronAssetFetch } = require(modulePath);
  app.setPath("userData", path.join(root, "profile"));
  await app.whenReady();
  const fileId = "test-public-assets";
  const input = path.join(root, "input");
  for (const name of ["ZENONZARD_CARDLIST", "audio", "video"]) {
    fs.mkdirSync(path.join(input, name), { recursive: true });
    fs.writeFileSync(path.join(input, name, "tiny.txt"), `asset ${name}`);
  }
  const archive = path.join(root, "tiny.7z");
  execFileSync(sevenZipPath, ["a", "-t7z", "-mx=0", archive, "."], { cwd: input, windowsHide: true });
  const bytes = fs.readFileSync(archive);
  const requests = [];
  let mode = "normal";
  const server = http.createServer((req, res) => {
    requests.push(req.url);
    assert.equal(req.headers.cookie, undefined);
    if (mode === "abort-before-headers") return;
    if (mode === "untrusted" || mode === "loop") {
      res.writeHead(302, { location: mode === "untrusted" ? "https://evil.example/archive" : `https://drive.google.com/uc?id=${fileId}&export=download` });
      res.end();
      return;
    }
    if (req.url.startsWith("/uc")) {
      res.writeHead(302, { location: `https://drive.usercontent.google.com/download?id=${fileId}&export=download` });
      res.end();
    } else if (!req.url.includes("confirm=t")) {
      res.writeHead(200, { "content-type": "text/html" });
      res.end(`<form id="download-form" method="get" action="https://drive.usercontent.google.com/download"><input type="hidden" name="id" value="${fileId}"><input type="hidden" name="export" value="download"><input type="hidden" name="confirm" value="t"><input type="hidden" name="uuid" value="local-test"></form>`);
    } else {
      res.writeHead(200, { "content-type": "application/octet-stream", "content-length": String(bytes.length) });
      if (mode === "abort-body" || mode === "truncate") {
        res.write(bytes.subarray(0, 8));
        if (mode === "truncate") setTimeout(() => res.destroy(), 20);
        return;
      }
      res.end(bytes);
    }
  });
  await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
  const origin = `http://127.0.0.1:${server.address().port}`;
  await require("electron").session.defaultSession.cookies.set({ url: origin, name: "private-session", value: "must-not-send" });
  // Map the pinned public endpoints to a deterministic local HTTP server while
  // exercising the real Chromium network implementation used by the desktop.
  const fetchImpl = createElectronAssetFetch({ request(options) {
    assert.equal(options.redirect, "manual");
    assert.equal(options.credentials, "omit");
    assert.equal(options.useSessionCookies, false);
    const parsed = new URL(options.url);
    return net.request({ ...options, url: origin + parsed.pathname + parsed.search });
  } });
  try {
    const destination = path.join(root, "installed");
    const events = [];
    const result = await installAssetBundle({ destination,
      source: { fileId, sizeBytes: bytes.length, fileName: "asserts.7z" },
      fetchImpl, onProgress: event => events.push(event),
    });
    assert.equal(result.status, "installed");
    assert.equal(assetRootLooksValid(destination), true);
    assert.equal(fs.readFileSync(path.join(destination, "audio", "tiny.txt"), "utf8"), "asset audio");
    assert.equal(requests.length, 3);
    assert.deepEqual([...new Set(events.map(event => event.stage))], ["download", "verify", "extract", "complete"]);
    console.log("REAL_ELECTRON_ASSET_INSTALL_PASS");
    for (const scenario of ["untrusted", "loop", "abort-before-headers", "abort-body", "truncate"]) {
      mode = scenario;
      const target = path.join(root, scenario);
      const controller = new AbortController();
      const start = requests.length;
      const timer = scenario === "abort-before-headers" ? setTimeout(() => controller.abort(), 50) : null;
      try {
        await assert.rejects(installAssetBundle({ destination: target,
          source: { fileId, sizeBytes: bytes.length, fileName: "asserts.7z" },
          fetchImpl, signal: controller.signal,
          onProgress: event => { if (scenario === "abort-body" && event.stage === "download" && event.receivedBytes > 0) controller.abort(); },
        }), error => {
          if (scenario === "untrusted") assert.match(error.message, /Untrusted/);
          else if (scenario === "loop") assert.match(error.message, /Too many/);
          else if (scenario === "truncate") assert.match(error.message, /ERR_|aborted|closed/i);
          else assert.equal(error.name, "AbortError");
          return true;
        });
      } finally { clearTimeout(timer); }
      assert.equal(fs.existsSync(target), false);
      assert.deepEqual(fs.readdirSync(root).filter(name => name.startsWith(".zz-assets-")), []);
      if (scenario === "untrusted") assert.equal(requests.length - start, 1);
      if (scenario === "loop") assert.equal(requests.length - start, 8);
      console.log("REAL_ELECTRON_BOUNDARY_PASS", scenario);
    }
  } finally {
    await new Promise(resolve => server.close(resolve));
  }
}

test("real Electron installs assets across HTTP redirects and Drive confirmation", { timeout: 30000 }, t => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "zz-electron-asset-test-"));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const script = path.join(root, "integration.cjs");
  const args = [root, require.resolve("../electron/asset-bootstrap"), require("7zip-bin").path7za];
  fs.writeFileSync(script, `(${runElectronHarness.toString()})(...${JSON.stringify(args)})\n.then(() => require('electron').app.exit(0), error => { console.error(error); require('electron').app.exit(1); });`);
  const result = spawnSync(require("electron"), [script], { encoding: "utf8", windowsHide: true, timeout: 25000 });
  if (result.error) throw result.error;
  assert.equal(result.status, 0, result.stdout + result.stderr);
  assert.match(result.stdout, /REAL_ELECTRON_ASSET_INSTALL_PASS/);
  for (const scenario of ["untrusted", "loop", "abort-before-headers", "abort-body", "truncate"]) {
    assert.ok(result.stdout.includes(`REAL_ELECTRON_BOUNDARY_PASS ${scenario}`), result.stdout);
  }
});
