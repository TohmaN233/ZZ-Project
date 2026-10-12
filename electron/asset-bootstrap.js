"use strict";

const fs = require("node:fs");
const fsp = fs.promises;
const path = require("node:path");
const crypto = require("node:crypto");
const { spawn } = require("node:child_process");
const { Readable } = require("node:stream");
const { path7za } = require("7zip-bin");

const REQUIRED_DIRECTORIES = ["ZENONZARD_CARDLIST", "audio", "video"];
const SEVEN_ZIP_MAGIC = Buffer.from([0x37, 0x7a, 0xbc, 0xaf, 0x27, 0x1c]);
const MAX_HTML_BYTES = 256 * 1024;
const MAX_TOOL_OUTPUT = 64 * 1024 * 1024;

// Electron net.fetch rejects manual redirects instead of returning their 3xx
// response. Use ClientRequest so fetchPublic can validate every redirect before
// issuing the next request, while retaining Chromium's system proxy support.
function createElectronAssetFetch(net, { onLog = () => {} } = {}) {
  return (url, { signal, redirect, credentials } = {}) => {
    if (redirect !== "manual" || credentials !== "omit") {
      throw new TypeError("Asset requests require manual redirects and omitted credentials");
    }
    checkAbort(signal);
    return new Promise((resolve, reject) => {
      const target = new URL(url);
      onLog(`Asset HTTP GET: ${target.origin}${target.pathname}`);
      const request = net.request({ url, method: "GET", redirect: "manual", credentials: "omit", useSessionCookies: false });
      let settled = false;
      let incoming = null;
      let ended = false;
      const cleanup = () => signal?.removeEventListener("abort", abort);
      const fail = error => {
        cleanup();
        if (!settled) { settled = true; reject(error); }
        else if (incoming && !ended) incoming.destroy(error);
      };
      const abort = () => {
        fail(new DOMException("Asset installation cancelled", "AbortError"));
        request.abort();
      };
      const headersFrom = values => {
        const headers = new Headers();
        for (const [name, value] of Object.entries(values)) {
          for (const item of Array.isArray(value) ? value : [value]) headers.append(name, item);
        }
        return headers;
      };
      request.on("error", fail);
      request.on("redirect", (status, method, location, values) => {
        try {
          if (method !== "GET") throw new Error("Unexpected asset redirect method");
          const headers = headersFrom(values);
          headers.set("location", location);
          onLog(`Asset HTTP redirect: ${status} -> ${new URL(location, url).origin}`);
          const response = new Response(null, { status, headers });
          settled = true;
          cleanup();
          resolve(response);
        } catch (error) { fail(error); }
        // The next URL is checked by fetchPublic; never let Chromium follow it.
        request.abort();
      });
      request.on("response", response => {
        incoming = response;
        response.once("end", () => { ended = true; cleanup(); });
        response.once("close", () => { cleanup(); if (!ended) request.abort(); });
        response.once("aborted", () => response.destroy(new DOMException("Asset HTTP response aborted", "AbortError")));
        try {
          onLog(`Asset HTTP response: ${response.statusCode} from ${target.hostname}`);
          const body = Readable.toWeb(response, { strategy: { highWaterMark: 64 * 1024, size: chunk => chunk.byteLength } });
          const result = new Response([204, 205, 304].includes(response.statusCode) ? null : body,
            { status: response.statusCode, headers: headersFrom(response.headers) });
          settled = true;
          resolve(result);
        } catch (error) { fail(error); response.destroy(); request.abort(); }
      });
      signal?.addEventListener("abort", abort, { once: true });
      if (signal?.aborted) abort();
      else request.end();
    });
  };
}

function assetRootLooksValid(root) {
  try {
    return [root, ...REQUIRED_DIRECTORIES.map((name) => path.join(root, name))].every((item) => {
      const stat = fs.lstatSync(item);
      return stat.isDirectory() && !stat.isSymbolicLink();
    });
  } catch (error) {
    if (error.code === "ENOENT" || error.code === "ENOTDIR") return false;
    throw error;
  }
}

