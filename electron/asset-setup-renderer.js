const statusNode = document.getElementById("status");
const progressNode = document.getElementById("progress");
const bytesNode = document.getElementById("bytes");
const destinationNode = document.getElementById("destination");
const cancelButton = document.getElementById("cancel");
const stages = {
  download: "正在下载游戏资源…",
  verify: "正在校验资源包…",
  extract: "正在解压游戏资源…",
  complete: "资源安装完成，正在启动游戏…",
};
function sizeText(bytes) { return `${(Number(bytes) / 1e9).toFixed(2)} GB`; }
window.assetSetup.onProgress((event) => {
  statusNode.textContent = stages[event.stage] || "正在准备游戏资源…";
  if (event.destination) destinationNode.textContent = `保存位置：${event.destination}`;
  if (Number.isFinite(event.percent)) progressNode.value = Math.max(0, Math.min(100, event.percent));
  else progressNode.removeAttribute("value");
  if (event.stage === "download") bytesNode.textContent = `${sizeText(event.receivedBytes || 0)} / ${sizeText(event.totalBytes)}（${Math.floor(event.percent || 0)}%）`;
  else bytesNode.textContent = event.stage === "complete" ? "完成后将自动进入游戏。" : "请稍候，关闭窗口可取消安装。";
  cancelButton.disabled = event.stage === "complete";
});
cancelButton.addEventListener("click", async () => {
  cancelButton.disabled = true;
  statusNode.textContent = "正在取消安装…";
  await window.assetSetup.cancel();
});
