# 安装说明

当前发布把 **源码与默认模型** 放在 GitHub，把约 900 MB 的 **卡图、角色图、卡垫、视频与 BGM** 放在独立资源包中。两部分都准备好后，桌面客户端才能显示完整内容。

## 1. 系统要求

- Windows 10 或 Windows 11
- Linux 或 macOS 可从源码启动，目前属于实验支持，尚不提供打包安装程序
- Python 3.10 或更高版本
- Node.js 20 或更高版本
- Git LFS（仅在使用 `git clone` 时需要）
- 普通游玩不要求独立显卡
- 本地 AI 训练需要 NVIDIA GPU、匹配的驱动与 CUDA 版 PyTorch

## 2. 下载源码

推荐从 GitHub Releases 下载源码压缩包。开发者也可以使用：

```powershell
git lfs install
git clone https://github.com/TohmaN233/ZZ-Project.git
cd ZZ-Project
```

`.pt` 默认模型由 Git LFS 管理。克隆后如果模型文件只有几百字节，请执行：

```powershell
git lfs pull
```

## 3. 安装依赖

在项目根目录打开 PowerShell：

```powershell
python -m pip install -r requirements-runtime.txt
npm install
```

默认的 PyTorch 包可在 CPU 上运行对战 AI。需要 CUDA 时，请按照 [PyTorch 官方安装选择器](https://pytorch.org/get-started/locally/) 安装与你的显卡驱动匹配的版本，再执行其余依赖安装。

## 4. 安装完整资源包

[从 Google Drive 下载 `ZZ-Assets-v1.zip`](https://drive.google.com/drive/folders/1R8NwBsR2QBvDHUwynZqLooZYI8TlX8TZ?usp=sharing)，在项目根目录解压。正确结构如下：

```text
ZZ-Project/
├─ asserts/
│  ├─ ZENONZARD_CARDLIST/
│  ├─ audio/
│  │  ├─ battle_sfx/
│  │  └─ bgm/
│  ├─ card_back/
│  ├─ images/
│  │  └─ clean_graph/
│  │     ├─ characters/
│  │     ├─ playmats/
│  │     └─ ui/
│  └─ video/
├─ data/
├─ electron/
├─ zz/
├─ launch-electron.cmd
├─ launch-electron.sh
└─ launch-electron.command
```

资源包中的目录名与程序引用路径全部使用 ASCII 英文字符，避免不同系统区域设置导致的路径乱码。

发布页面会列出资源包大小和 SHA-256。下载后可以验证：

```powershell
Get-FileHash .\ZZ-Assets-v1.zip -Algorithm SHA256
```

输出应与发布页面和 `ASSET_PACK_MANIFEST.json` 中的值一致。

## 5. 启动桌面客户端

Windows 双击或在 PowerShell 运行：

```text
launch-electron.cmd
```

Linux 在终端运行：

```bash
./launch-electron.sh
```

macOS 在终端运行，也可以双击 `.command` 文件：

```bash
./launch-electron.command
```

Linux/macOS 启动器会优先使用 `python3`，也可以提前设置 `ZZ_PYTHON` 指定解释器。若下载工具移除了执行权限，先运行：

```bash
chmod +x launch-electron.sh launch-electron.command
```

所有平台也都可以直接运行：

```powershell
npm run electron:dev
```

桌面客户端启动后会自动读取 GitHub 最新 Release。仅在发现更高版本时显示更新提示；网络检查失败不会阻止离线游玩，诊断信息会写入 Electron 日志。原生 `Help` 菜单提供项目发布页与最新 Release 入口。

首次进入后可以在 `Setting` 中切换中文、日本语、English 和对战 BGM。

开发者模式默认关闭且没有内置密码。确实需要调试功能时，请在启动前设置仅本机使用的环境变量：

```powershell
$env:ZZ_DEV_MODE_PASSWORD = "请替换为你自己的密码"
npm run electron:dev
```

不要把这个值写入仓库或公开的启动脚本。

## 6. 仅运行浏览器前端

```powershell
python -m zz.web.server --host 127.0.0.1 --port 8765 --asset-root .\asserts
```

然后访问 `http://127.0.0.1:8765/`。

## 7. 联机

- **LAN**：房主在 Online Game 中启动局域网房间，同一网络的玩家使用界面显示的地址加入。
- **Internet**：默认个人服务器位于加拿大，其他地区稳定性未经充分验证；中国大陆通常需要代理。

完整说明见 [docs/ONLINE.md](docs/ONLINE.md)。

## 8. 可选：本地 AI 训练

本地训练是实验与娱乐功能，不是正常游玩的必需步骤。

1. 安装 NVIDIA 驱动与 CUDA 版 PyTorch。
2. 在 Replay & Training 中积累本机对局记录。
3. 从客户端训练入口启动任务，或使用 `ai_training/` 下的命令行工具。
4. 某个 Codeman 的专门训练若成功生成 `.pt`，运行时会优先加载其专属模型。

训练可能消耗大量显存、时间与磁盘空间。不要把本机生成的 `data/codeman_ai/`、`data/ai_challenges/` 或训练目录提交到公共仓库。

## 9. 常见问题

### 卡图、角色或音乐缺失

确认 `asserts/` 是项目根目录的直接子目录，而不是 `asserts/asserts/`。检查 `asserts/images` 和 `asserts/ZENONZARD_CARDLIST` 是否存在。

### 英文卡图缺失

英文版卡图直接使用官网 URL，已知存在图片与卡牌没有正确对齐的现象。英语圈用户若能提供卡图资源和对应英文文本，此问题可以轻易解决。

### High AI 启动时报模型错误

确认 Git LFS 已完整下载模型，并重新执行 `git lfs pull`。不要用空文件或其他模型覆盖清单中的默认模型。

### Online Game 无法连接

先用 LAN 模式排除本机防火墙问题。公网服务器位于加拿大，跨地区网络可能不稳定；详见联机文档。