function formatAssetSize(bytes) {
  if (!Number.isFinite(bytes) || bytes < 0) throw new TypeError("Invalid asset size");
  if (bytes >= 1024 ** 3) return `${(bytes / 1024 ** 3).toFixed(2)} GiB`;
  if (bytes >= 1024 ** 2) return `${(bytes / 1024 ** 2).toFixed(1)} MiB`;
  if (bytes >= 1024) return `${(bytes / 1024).toFixed(1)} KiB`;
  return `${bytes} B`;
}

function checkAbort(signal) {
  if (signal?.aborted) throw new DOMException("Asset installation cancelled", "AbortError");
}

function checkedDownloadUrl(value, fileId) {
  const url = new URL(value);
  const allowed = (url.hostname === "drive.google.com" && url.pathname === "/uc") ||
    (url.hostname === "drive.usercontent.google.com" && url.pathname === "/download");
  if (url.protocol !== "https:" || url.port || url.username || url.password || !allowed ||
      url.searchParams.get("id") !== fileId || url.searchParams.get("export") !== "download") {
    throw new Error("Untrusted Google Drive download URL");
  }
  return url;
}

async function fetchPublic(fetchImpl, url, fileId, signal) {
  for (let count = 0; count < 8; count += 1) {
    checkAbort(signal);
    url = checkedDownloadUrl(url, fileId);
    const response = await fetchImpl(url.href, { signal, redirect: "manual", credentials: "omit" });
    if ([301, 302, 303, 307, 308].includes(response.status)) {
      const location = response.headers.get("location");
      if (!location) throw new Error("Google Drive redirect has no location");
      if (response.body) await response.body.cancel();
      url = new URL(location, url).href;
      continue;
    }
    if (!response.ok) {
      if (response.body) await response.body.cancel();
      throw new Error(`Google Drive download failed: HTTP ${response.status}`);
    }
    if (response.url) {
      try { checkedDownloadUrl(response.url, fileId); } catch (error) {
        if (response.body) await response.body.cancel();
        throw error;
      }
    }
    return response;
  }
  throw new Error("Too many Google Drive redirects");
}

function decodeHtml(value) {
  return value.replace(/&(?:amp|quot|apos|lt|gt|#\d+|#x[0-9a-f]+);/gi, (entity) => {
    const named = { "&amp;": "&", "&quot;": '"', "&apos;": "'", "&lt;": "<", "&gt;": ">" };
    if (named[entity.toLowerCase()]) return named[entity.toLowerCase()];
    const number = entity.toLowerCase().startsWith("&#x") ? parseInt(entity.slice(3, -1), 16) : Number(entity.slice(2, -1));
    if (!Number.isInteger(number) || number > 0x10ffff) throw new Error("Invalid Drive confirmation HTML entity");
    return String.fromCodePoint(number);
  });
}

function htmlAttributes(tag) {
  const result = Object.create(null);
  for (const match of tag.matchAll(/([\w-]+)\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+))/g)) {
    const key = match[1].toLowerCase();
    if (Object.hasOwn(result, key)) throw new Error("Duplicate Drive confirmation attribute");
    result[key] = decodeHtml(match[2] ?? match[3] ?? match[4]);
  }
  return result;
}

function confirmationUrl(html, fileId) {
  const forms = [...html.matchAll(/<form\b([^>]*)>([\s\S]*?)<\/form\s*>/gi)].filter((match) => htmlAttributes(match[1]).id === "download-form");
  if (forms.length !== 1) throw new Error("Google Drive returned HTML instead of the asset archive (quota, login, or unavailable file)");
  const attrs = htmlAttributes(forms[0][1]);
  if ((attrs.method || "get").toLowerCase() !== "get") throw new Error("Unsupported Drive confirmation method");
  const url = new URL(attrs.action);
  if (url.protocol !== "https:" || url.hostname !== "drive.usercontent.google.com" || url.pathname !== "/download" ||
      url.port || url.username || url.password || url.search || url.hash) throw new Error("Untrusted Drive confirmation action");
  const fields = new Map();
  for (const match of forms[0][2].matchAll(/<input\b[^>]*>/gi)) {
    const input = htmlAttributes(match[0]);
    if (input.type?.toLowerCase() !== "hidden") continue;
    if (!["id", "export", "confirm", "uuid"].includes(input.name) || fields.has(input.name) || input.value === undefined) {
      throw new Error("Unexpected Drive confirmation field");
    }
    fields.set(input.name, input.value);
  }
  if (fields.get("id") !== fileId || fields.get("export") !== "download" || fields.get("confirm") !== "t" ||
      !/^[a-zA-Z0-9-]{1,128}$/.test(fields.get("uuid") || "")) throw new Error("Invalid Drive confirmation fields");
  for (const [key, value] of fields) url.searchParams.set(key, value);
  return checkedDownloadUrl(url.href, fileId).href;
}

