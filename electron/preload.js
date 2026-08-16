const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("zzDesktop", {
  startServer: (options = {}) => ipcRenderer.invoke("server:start", options),
  stopServer: () => ipcRenderer.invoke("server:stop"),
  serverStatus: () => ipcRenderer.invoke("server:status"),
  openFolder: () => ipcRenderer.invoke("dialog:openFolder"),
  openPath: (targetPath) => ipcRenderer.invoke("shell:openPath", targetPath),
  openReplayWindow: (payload) => ipcRenderer.invoke("replay:openWindow", payload),
  selectAssetRoot: () => ipcRenderer.invoke("assets:selectRoot"),
  selectDeckRoot: () => ipcRenderer.invoke("decks:selectRoot"),
  getVersion: () => ipcRenderer.invoke("app:getVersion"),
  checkForUpdates: () => ipcRenderer.invoke("app:checkForUpdates"),
  openReleasePage: () => ipcRenderer.invoke("app:openReleasePage"),
  quit: () => ipcRenderer.invoke("app:quit"),
});

contextBridge.exposeInMainWorld("zzMultiplayer", {
  status: () => ipcRenderer.invoke("multiplayer:status"),
  connect: (config) => ipcRenderer.invoke("multiplayer:connect", config),
  disconnect: () => ipcRenderer.invoke("multiplayer:disconnect"),
  reconnect: () => ipcRenderer.invoke("multiplayer:reconnect"),
  createRoom: (payload) => ipcRenderer.invoke("multiplayer:createRoom", payload),
  joinRoom: (payload) => ipcRenderer.invoke("multiplayer:joinRoom", payload),
  selectDeck: (payload) => ipcRenderer.invoke("multiplayer:selectDeck", payload),
  setReady: (ready) => ipcRenderer.invoke("multiplayer:setReady", ready),
  selectOpeningChoice: (choice) => ipcRenderer.invoke("multiplayer:selectOpeningChoice", choice),
  submitAction: (action) => ipcRenderer.invoke("multiplayer:submitAction", action),
  surrender: () => ipcRenderer.invoke("multiplayer:surrender"),
  requestSync: () => ipcRenderer.invoke("multiplayer:requestSync"),
  leaveRoom: () => ipcRenderer.invoke("multiplayer:leaveRoom"),
  lanStatus: () => ipcRenderer.invoke("multiplayer:lanStatus"),
  startLanHost: (options) => ipcRenderer.invoke("multiplayer:startLanHost", options),
  stopLanHost: () => ipcRenderer.invoke("multiplayer:stopLanHost"),
  discoverLan: (options) => ipcRenderer.invoke("multiplayer:discoverLan", options),
  onEvent: (callback) => {
    if (typeof callback !== "function") throw new TypeError("callback must be a function");
    const listener = (_event, payload) => callback(payload);
    ipcRenderer.on("multiplayer:event", listener);
    return () => ipcRenderer.removeListener("multiplayer:event", listener);
  },
});
