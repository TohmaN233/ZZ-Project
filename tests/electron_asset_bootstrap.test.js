"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const fsp = fs.promises;
const os = require("node:os");
const path = require("node:path");
const crypto = require("node:crypto");
const { execFileSync } = require("node:child_process");
const { test } = require("node:test");
const { path7za } = require("7zip-bin");
const { installAssetBundle, assetRootLooksValid, formatAssetSize } = require("../electron/asset-bootstrap");

const FILE_ID = "1f7AAwFqaFRLyX1z7pPF68YJ7fE9r3DXs";

function fixture(t, { nested = true, wrongLayout = false } = {}) {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), "zz-asset-test-"));
  t.after(() => fs.rmSync(directory, { recursive: true, force: true }));
  const input = path.join(directory, "input");
  const root = nested ? path.join(input, "asserts") : input;
  for (const name of wrongLayout ? ["audio"] : ["ZENONZARD_CARDLIST", "audio", "video"]) {
    fs.mkdirSync(path.join(root, name), { recursive: true });
    fs.writeFileSync(path.join(root, name, "tiny.txt"), `real asset fixture ${name}`);
  }
  const archive = path.join(directory, "tiny.7z");
  execFileSync(path7za, ["a", "-t7z", "-mx=0", archive, "."], { cwd: input, windowsHide: true });
  const bytes = fs.readFileSync(archive);
  return { directory, archive, bytes, destination: path.join(directory, "installed"), source: { fileId: FILE_ID, fileName: "asserts.7z", sizeBytes: bytes.length, folderUrl: "https://drive.google.com/drive/folders/public" } };
}

function binary(bytes) {
  return new Response(bytes, { headers: { "Content-Type": "application/octet-stream", "Content-Length": String(bytes.length) } });
}

function assertClean(fixture) {
  assert.equal(fs.existsSync(fixture.destination), false);
  assert.deepEqual(fs.readdirSync(fixture.directory).filter((name) => name.startsWith(".zz-assets-")), []);
}

function confirmation(overrides = {}) {
  const fields = { id: FILE_ID, export: "download", confirm: "t", uuid: "sample-confirm-uuid", ...overrides };
  return `<html><form id="download-form" method="get" action="https://drive.usercontent.google.com/download">${Object.entries(fields).map(([name, value]) => `<input type="hidden" name="${name}" value="${value}">`).join("")}</form></html>`;
}

test("real 7z archive installs through bounded Drive confirmation with exact byte progress", async (t) => {
  const sample = fixture(t);
  sample.source.sha256 = crypto.createHash("sha256").update(sample.bytes).digest("hex");
  sample.source.expandedBytes = ["ZENONZARD_CARDLIST", "audio", "video"].reduce((sum, name) => sum + Buffer.byteLength(`real asset fixture ${name}`), 0);
  const requests = [];
  const events = [];
  const result = await installAssetBundle({ ...sample, onProgress: (event) => events.push(event), fetchImpl: async (url, options) => {
    requests.push({ url, options });
    if (requests.length === 1) return new Response(null, { status: 303, headers: { location: `https://drive.usercontent.google.com/download?id=${FILE_ID}&export=download` } });
    if (requests.length === 2) return new Response(confirmation(), { headers: { "content-type": "text/html; charset=utf-8" } });
    const chunks = [sample.bytes.subarray(0, 3), sample.bytes.subarray(3, 13), sample.bytes.subarray(13)];
    return new Response(new ReadableStream({ pull(controller) { const chunk = chunks.shift(); if (chunk) controller.enqueue(chunk); else controller.close(); } }), { headers: { "content-type": "application/octet-stream" } });
  } });
  assert.deepEqual(result, { status: "installed", destination: sample.destination });
  assert.equal(assetRootLooksValid(sample.destination), true);
  assert.equal(fs.readFileSync(path.join(sample.destination, "audio", "tiny.txt"), "utf8"), "real asset fixture audio");
  assert.equal(requests.length, 3);
  assert.equal(new URL(requests[2].url).searchParams.get("confirm"), "t");
  assert.ok(requests.every(({ options }) => options.redirect === "manual" && options.credentials === "omit"));
  assert.deepEqual(events.filter((event) => event.stage === "download").map((event) => event.receivedBytes), [0, 3, 13, sample.bytes.length]);
  assert.ok(events.every((event) => event.totalBytes === sample.bytes.length && event.percent >= 0 && event.percent <= 100));
  assert.deepEqual([...new Set(events.map((event) => event.stage))], ["download", "verify", "extract", "complete"]);
  assert.deepEqual(fs.readdirSync(sample.directory).filter((name) => name.startsWith(".zz-assets-")), []);
});

