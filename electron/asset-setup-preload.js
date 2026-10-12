const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("assetSetup", {
  cancel: () => ipcRenderer.invoke("assets:cancel"),
  onProgress: (callback) => {
    const listener = (_event, progress) => callback(progress);
    ipcRenderer.on("assets:progress", listener);
    return () => ipcRenderer.removeListener("assets:progress", listener);
  },
});
