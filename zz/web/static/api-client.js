(function () {
  async function request(path, body = null, options = {}) {
    const method = options.method || (body === null ? "GET" : "POST");
    const init = { method };
    if (body !== null && method !== "GET") {
      init.headers = { "Content-Type": "application/json" };
      init.body = JSON.stringify(body);
    }
    const response = await fetch(path, init);
    return response.json();
  }

  function get(path) {
    return request(path);
  }

  function post(path, body = {}) {
    return request(path, body);
  }

  function del(path) {
    return request(path, null, { method: "DELETE" });
  }

  const desktop = {
    serverStatus: () => window.zzDesktop && window.zzDesktop.serverStatus
      ? window.zzDesktop.serverStatus()
      : Promise.resolve(null),
    openFolder: () => window.zzDesktop && window.zzDesktop.openFolder
      ? window.zzDesktop.openFolder()
      : Promise.resolve(null),
    openPath: (targetPath) => window.zzDesktop && window.zzDesktop.openPath
      ? window.zzDesktop.openPath(targetPath)
      : Promise.resolve(null),
    openReplayWindow: (payload) => window.zzDesktop && window.zzDesktop.openReplayWindow
      ? window.zzDesktop.openReplayWindow(payload)
      : Promise.resolve({ ok: false, unavailable: true }),
    checkForUpdates: () => window.zzDesktop && window.zzDesktop.checkForUpdates
      ? window.zzDesktop.checkForUpdates()
      : Promise.resolve({ status: "unavailable" }),
    openReleasePage: () => window.zzDesktop && window.zzDesktop.openReleasePage
      ? window.zzDesktop.openReleasePage()
      : Promise.resolve({ ok: false, unavailable: true }),
    downloadAndInstallUpdate: () => window.zzDesktop && window.zzDesktop.downloadAndInstallUpdate
      ? window.zzDesktop.downloadAndInstallUpdate()
      : Promise.resolve({ ok: false, unavailable: true, error: "desktop client required" }),
    onUpdateDownloadProgress: (callback) => window.zzDesktop && window.zzDesktop.onUpdateDownloadProgress
      ? window.zzDesktop.onUpdateDownloadProgress(callback)
      : () => {},
    quit: () => window.zzDesktop && window.zzDesktop.quit
      ? window.zzDesktop.quit()
      : Promise.resolve({ ok: false, unavailable: true }),
  };

  window.ZZApi = { request, get, post, delete: del, desktop };
})();