async function readHtml(response, signal) {
  if (!response.body) throw new Error("Google Drive response has no body");
  const reader = response.body.getReader();
  const chunks = [];
  let size = 0;
  try {
    while (true) {
      checkAbort(signal);
      const item = await reader.read();
      if (item.done) break;
      size += item.value.byteLength;
      if (size > MAX_HTML_BYTES) throw new Error("Google Drive HTML response exceeds confirmation limit");
      chunks.push(Buffer.from(item.value));
    }
    return Buffer.concat(chunks).toString("utf8");
  } finally {
    await reader.cancel();
    reader.releaseLock();
  }
}

async function requireDiskSpace(directory, requiredBytes) {
  if (typeof fsp.statfs !== "function") throw new Error("Disk space verification requires Node statfs support");
  const stat = await fsp.statfs(directory, { bigint: true });
  const available = stat.bavail * stat.bsize;
  if (available < BigInt(requiredBytes) + 64n * 1024n * 1024n) {
    throw new Error(`Insufficient disk space: need ${formatAssetSize(requiredBytes)} plus 64 MiB reserve`);
  }
}

async function run7zip(args, signal, onOutput) {
  checkAbort(signal);
  return new Promise((resolve, reject) => {
    const child = spawn(path7za, args, { windowsHide: true, stdio: ["ignore", "pipe", "pipe"] });
    let output = "";
    let failure;
    const abort = () => child.kill();
    signal?.addEventListener("abort", abort, { once: true });
    const collect = (chunk) => {
      output += chunk.toString("utf8");
      if (output.length > MAX_TOOL_OUTPUT) {
        failure = new Error("7-Zip output exceeds safe limit");
        child.kill();
      }
      if (onOutput && !failure) {
        try { onOutput(chunk.toString("utf8")); } catch (error) { failure = error; child.kill(); }
      }
    };
    child.stdout.on("data", collect);
    child.stderr.on("data", collect);
    child.on("error", (error) => { failure = error; });
    child.on("close", (code) => {
      signal?.removeEventListener("abort", abort);
      if (signal?.aborted) return reject(new DOMException("Asset installation cancelled", "AbortError"));
      if (failure) return reject(failure);
      if (code !== 0) return reject(new Error(`7-Zip ${args[0]} failed (exit ${code}): ${output.slice(-4096).trim()}`));
      resolve(output);
    });
    if (signal?.aborted) abort();
  });
}

function inspectEntries(listing) {
  const names = new Set();
  let expandedBytes = 0;
  // Solid archives list directories last, with empty final fields ("Block = ").
  // Preserve field whitespace; trim() would turn the last field into invalid
  // syntax. Ignore only empty records separating the technical entries.
  const records = listing.split(/\r?\n\s*\r?\n/).filter((record) => record.trim());
  for (const record of records) {
    const fields = Object.create(null);
    for (const line of record.split(/\r?\n/)) {
      const match = /^([^=]+) = (.*)$/.exec(line);
      if (!match || Object.hasOwn(fields, match[1].trim())) throw new Error("Unrecognized 7-Zip entry listing");
      fields[match[1].trim()] = match[2];
    }
    const name = fields.Path;
    if (!name || name.includes("\0") || /[\r\n:]/.test(name) || /^[\\/]/.test(name)) throw new Error(`Unsafe archive entry: ${name}`);
    const parts = name.replace(/\\/g, "/").replace(/\/$/, "").split("/");
    if (parts.some((part) => !part || part === "." || part === ".." || /[. ]$/.test(part) || /^(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$)/i.test(part))) {
      throw new Error(`Unsafe archive entry: ${name}`);
    }
    if (Object.keys(fields).some((key) => /link|reparse/i.test(key)) || /(^|\s)l[rwx-]{9}(\s|$)/.test(fields.Attributes || "") || /^[A-Z_]*L/.test(fields.Attributes || "")) {
      throw new Error(`Archive links are forbidden: ${name}`);
    }
    const normalized = parts.join("/").toLowerCase();
    if (names.has(normalized)) throw new Error(`Duplicate archive entry: ${name}`);
    names.add(normalized);
    if (!/^\d+$/.test(fields.Size || "")) throw new Error(`Missing archive entry size: ${name}`);
    expandedBytes += Number(fields.Size);
    if (!Number.isSafeInteger(expandedBytes)) throw new Error("Archive expanded size is invalid");
    if (fields.Encrypted === "+") throw new Error("Encrypted asset archives are unsupported");
  }
  return expandedBytes;
}

