const path = require("node:path");
const { assetRootLooksValid, formatAssetSize, installAssetBundle } = require("./asset-bootstrap");

async function ensureStartupAssets({ destination, source, dialog, BrowserWindow, ipcMain, fetchImpl,
  signal, onLog = () => {}, installImpl = installAssetBundle }) {
  if (assetRootLooksValid(destination)) return destination;
  if (signal?.aborted) return null;
  const spaceDetail = source.expandedBytes === undefined
    ? "解压还需要额外磁盘空间。"
    : `解压大小：${(source.expandedBytes / 1e9).toFixed(2)} GB\n安装期间请预留至少 ${((source.sizeBytes + source.expandedBytes + 64 * 1024 ** 2) / 1e9).toFixed(1)} GB 空闲空间。`;
  const consent = await dialog.showMessageBox({
    type: "question",
    title: "下载游戏资源",
    message: "未找到完整的 asserts 游戏资源。是否下载并自动安装？",
    detail: `文件：${source.fileName}\n下载大小：${(source.sizeBytes / 1e9).toFixed(2)} GB（${formatAssetSize(source.sizeBytes)}）\n保存位置：${destination}\n来源：${source.folderUrl}\n\n下载后会校验并自动解压。\n${spaceDetail}`,
    buttons: ["下载并安装", "退出"], defaultId: 0, cancelId: 1, noLink: true,
    signal,
  });
  if (consent.response !== 0 || signal?.aborted) return null;

  while (!signal?.aborted) {
    const controller = new AbortController();
    const abort = () => controller.abort();
    signal?.addEventListener("abort", abort, { once: true });
    const window = new BrowserWindow({
      width: 580, height: 400, resizable: false, backgroundColor: "#071117", autoHideMenuBar: true,
      webPreferences: { preload: path.join(__dirname, "asset-setup-preload.js"), contextIsolation: true, nodeIntegration: false, sandbox: true },
    });
    let closing = false;
    window.on("close", () => { if (!closing) controller.abort(); });
    window.webContents.on("will-navigate", (event) => event.preventDefault());
    window.webContents.setWindowOpenHandler(() => ({ action: "deny" }));
    ipcMain.handle("assets:cancel", (event) => {
      if (event.sender !== window.webContents) throw new Error("Untrusted asset-setup sender");
      controller.abort();
      return { cancelled: true };
    });
    let error = null;
    try {
      await window.loadFile(path.join(__dirname, "asset-setup.html"));
      onLog(`Asset install started: ${source.fileName}, ${source.sizeBytes} bytes -> ${destination}`);
      await installImpl({ destination, source, fetchImpl, signal: controller.signal,
        onProgress: (progress) => {
          if (!window.isDestroyed()) window.webContents.send("assets:progress", { ...progress, destination });
          if (progress.stage !== "download") onLog(`Asset install stage: ${progress.stage}`);
          if (typeof progress.percent === "number") window.setProgressBar(progress.percent / 100);
          else window.setProgressBar(2);
        },
      });
      if (controller.signal.aborted) return null;
      onLog(`Asset install completed: ${destination}`);
      return destination;
    } catch (failure) {
      error = failure;
      onLog(`Asset install ${controller.signal.aborted ? "cancelled" : "failed"}: ${failure.message || failure}`);
    } finally {
      closing = true;
      ipcMain.removeHandler("assets:cancel");
      signal?.removeEventListener("abort", abort);
      if (!window.isDestroyed()) window.destroy();
    }
    if (controller.signal.aborted || signal?.aborted) return null;
    const permissionHint = ["EACCES", "EPERM"].includes(error.code)
      ? "\n程序目录没有写入权限。请以管理员身份运行一次，或将程序放在可写目录。" : "";
    const choice = await dialog.showMessageBox({
      type: "error", title: "游戏资源安装失败", message: "资源尚未安装，游戏没有启动。",
      detail: `${error.message || error}${permissionHint}\n\n保存位置：${destination}\n手动下载：${source.folderUrl}`,
      buttons: ["重试", "退出"], defaultId: 1, cancelId: 1, noLink: true,
      signal,
    });
    if (choice.response !== 0) return null;
  }
  return null;
}

module.exports = { ensureStartupAssets };
