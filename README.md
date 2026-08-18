# ZENONZARD Offline Project

[简体中文](README.md) | [日本語](README.ja.md) | [English](README.en.md)

一个非官方、非商业的 ZENONZARD 桌面端复现与 AI 实验项目。

[项目介绍网页](https://tohman233.github.io/ZZ-Project/) · [安装说明](INSTALL.md) · [联机说明](docs/ONLINE.md) · [中文规则书](docs/rules/zz_rulebook_zh.md)

## 当前版本包含什么

- **Game Lobby**：选择双方卡组、Codeman、卡垫、先后手和 AI 难度。
- **卡组制作**：搜索卡池，编辑并保存可直接用于对战的卡组。
- **三种单机模式**：普通人 VS AI、可见并控制双方的神视点、AI VS AI。
- **三档 AI**：Easy 为 Greedy CPU；Medium 与 High 使用强化学习模型。
- **Codeman 记忆**：在本机保存最近的部分对局与 Replay；存在专属 `.pt` 时优先作为该 Codeman 的对战模型。
- **AI 建议**：对战时点击自己的 Codeman，可以查看当前选择的 AI 建议。
- **Replay & Training**：回看最近牌局；具备 GPU / CUDA 环境时可进行本地实验训练。
- **Online Game**：支持局域网与个人服务器联机；双方以石头剪刀布决定先手，对局结束后保留原房间，可换卡组直接再战。
- **三语界面**：中文、日本語、English。
- **BGM 设置**：完整资源包提供 ZZ 角色歌曲。
- **版本检查**：桌面客户端启动时检查 GitHub 最新 Release；发现新版本后可直接打开发布页。
- **跨平台启动**：Windows 提供安装包；Linux 提供 portable `tar.gz` bundle；macOS 与开发者使用源码 `.sh`。本次发布移除了单独的 `.command` launcher。

Story Mode 还没有开发。长期目标是设计由 Agent 自动与用户交互的游戏，对应实现 GAL 前端，并吸收 SillyTavern 相关社群在角色、世界书与长期互动方面积累的经验，构建个人专属的、与自己的 Codeman 一起经历的 ZZ 体验。

## AI 水平说明

这个项目不会把实验模型包装成强 AI。作者有统计学学位，但没有修过强化学习课程，研究方向也与强化学习无关；个人项目的训练规模同样有限。当前模型与 ZENONZARD 正式运营时期万代使用的 AI 有明显差距，AI 建议也主要是娱乐功能。

特别说明：电脑 AI 的训练数据和训练卡池目前只覆盖 PC01。PC01R、EX01 和 PC02 没有进入这套训练流程，因此不要期待电脑 AI 能正确理解新增卡包；PC02 的规则可玩性不代表 AI 已经学会这些卡。

AI 相关代码由 Codex 协助编写，并参考了 [sbl1996/ygo-agent](https://github.com/sbl1996/ygo-agent) 的公开方法与工程结构。详见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

## 安装

Windows 玩家推荐直接下载并运行 [ZZ-Project-v0.3.1-Windows-Setup.exe](https://github.com/TohmaN233/ZZ-Project/releases/download/v0.3.1/ZZ-Project-v0.3.1-Windows-Setup.exe)。安装器已经包含可玩的桌面客户端、冻结后的 Python server、规则代码和默认模型，不需要 Python 或 Node.js。大型资源仍从 [Google Drive 资源文件夹](https://drive.google.com/drive/folders/1R8NwBsR2QBvDHUwynZqLooZYI8TlX8TZ?usp=sharing) 下载：主资源包的两个 ZIP volumes `ZZ-Assets-PC02-v1.zip.001` 与 `ZZ-Assets-PC02-v1.zip.002` 都下载后，用 7-Zip 打开 `.001`，将得到的 `asserts/` 放到安装目录，与 `ZZ-Project.exe` 同级。需要英文卡图的玩家再下载单独的 `ZZ-Assets-PC02-English-v1.zip`，解压到同一个 `asserts/`。完整步骤、目录结构和源码启动方式见 [INSTALL.md](INSTALL.md)。想自己搭联机服务器时，只下载 Release 里最新的 `ZZ-Multiplayer-*.tar.gz`，步骤见 [docs/ONLINE.md](docs/ONLINE.md)。

Linux 玩家下载 [ZZ-Project-v0.3.1-Linux.tar.gz](https://github.com/TohmaN233/ZZ-Project/releases/download/v0.3.1/ZZ-Project-v0.3.1-Linux.tar.gz)，解压后运行 `./launch-electron.sh`；首次启动会在用户缓存目录准备运行时。macOS 玩家与开发者使用 [ZZ-Project-v0.3.1-source.zip](https://github.com/TohmaN233/ZZ-Project/releases/download/v0.3.1/ZZ-Project-v0.3.1-source.zip)，再按安装说明安装依赖。

```powershell
python -m pip install -r requirements-runtime.txt
npm install
```

随后将资源包中的 `asserts/` 放到仓库根目录，并按平台运行：

```powershell
# Windows
.\launch-electron.cmd
```

```bash
# Linux
./launch-electron.sh

# macOS (source launch)
./launch-electron.sh
```

## 内容边界

当前卡池包含基本卡、EX01、PC01、PC01R 与 PC02。个人测试无法覆盖全部卡牌组合，因此可能仍有小型规则或界面 Bug。

英文卡图和英文文本作为独立资源包发布；未覆盖的卡图仍可能回退到官网链接，已知存在图片与卡牌没有对齐的现象。

## 致谢

特别感谢 theFeri 提供的 50+ 张高清 playmat 图，以及 **Valkyrie** 提供的英文文本。

## 参与项目

特别欢迎有强化学习经验的贡献者一起研究能否训练出更适合离线运行的 ZZ AI。卡牌资料、英文图片与译文、规则测试、Bug 报告也都很重要，请通过 Issues 或 Discussions 联系。

## 权利说明

本项目是非官方、非商业的粉丝开发与研究项目。ZENONZARD 名称、角色、卡图、音乐与相关素材的权利归各自权利方所有；本项目与 BANDAI、STRAIGHT EDGE、SUNRISE 无隶属或授权关系。

仓库代码的正式开源许可证将在首个公开版本发布前确定；第三方依赖与参考项目继续适用各自许可证。