async function assertNoExtractedLinks(directory, signal) {
  checkAbort(signal);
  for (const name of await fsp.readdir(directory)) {
    const entry = path.join(directory, name);
    const stat = await fsp.lstat(entry);
    if (stat.isSymbolicLink() || (!stat.isDirectory() && !stat.isFile()) || (stat.isFile() && stat.nlink > 1)) {
      throw new Error(`Extracted asset contains a link or special file: ${entry}`);
    }
    if (stat.isDirectory()) await assertNoExtractedLinks(entry, signal);
  }
}

async function pathExists(item) {
  try { await fsp.lstat(item); return true; } catch (error) {
    if (error.code === "ENOENT") return false;
    throw error;
  }
}

async function installAssetBundle({ destination, source, fetchImpl = globalThis.fetch, onProgress = () => {}, signal }) {
  if (!destination || !source || !/^[a-zA-Z0-9_-]+$/.test(source.fileId || "") ||
      !Number.isSafeInteger(source.sizeBytes) || source.sizeBytes < 6 || typeof fetchImpl !== "function" ||
      (source.expandedBytes !== undefined && (!Number.isSafeInteger(source.expandedBytes) || source.expandedBytes < 0)) ||
      (source.sha256 !== undefined && !/^[a-fA-F0-9]{64}$/.test(source.sha256))) throw new TypeError("Invalid asset installation configuration");
  destination = path.resolve(destination);
  const progress = (stage, receivedBytes, percent, message) => onProgress({ stage, receivedBytes, totalBytes: source.sizeBytes, percent, ...(message ? { message } : {}) });
  checkAbort(signal);
  if (assetRootLooksValid(destination)) {
    progress("complete", source.sizeBytes, 100, "Assets already installed");
    return { status: "existing", destination };
  }
  if (await pathExists(destination)) throw new Error(`Asset destination already exists but is incomplete: ${destination}`);
  const parent = path.dirname(destination);
  await fsp.mkdir(parent, { recursive: true });
  await requireDiskSpace(parent, source.sizeBytes + (source.expandedBytes ?? 0));
  const staging = await fsp.mkdtemp(path.join(parent, ".zz-assets-"));
  let failure;
  let response;
  try {
    const archive = path.join(staging, "bundle.7z");
    const extracted = path.join(staging, "extracted");
    progress("download", 0, 0);
    response = await fetchPublic(fetchImpl, `https://drive.google.com/uc?export=download&id=${source.fileId}`, source.fileId, signal);
    if ((response.headers.get("content-type") || "").toLowerCase().includes("text/html")) {
      const url = confirmationUrl(await readHtml(response, signal), source.fileId);
      response = await fetchPublic(fetchImpl, url, source.fileId, signal);
      if ((response.headers.get("content-type") || "").toLowerCase().includes("text/html")) {
        throw new Error("Google Drive returned HTML after confirmation (quota, login, or unavailable file)");
      }
    }
    const advertised = response.headers.get("content-length");
    if (advertised !== null && (!/^\d+$/.test(advertised) || Number(advertised) !== source.sizeBytes)) {
      throw new Error(`Asset download size mismatch: expected ${source.sizeBytes}, server advertised ${advertised}`);
    }
    if (!response.body) throw new Error("Asset download has no response body");
    if (response.body.locked) throw new Error("Asset response body is already in use");
    const output = await fsp.open(archive, "wx");
    const reader = response.body.getReader();
    const hash = crypto.createHash("sha256");
    let receivedBytes = 0;
    let magic = Buffer.alloc(0);
    try {
      while (true) {
        checkAbort(signal);
        const item = await reader.read();
        checkAbort(signal);
        if (item.done) break;
        const chunk = Buffer.from(item.value);
        receivedBytes += chunk.length;
        if (receivedBytes > source.sizeBytes) throw new Error("Asset download exceeds expected size");
        if (magic.length < 6) magic = Buffer.concat([magic, chunk]).subarray(0, 6);
        hash.update(chunk);
        await output.writeFile(chunk);
        progress("download", receivedBytes, receivedBytes / source.sizeBytes * 100);
      }
    } finally {
      try { await output.close(); } finally {
        try { await reader.cancel(); } finally { reader.releaseLock(); }
      }
    }
    if (receivedBytes !== source.sizeBytes) throw new Error(`Asset download size mismatch: expected ${source.sizeBytes}, received ${receivedBytes}`);
    if (!magic.equals(SEVEN_ZIP_MAGIC)) throw new Error("Downloaded file is not a 7z archive (HTML, quota, or invalid content)");
    if (source.sha256 && hash.digest("hex") !== source.sha256.toLowerCase()) throw new Error("Asset SHA-256 mismatch");
    progress("verify", receivedBytes, 0);
    const listing = await run7zip(["l", "-slt", "-ba", "-sccUTF-8", "-p__asset_bundle_no_password__", archive], signal);
    const expandedBytes = inspectEntries(listing);
    if (source.expandedBytes !== undefined && expandedBytes !== source.expandedBytes) {
      throw new Error(`Asset expanded size mismatch: expected ${source.expandedBytes}, archive contains ${expandedBytes}`);
    }
    await requireDiskSpace(parent, expandedBytes);
    await run7zip(["t", "-bd", "-y", "-p__asset_bundle_no_password__", archive], signal);
    progress("verify", receivedBytes, 100);
    await fsp.mkdir(extracted);
    progress("extract", receivedBytes, 0);
    await run7zip(["x", "-y", "-bsp1", "-sccUTF-8", "-p__asset_bundle_no_password__", `-o${extracted}`, archive], signal, (chunk) => {
      for (const match of chunk.matchAll(/(\d{1,3})%/g)) progress("extract", receivedBytes, Math.min(100, Number(match[1])));
    });
    await assertNoExtractedLinks(extracted, signal);
    const nestedRoot = path.join(extracted, "asserts");
    const root = assetRootLooksValid(nestedRoot) ? nestedRoot : extracted;
    if (!assetRootLooksValid(root)) throw new Error("Asset archive layout is invalid: requires ZENONZARD_CARDLIST, audio, and video directories");
    progress("extract", receivedBytes, 100);
    checkAbort(signal);
    if (await pathExists(destination)) throw new Error(`Asset destination appeared during installation: ${destination}`);
    await fsp.rename(root, destination);
    progress("complete", receivedBytes, 100);
    return { status: "installed", destination };
  } catch (error) {
    failure = error;
    throw error;
  } finally {
    const cleanupErrors = [];
    try { if (response?.body && !response.body.locked) await response.body.cancel(); } catch (error) {
      // Cancelling an already errored ReadableStream rejects with its original
      // error. It was reported above; only a distinct cleanup failure is new.
      if (error !== failure) cleanupErrors.push(error);
    }
    try { await fsp.rm(staging, { recursive: true }); } catch (error) { cleanupErrors.push(error); }
    if (cleanupErrors.length) throw new AggregateError(failure ? [failure, ...cleanupErrors] : cleanupErrors, `Failed to clean asset download or owned staging directory: ${staging}`);
  }
}

module.exports = { installAssetBundle, assetRootLooksValid, formatAssetSize, createElectronAssetFetch };