test("flat real 7z archive installs, then an existing valid destination skips network", async (t) => {
  const sample = fixture(t, { nested: false });
  await installAssetBundle({ ...sample, fetchImpl: async () => binary(sample.bytes) });
  const result = await installAssetBundle({ ...sample, fetchImpl: () => { throw new Error("Network must not run"); } });
  assert.equal(result.status, "existing");
});

test("real 7z directory listings preserve the final entry's empty technical fields", async (t) => {
  const sample = fixture(t, { nested: false });
  fs.unlinkSync(sample.archive);
  execFileSync(path7za, ["a", "-t7z", "-mx=1", sample.archive, "."], {
    cwd: path.join(sample.directory, "input"), windowsHide: true,
  });
  const listing = execFileSync(path7za, ["l", "-slt", "-ba", sample.archive], {
    encoding: "utf8", windowsHide: true,
  });
  // The public archive lists directories last; 7-Zip may write them first
  // when creating a new archive. Preserve the real records and reproduce
  // the public archive's legal entry ordering for the parser regression.
  const records = listing.split(/\r?\n\r?\n/).filter((record) => record.trim());
  records.sort((a, b) => Number(/^Attributes = D/m.test(a)) - Number(/^Attributes = D/m.test(b)));
  const directoriesLast = records.join("\r\n\r\n") + "\r\n\r\n";
  assert.match(directoriesLast, /Block = \r?\n\r?\n$/);
  const Module = require("node:module");
  const modulePath = require.resolve("../electron/asset-bootstrap");
  const parserModule = new Module(modulePath, module);
  parserModule.filename = modulePath;
  parserModule.paths = module.paths;
  parserModule._compile(fs.readFileSync(modulePath, "utf8") + "\nmodule.exports.inspectEntries = inspectEntries;", modulePath);
  assert.equal(parserModule.exports.inspectEntries(directoriesLast), 85);
  const bytes = fs.readFileSync(sample.archive);
  const result = await installAssetBundle({ ...sample,
    source: { ...sample.source, sizeBytes: bytes.length },
    fetchImpl: async () => binary(bytes),
  });
  assert.equal(result.status, "installed");
  assert.equal(assetRootLooksValid(sample.destination), true);
});

test("preexisting incomplete destination is preserved and fails before network", async (t) => {
  const sample = fixture(t);
  fs.mkdirSync(sample.destination);
  fs.writeFileSync(path.join(sample.destination, "keep.txt"), "preserve me");
  await assert.rejects(installAssetBundle({ ...sample, fetchImpl: () => { throw new Error("Network must not run"); } }), /already exists but is incomplete/);
  assert.equal(fs.readFileSync(path.join(sample.destination, "keep.txt"), "utf8"), "preserve me");
});

test("the published expanded-size pin must match the real archive before extraction", async t => {
  const sample = fixture(t);
  sample.source.expandedBytes = 1;
  const events = [];
  await assert.rejects(installAssetBundle({ ...sample, fetchImpl: async () => binary(sample.bytes),
    onProgress: event => events.push(event) }), /expanded size mismatch/);
  assert.equal(events.some(event => event.stage === "extract"), false);
  assertClean(sample);
});

test("download abort cancels the owned stream and removes staging", async (t) => {
  const sample = fixture(t);
  const controller = new AbortController();
  let cancelled = false;
  const body = new ReadableStream({ pull(stream) { stream.enqueue(sample.bytes.subarray(0, 8)); }, cancel() { cancelled = true; } });
  await assert.rejects(installAssetBundle({ ...sample, signal: controller.signal, fetchImpl: async () => new Response(body), onProgress: (event) => {
    if (event.stage === "download" && event.receivedBytes > 0) controller.abort();
  } }), { name: "AbortError" });
  assert.equal(cancelled, true);
  assertClean(sample);
});

test("abort before download preserves all paths", async (t) => {
  const sample = fixture(t);
  const controller = new AbortController();
  controller.abort();
  await assert.rejects(installAssetBundle({ ...sample, signal: controller.signal, fetchImpl: () => { throw new Error("Network must not run"); } }), { name: "AbortError" });
  assertClean(sample);
});

