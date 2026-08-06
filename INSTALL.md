# 安装说明

当前发布把 **可直接运行的 Windows 桌面程序、源码与默认模型** 放在 GitHub，把 **卡图、角色图、卡垫、视频与 BGM** 放在独立资源包中。英文卡图也单独提供一个覆盖包。程序包与资源包都准备好后，桌面客户端才能显示完整内容。

## 1. 系统要求

- Windows 10 或 Windows 11
- Linux 或 macOS 可从源码启动，目前属于实验支持，尚不提供原生安装程序
- Windows 安装包用户不需要预装 Python 或 Node.js
- 源码启动用户需要 Python 3.10 或更高版本、Node.js 20 或更高版本
- Git LFS（仅在使用 `git clone` 时需要）
- 7-Zip（从 Google Drive 下载主资源包的两个 ZIP volumes 时需要）
- 普通游玩不要求独立显卡
- 本地 AI 训练需要 NVIDIA GPU、匹配的驱动与 CUDA 版 PyTorch

## 2. Windows 安装包（推荐）

Windows 玩家直接下载并运行 [ZZ-Project-v0.2.0-Windows-Setup.exe](https://github.com/TohmaN233/ZZ-Project/releases/download/v0.2.0/ZZ-Project-v0.2.0-Windows-Setup.exe)。安装器已经包含 Electron 桌面客户端、冻结后的 Python server、规则代码和当前默认模型，不需要安装 Python、Node.js 或执行 `npm install`。安装完成后，从开始菜单或桌面快捷方式启动 `ZZ-Project`。

安装器不包含大型 `asserts/` 资源。请继续按照第 5 节下载主资源包；用 7-Zip 解压后，把得到的 `asserts/` 文件夹放到安装目录中，与 `ZZ-Project.exe` 同级：

```text
<安装目录>/
├─ ZZ-Project.exe
└─ asserts/
   ├─ ZENONZARD_CARDLIST/
   ├─ images/
   └─ ...
```

英文版玩家再把 `ZZ-Assets-PC02-English-v1.zip` 解压到同一个 `asserts/`，使其写入 `asserts/Eng-cards/`。如果安装器安装到了没有写入权限的目录，请在安装时选择一个你有权限的目录，或先在其他位置解压后将 `asserts/` 复制进去。

安装器 SHA-256：`404889972E070EB5D5A77CCC4B81763390237C51F68541D467006919C8808667`；文件大小：`197377656` bytes。

## 3. 下载源码

推荐从 GitHub Releases 下载明确标注的
[`ZZ-Project-v0.2.0-source.zip`](https://github.com/TohmaN233/ZZ-Project/releases/download/v0.2.0/ZZ-Project-v0.2.0-source.zip)。
该附件包含本次 v0.2.0 发布快照的实际默认模型；不要使用页面底部由旧版 tag 自动生成的
`Source code` 压缩包。开发者也可以使用：

```powershell
git lfs install
git clone https://github.com/TohmaN233/ZZ-Project.git
cd ZZ-Project
```

`.pt` 默认模型由 Git LFS 管理。克隆后如果模型文件只有几百字节，请执行：

```powershell
git lfs pull
```

## 4. 安装依赖

在项目根目录打开 PowerShell：

```powershell
python -m pip install -r requirements-runtime.txt
npm install
```

默认的 PyTorch 包可在 CPU 上运行对战 AI。需要 CUDA 时，请按照 [PyTorch 官方安装选择器](https://pytorch.org/get-started/locally/) 安装与你的显卡驱动匹配的版本，再执行其余依赖安装。

## 5. 安装资源包

从 [Google Drive 资源文件夹](https://drive.google.com/drive/folders/1R8NwBsR2QBvDHUwynZqLooZYI8TlX8TZ?usp=sharing)下载主资源包的两个 volumes：`ZZ-Assets-PC02-v1.zip.001` 与 `ZZ-Assets-PC02-v1.zip.002`。两个文件都下载完成后，用 7-Zip 打开 `.001`，它会自动读取 `.002`，并将内容解压到项目根目录。不要只下载其中一个 volume。需要英文卡图的玩家再下载单独的 `ZZ-Assets-PC02-English-v1.zip`，同样在项目根目录解压。英文包会写入 `asserts/Eng-cards/`，不会覆盖主资源包。正确结构如下：

```text
ZZ-Project/
├─ asserts/
│  ├─ ZENONZARD_CARDLIST/
│  ├─ Eng-cards/              # optional English card/Force/Mana faces
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
└─ launch-electron.sh
```

资源包中的目录名与程序引用路径全部使用 ASCII 英文字符，避免不同系统区域设置导致的路径乱码。

发布页面会列出两个资源包的大小和 SHA-256。下载后可以验证：

```powershell
Get-FileHash .\ZZ-Assets-PC02-v1.zip.001 -Algorithm SHA256
Get-FileHash .\ZZ-Assets-PC02-v1.zip.002 -Algorithm SHA256
Get-FileHash .\ZZ-Assets-PC02-English-v1.zip -Algorithm SHA256
```

输出应与发布页面和 `ASSET_PACK_MANIFEST.json` 中的 volume/archive 值一致。主资源包两个 volume 的大小分别为 629145600 bytes 和 576401952 bytes；英文包为 195374917 bytes。

## 6. 启动桌面客户端

使用 Windows 安装包时，直接从开始菜单或桌面快捷方式启动 `ZZ-Project`。下面的 launcher 仅用于源码版本：

Windows 双击或在 PowerShell 运行：

```text
launch-electron.cmd
```

Linux 在终端运行：

```bash
./launch-electron.sh
```

macOS 也可以在终端运行同一个 `.sh` launcher：

```bash
./launch-electron.sh
```

Linux/macOS 启动器会优先使用 `python3`，也可以提前设置 `ZZ_PYTHON` 指定解释器。若下载工具移除了执行权限，先运行：

```bash
chmod +x launch-electron.sh
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

## 7. 仅运行浏览器前端

```powershell
python -m zz.web.server --host 127.0.0.1 --port 8765 --asset-root .\asserts
```

然后访问 `http://127.0.0.1:8765/`。

## 8. 联机

- **LAN**：房主在 Online Game 中启动局域网房间，同一网络的玩家使用界面显示的地址加入。
- **Internet**：默认个人服务器位于加拿大，其他地区稳定性未经充分验证；中国大陆通常需要代理。

完整说明见 [docs/ONLINE.md](docs/ONLINE.md)。

## 9. 可选：本地 AI 训练

本地训练是实验与娱乐功能，不是正常游玩的必需步骤。

Windows 安装包是面向直接游玩的精简版本，不携带训练依赖；需要运行训练时请下载源码包，并按本节安装 CUDA 版 PyTorch。

当前发布的电脑 AI 训练只使用 PC01 卡池。PC01R、EX01 和 PC02 的规则已经可以游玩，但没有进入当前模型的训练数据，因此不要把新增卡包的电脑 AI 表现当作强度保证。

1. 安装 NVIDIA 驱动与 CUDA 版 PyTorch。
2. 在 Replay & Training 中积累本机对局记录。
3. 从客户端训练入口启动任务，或使用 `ai_training/` 下的命令行工具。
4. 某个 Codeman 的专门训练若成功生成 `.pt`，运行时会优先加载其专属模型。

训练可能消耗大量显存、时间与磁盘空间。不要把本机生成的 `data/codeman_ai/`、`data/ai_challenges/` 或训练目录提交到公共仓库。

## 10. 常见问题

### 卡图、角色或音乐缺失

确认两个主资源 volume 都已下载，并且使用 7-Zip 打开 `.001`，而不是只解压单个 volume。源码版本中确认 `asserts/` 是项目根目录的直接子目录；Windows 安装包版本中确认它与 `ZZ-Project.exe` 同级，而不是 `asserts/asserts/`。检查 `asserts/images` 和 `asserts/ZENONZARD_CARDLIST` 是否存在。

### 英文卡图缺失

确认已经额外下载并解压 `ZZ-Assets-PC02-English-v1.zip`，且路径为 `asserts/Eng-cards/`。本地包未覆盖的卡仍可能使用官网 URL，存在图片与卡牌没有正确对齐的现象。

### High AI 启动时报模型错误

确认 Git LFS 已完整下载模型，并重新执行 `git lfs pull`。不要用空文件或其他模型覆盖清单中的默认模型。

### Online Game 无法连接

先用 LAN 模式排除本机防火墙问题。公网服务器位于加拿大，跨地区网络可能不稳定；详见联机文档。
