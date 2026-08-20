"use strict";

const RELEASE_API_URL = "https://api.github.com/repos/TohmaN233/ZZ-Project/releases/latest";
const LATEST_RELEASE_URL = "https://github.com/TohmaN233/ZZ-Project/releases/latest";
const PROJECT_WEBSITE_URL = "https://tohman233.github.io/ZZ-Project/";

function parseVersion(value) {
  const raw = String(value || "").trim();
  const match = /^v?(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?(?:\+[0-9A-Za-z.-]+)?$/.exec(raw);
  if (!match) throw new Error(`invalid semantic version: ${raw || "<empty>"}`);
  return {
    raw,
    core: match.slice(1, 4).map(Number),
    prerelease: match[4] ? match[4].split(".") : [],
  };
}

function comparePrerelease(left, right) {
  if (left.length === 0 || right.length === 0) {
    if (left.length === right.length) return 0;
    return left.length === 0 ? 1 : -1;
  }
  const length = Math.max(left.length, right.length);
  for (let index = 0; index < length; index += 1) {
    if (left[index] === undefined) return -1;
    if (right[index] === undefined) return 1;
    if (left[index] === right[index]) continue;
    const leftNumber = /^\d+$/.test(left[index]) ? Number(left[index]) : null;
    const rightNumber = /^\d+$/.test(right[index]) ? Number(right[index]) : null;
    if (leftNumber !== null && rightNumber !== null) return Math.sign(leftNumber - rightNumber);
    if (leftNumber !== null) return -1;
    if (rightNumber !== null) return 1;
    return left[index] < right[index] ? -1 : 1;
  }
  return 0;
}

function compareVersions(leftValue, rightValue) {
  const left = parseVersion(leftValue);
  const right = parseVersion(rightValue);
  for (let index = 0; index < left.core.length; index += 1) {
    if (left.core[index] !== right.core[index]) {
      return Math.sign(left.core[index] - right.core[index]);
    }
  }
  return comparePrerelease(left.prerelease, right.prerelease);
}

async function checkLatestRelease({ currentVersion, fetchImpl }) {
  if (typeof fetchImpl !== "function") throw new TypeError("fetchImpl must be a function");
  const current = parseVersion(currentVersion).raw.replace(/^v/, "");
  const response = await fetchImpl(RELEASE_API_URL, {
    headers: {
      Accept: "application/vnd.github+json",
      "X-GitHub-Api-Version": "2026-03-10",
    },
  });
  if (!response || typeof response.ok !== "boolean") {
    throw new Error("GitHub update check returned an invalid response");
  }
  if (!response.ok) throw new Error(`GitHub update check failed: HTTP ${response.status}`);
  const release = await response.json();
  if (!release || typeof release.tag_name !== "string") {
    throw new Error("GitHub latest release is missing tag_name");
  }
  const latestVersion = parseVersion(release.tag_name).raw.replace(/^v/, "");
  return {
    status: compareVersions(current, latestVersion) < 0 ? "available" : "current",
    currentVersion: current,
    latestVersion,
    releaseUrl: LATEST_RELEASE_URL,
    releaseName: typeof release.name === "string" ? release.name : null,
    publishedAt: typeof release.published_at === "string" ? release.published_at : null,
  };
}

const CHECKSUMS_ASSET_NAME = "SHA256SUMS-PC02.txt";

function installerFileName(version, platform = process.platform) {
  const normalized = String(version || "").replace(/^v/, "");
  if (platform === "win32") return `ZZ-Project-v${normalized}-Windows-Setup.exe`;
  if (platform === "linux") return `ZZ-Project-v${normalized}-Linux.tar.gz`;
  return null;
}

function parseChecksumMap(text) {
  const checksums = {};
  String(text || "").split(/\r?\n/).forEach((line) => {
    const match = /^([0-9a-fA-F]{64})\s+\*?(.+?)$/.exec(line.trim());
    if (!match) return;
    checksums[match[2].trim()] = match[1].toLowerCase();
  });
  return checksums;
}

function selectInstallerAsset(release, platform = process.platform) {
  if (!release || typeof release !== "object") {
    throw new Error("GitHub latest release is missing");
  }
  const version = parseVersion(release.tag_name).raw.replace(/^v/, "");
  const fileName = installerFileName(version, platform);
  if (!fileName) {
    throw new Error(`no packaged installer for platform ${platform}`);
  }
  const assets = Array.isArray(release.assets) ? release.assets : [];
  const installer = assets.find((asset) => asset && asset.name === fileName);
  if (!installer || typeof installer.browser_download_url !== "string") {
    throw new Error(`missing installer asset ${fileName}`);
  }
  const checksums = assets.find((asset) => asset && asset.name === CHECKSUMS_ASSET_NAME) || null;
  return {
    version,
    fileName,
    downloadUrl: installer.browser_download_url,
    checksumsUrl: checksums && typeof checksums.browser_download_url === "string"
      ? checksums.browser_download_url
      : null,
  };
}

module.exports = {
  CHECKSUMS_ASSET_NAME,
  LATEST_RELEASE_URL,
  PROJECT_WEBSITE_URL,
  RELEASE_API_URL,
  checkLatestRelease,
  compareVersions,
  installerFileName,
  parseChecksumMap,
  parseVersion,
  selectInstallerAsset,
};