test("truncated, oversized, advertised wrong size, and nonarchive downloads fail explicitly", async (t) => {
  const sample = fixture(t);
  const cases = [
    [new Response(sample.bytes.subarray(0, -1)), /size mismatch/],
    [new Response(Buffer.concat([sample.bytes, Buffer.from("extra")])), /exceeds expected size/],
    [binary(sample.bytes.subarray(0, -1)), /server advertised/],
    [binary(Buffer.alloc(sample.bytes.length, "X")), /not a 7z archive/],
  ];
  for (const [response, pattern] of cases) {
    await assert.rejects(installAssetBundle({ ...sample, fetchImpl: async () => response }), pattern);
    assertClean(sample);
  }
});

test("HTTP, quota/login HTML, and repeated confirmation fail without extraction", async (t) => {
  const sample = fixture(t);
  await assert.rejects(installAssetBundle({ ...sample, fetchImpl: async () => new Response("denied", { status: 403 }) }), /HTTP 403/);
  await assert.rejects(installAssetBundle({ ...sample, fetchImpl: async () => new Response("<html>Download quota exceeded; sign in</html>", { headers: { "content-type": "text/html" } }) }), /quota, login/);
  let calls = 0;
  await assert.rejects(installAssetBundle({ ...sample, fetchImpl: async () => { calls += 1; return new Response(confirmation(), { headers: { "content-type": "text/html" } }); } }), /HTML after confirmation/);
  assert.equal(calls, 2);
  assertClean(sample);
});

test("confirmation enforces the exact file ID, hidden fields, host, and bounded HTML", async (t) => {
  const sample = fixture(t);
  for (const html of [confirmation({ id: "another-file" }), confirmation({ extra: "unexpected" }), confirmation().replace("drive.usercontent.google.com", "evil.example"), "x".repeat(256 * 1024 + 1)]) {
    await assert.rejects(installAssetBundle({ ...sample, fetchImpl: async () => new Response(html, { headers: { "content-type": "text/html" } }) }), /confirmation|limit/);
    assertClean(sample);
  }
  let requests = 0;
  await assert.rejects(installAssetBundle({ ...sample, fetchImpl: async () => { requests += 1; return new Response(null, { status: 302, headers: { location: "https://evil.example/download" } }); } }), /Untrusted/);
  assert.equal(requests, 1);
  assertClean(sample);
});

test("real 7z CRC failure and an optional SHA mismatch reject installation", async (t) => {
  const sample = fixture(t);
  const corrupt = Buffer.from(sample.bytes);
  corrupt[32] ^= 0xff;
  await assert.rejects(installAssetBundle({ ...sample, fetchImpl: async () => binary(corrupt) }), /7-Zip t failed/);
  await assert.rejects(installAssetBundle({ ...sample, source: { ...sample.source, sha256: "0".repeat(64) }, fetchImpl: async () => binary(sample.bytes) }), /SHA-256 mismatch/);
  assertClean(sample);
});

test("unsafe paths in real 7z entries fail before extraction", async (t) => {
  const sample = fixture(t);
  for (const name of ["../escape.txt", "/absolute.txt", "C:\\escape.txt", "asserts/audio/file:stream", "asserts/audio/NUL.txt"]) {
    fs.writeFileSync(sample.archive, sample.bytes);
    execFileSync(path7za, ["rn", sample.archive, "asserts/audio/tiny.txt", name], { windowsHide: true });
    const bytes = fs.readFileSync(sample.archive);
    await assert.rejects(installAssetBundle({ ...sample, source: { ...sample.source, sizeBytes: bytes.length }, fetchImpl: async () => binary(bytes) }), /Unsafe archive entry/);
    assertClean(sample);
  }
  assert.equal(fs.existsSync(path.join(sample.directory, "escape.txt")), false);
});

test("real 7z directory link entries are rejected before extraction", async (t) => {
  const sample = fixture(t);
  const input = path.join(sample.directory, "input");
  fs.symlinkSync(path.join(input, "asserts", "audio"), path.join(input, "asserts", "linked-audio"), process.platform === "win32" ? "junction" : "dir");
  execFileSync(path7za, ["u", "-snl", sample.archive, "."], { cwd: input, windowsHide: true });
  const bytes = fs.readFileSync(sample.archive);
  const events = [];
  await assert.rejects(installAssetBundle({ ...sample, source: { ...sample.source, sizeBytes: bytes.length }, fetchImpl: async () => binary(bytes), onProgress: (event) => events.push(event) }), /Archive links are forbidden/);
  assert.equal(events.some((event) => event.stage === "extract"), false);
  assertClean(sample);
});

