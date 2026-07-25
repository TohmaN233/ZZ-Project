"use strict";

const assert = require("node:assert/strict");
const { test } = require("node:test");

const {
  LATEST_RELEASE_URL,
  RELEASE_API_URL,
  checkLatestRelease,
  compareVersions,
} = require("../electron/update-checker");

function githubResponse(tagName, overrides = {}) {
  return {
    ok: true,
    status: 200,
    json: async () => ({
      tag_name: tagName,
      name: `Release ${tagName}`,
      published_at: "2026-07-25T00:00:00Z",
      ...overrides,
    }),
  };
}

test("semantic version comparison handles v prefixes and prereleases", () => {
  assert.equal(compareVersions("0.1.0", "v0.1.1"), -1);
  assert.equal(compareVersions("v1.2.3", "1.2.3"), 0);
  assert.equal(compareVersions("1.2.3-beta.2", "1.2.3-beta.10"), -1);
  assert.equal(compareVersions("1.2.3", "1.2.3-rc.1"), 1);
  assert.throws(() => compareVersions("development", "1.0.0"), /invalid semantic version/);
});

test("latest GitHub release reports an available update", async () => {
  let request = null;
  const result = await checkLatestRelease({
    currentVersion: "0.1.0",
    fetchImpl: async (url, options) => {
      request = { url, options };
      return githubResponse("v0.2.0");
    },
  });

  assert.equal(request.url, RELEASE_API_URL);
  assert.equal(request.options.headers.Accept, "application/vnd.github+json");
  assert.equal(request.options.headers["X-GitHub-Api-Version"], "2026-03-10");
  assert.deepEqual(result, {
    status: "available",
    currentVersion: "0.1.0",
    latestVersion: "0.2.0",
    releaseUrl: LATEST_RELEASE_URL,
    releaseName: "Release v0.2.0",
    publishedAt: "2026-07-25T00:00:00Z",
  });
});

test("current release and GitHub failures remain explicit", async () => {
  const current = await checkLatestRelease({
    currentVersion: "0.1.0",
    fetchImpl: async () => githubResponse("v0.1.0"),
  });
  assert.equal(current.status, "current");

  await assert.rejects(
    checkLatestRelease({
      currentVersion: "0.1.0",
      fetchImpl: async () => ({ ok: false, status: 403, json: async () => ({}) }),
    }),
    /HTTP 403/,
  );
  await assert.rejects(
    checkLatestRelease({
      currentVersion: "0.1.0",
      fetchImpl: async () => githubResponse(null),
    }),
    /missing tag_name/,
  );
});
