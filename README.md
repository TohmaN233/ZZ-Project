# ZENONZARD Offline Project

[简体中文](README.md) | [日本語](README.ja.md) | [English](README.en.md)

一个非官方、非商业的 ZENONZARD 桌面游戏复现与 AI 实验项目，面向想体验本地对战、研究规则或参与开发的玩家。

[项目介绍网页](https://tohman233.github.io/ZZ-Project/) · [安装说明](INSTALL.md) · [联机说明](docs/ONLINE.md) · [中文规则书](docs/rules/zz_rulebook_zh.md)

## 系统要求

- Windows 10 或 11 可运行安装包；Linux 玩家可使用便携包；macOS 与开发者使用源码启动。
- 源码启动需要 Python 3.10+ 和 Node.js 20+。
- 普通对战无需独立 GPU；本地 AI 训练需要 NVIDIA GPU、兼容驱动和 CUDA 版 PyTorch。

## 安装

v0.5.2 的 Windows 版将卡组保存在安装目录的 `data/decks/`。首次启动时会从旧的 `%APPDATA%\zenonzard-clone\game-data\decks\` 迁移卡组，保留原文件作为备份，且不会覆盖冲突卡组。换手时选牌不再遮挡邻牌，启动失败时会显示诊断信息；为保护玩家数据，卸载时可能保留部分程序资源。联机握手要求双方客户端与所连接服务器的 `applicationVersion` 完全相同；连接前请确认三方版本一致。v0.5.1 的一键将当前卡组编辑器重置为空白新卡组的操作仍会保留已保存卡组，并保留卡牌检索、规则结算、Force 搜索和对战视觉反馈改进；本版本也继续包含 v0.5.0 加入的 EX02C/SAO 70 张卡（含 2 张 CAMPAIGN 卡）及其对应的 EX02 原版卡面。

[Windows 安装包](https://github.com/TohmaN233/ZZ-Project/releases/download/v0.5.2/ZZ-Project-v0.5.2-Windows-Setup.exe) · [Linux 便携包](https://github.com/TohmaN233/ZZ-Project/releases/download/v0.5.2/ZZ-Project-v0.5.2-Linux.tar.gz) · [源码包](https://github.com/TohmaN233/ZZ-Project/releases/download/v0.5.2/ZZ-Project-v0.5.2-source.zip) · [自建联机服务器](https://github.com/TohmaN233/ZZ-Project/releases/download/v0.5.2/ZZ-Multiplayer-v0.5.2.tar.gz) · [SHA256 校验清单](https://github.com/TohmaN233/ZZ-Project/releases/download/v0.5.2/SHA256SUMS-PC02.txt)

Windows 玩家使用安装包，Linux 玩家使用便携包；macOS 玩家和开发者使用源码包。完整步骤见[安装说明](INSTALL.md)。

首次启动时，如果缺少完整的 `asserts/`，客户端会询问是否下载 [Google Drive 资源文件夹](https://drive.google.com/drive/folders/1R8NwBsR2QBvDHUwynZqLooZYI8TlX8TZ)中的 `asserts.7z`，并自动校验、解压。资源包为 1.53 GB，解压后为 1.58 GB，请预留至少 3.2 GB 空间；取消下载会退出游戏。若安装目录为 Program Files，首次安装资源需以管理员身份启动；也可选择可写的安装目录。

源码启动前，在项目根目录安装依赖：

```powershell
python -m pip install -r requirements-runtime.txt
npm install
```

## 配置

默认界面语言为简体中文，对手 AI 默认难度为 High。游戏大厅可以切换难度；顶部栏或设置页可切换中文、日语和英语，并选择或关闭背景音乐。Easy 使用 Greedy 策略，Medium 和 High 使用项目提供的运行时模型。

## 快速开始

Windows 安装版从开始菜单或桌面快捷方式启动。Linux 便携包首次运行会在用户缓存目录准备运行时。源码版按平台启动：

```powershell
# Windows 源码启动
.\launch-electron.cmd
```

```bash
# Linux 或 macOS 源码启动
./launch-electron.sh
```

## 当前内容

- **对战与卡组**：支持人类对 AI、神视点和 AI 对 AI；可搜索卡池、编辑并保存卡组，也可一键将当前编辑器重置为空白新卡组（清空卡牌和 Force，并重置名称及筛选），且不删除已保存卡组。
- **Codeman 与本地训练**：本机保存近期对局记忆；源码版可在 GPU / CUDA 环境中进行实验训练。
- **Replay 与 AI 建议**：回看最近对局；对战中可查看 Codeman 对当前行动的建议。
- **联机**：支持局域网与公网房间。公网客户端默认连接 `wss://zz.tgy233.top/multiplayer`；自建服务器说明见[联机说明](docs/ONLINE.md)。
- **卡池与界面**：包含基本卡、EX01、PC01、PC01R、PC02、PC02R DIVINE 的 106 张卡，以及 EX02C/SAO 的 70 张卡与对应 EX02 原版卡面；支持简体中文、日语和英语界面。
- **卡牌呈现**：可在卡牌详情中预览变身形态；同名重印卡合并计算数量，套牌最多 3 张。

Story Mode 尚未实现。长期目标是设计由 Agent 自动与玩家交互的游戏，并实现 GAL 风格前端；项目也计划吸收 SillyTavern 社群在角色、世界书和长期互动方面的经验，打造玩家与自己的 Codeman 共同经历的 ZZ 体验。

## AI 水平说明

这个项目不会把实验模型包装成强 AI。作者有统计学学位，但没有修过强化学习课程，研究方向也与强化学习无关；个人项目的训练规模同样有限。当前模型与 ZENONZARD 正式运营时期万代使用的 AI 有明显差距，AI 建议也主要是娱乐功能。

电脑 AI 的训练卡池目前只覆盖 PC01。PC01R、EX01、PC02、PC02R DIVINE、EX02 和 EX02C/SAO 没有进入当前训练流程，因此不要期待电脑 AI 能正确理解这些卡包；规则可玩不代表 AI 已经学会这些卡。

AI 相关代码由 Codex 协助编写，并参考了 [sbl1996/ygo-agent](https://github.com/sbl1996/ygo-agent) 的公开方法与工程结构。更多说明见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

## 参与项目

欢迎通过[贡献指南](CONTRIBUTING.md)参与项目；开始前请先通过 Issue 或 Discussion 说明准备处理的内容，避免重复工作。

## 致谢

感谢 theFeri 提供 50 多张高清 playmat 图片，以及 **Valkyrie** 提供英文文本。

## 权利说明

本项目是非官方、非商业的粉丝开发与研究项目。ZENONZARD 名称、角色、卡图、音乐与相关素材的权利归各自权利方所有；本项目与 BANDAI、STRAIGHT EDGE、SUNRISE 无隶属或授权关系。

仓库未附项目代码的正式开源许可证。参考项目及第三方依赖的权利说明见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)，其内容不替代各自的许可证。