test("abort kills only the owned real 7z child and cleans staging", async (t) => {
  const sample = fixture(t);
  const controller = new AbortController();
  const childProcess = require("node:child_process");
  const originalSpawn = childProcess.spawn;
  const modulePath = require.resolve("../electron/asset-bootstrap");
  let kills = 0;
  let childStarted = false;
  childProcess.spawn = (...args) => {
    const child = originalSpawn(...args);
    assert.equal(args[2].windowsHide, true);
    if (args[1][0] === "x") {
      childStarted = true;
      const originalKill = child.kill.bind(child);
      child.kill = (...killArgs) => { kills += 1; return originalKill(...killArgs); };
      queueMicrotask(() => controller.abort());
    }
    return child;
  };
  delete require.cache[modulePath];
  let installer;
  try { installer = require(modulePath).installAssetBundle; } finally {
    childProcess.spawn = originalSpawn;
    delete require.cache[modulePath];
  }
  await assert.rejects(installer({ ...sample, signal: controller.signal, fetchImpl: async () => binary(sample.bytes) }), { name: "AbortError" });
  assert.equal(childStarted, true);
  assert.equal(kills, 1);
  assertClean(sample);
});

test("wrong real archive layout rejects installation", async (t) => {
  const sample = fixture(t, { wrongLayout: true });
  await assert.rejects(installAssetBundle({ ...sample, fetchImpl: async () => binary(sample.bytes) }), /layout is invalid/);
  assertClean(sample);
});

test("destination created during extraction is preserved and atomic install fails", async (t) => {
  const sample = fixture(t);
  await assert.rejects(installAssetBundle({ ...sample, fetchImpl: async () => binary(sample.bytes), onProgress: (event) => {
    if (event.stage === "extract" && event.percent === 100 && !fs.existsSync(sample.destination)) {
      fs.mkdirSync(sample.destination);
      fs.writeFileSync(path.join(sample.destination, "keep.txt"), "concurrent owner");
    }
  } }), /appeared during installation/);
  assert.equal(fs.readFileSync(path.join(sample.destination, "keep.txt"), "utf8"), "concurrent owner");
  assert.deepEqual(fs.readdirSync(sample.directory).filter((name) => name.startsWith(".zz-assets-")), []);
});

test("rename permission failure leaves destination absent and cleans staging", async (t) => {
  const sample = fixture(t);
  const original = fsp.rename;
  fsp.rename = async () => { const error = new Error("permission denied during rename"); error.code = "EACCES"; throw error; };
  try {
    await assert.rejects(installAssetBundle({ ...sample, fetchImpl: async () => binary(sample.bytes) }), /permission denied during rename/);
  } finally { fsp.rename = original; }
  assertClean(sample);
});

test("disk space failure prevents network access", async (t) => {
  const sample = fixture(t);
  const original = fsp.statfs;
  fsp.statfs = async () => ({ bavail: 0n, bsize: 4096n });
  try {
    await assert.rejects(installAssetBundle({ ...sample, fetchImpl: () => { throw new Error("Network must not run"); } }), /Insufficient disk space/);
  } finally { fsp.statfs = original; }
  assertClean(sample);
});

test("expanded disk space failure occurs before extraction", async (t) => {
  const sample = fixture(t);
  const original = fsp.statfs;
  const events = [];
  let calls = 0;
  fsp.statfs = async () => { calls += 1; return { bavail: calls === 1 ? 1024n * 1024n : 0n, bsize: 4096n }; };
  try {
    await assert.rejects(installAssetBundle({ ...sample, fetchImpl: async () => binary(sample.bytes), onProgress: (event) => events.push(event) }), /Insufficient disk space/);
  } finally { fsp.statfs = original; }
  assert.equal(calls, 2);
  assert.equal(events.some((event) => event.stage === "extract"), false);
  assertClean(sample);
});

test("size labels and asset directory validation remain explicit", (t) => {
  const sample = fixture(t);
  assert.equal(assetRootLooksValid(sample.destination), false);
  assert.equal(formatAssetSize(1534680950), "1.43 GiB");
  assert.equal(formatAssetSize(1024), "1.0 KiB");
  assert.throws(() => formatAssetSize(-1), /Invalid asset size/);
});
