# ZENONZARD Offline Project

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
- **Online Game**：支持局域网与个人服务器联机。
- **三语界面**：中文、日本語、English。
- **BGM 设置**：完整资源包提供 ZZ 角色歌曲。
- **版本检查**：桌面客户端启动时检查 GitHub 最新 Release；发现新版本后可直接打开发布页。
- **跨平台启动**：Windows 使用 `.cmd`，Linux 使用 `.sh`，macOS 使用 `.command`。Linux/macOS 当前为源码启动的实验支持。

Story Mode 还没有开发。长期目标是设计由 Agent 自动与用户交互的游戏，对应实现 GAL 前端，并吸收 SillyTavern 相关社群在角色、世界书与长期互动方面积累的经验，构建个人专属的、与自己的 Codeman 一起经历的 ZZ 体验。

## AI 水平说明

这个项目不会把实验模型包装成强 AI。作者有统计学学位，但没有修过强化学习课程，研究方向也与强化学习无关；个人项目的训练规模同样有限。当前模型与 ZENONZARD 正式运营时期万代使用的 AI 有明显差距，AI 建议也主要是娱乐功能。

AI 相关代码由 Codex 协助编写，并参考了 [sbl1996/ygo-agent](https://github.com/sbl1996/ygo-agent) 的公开方法与工程结构。详见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

## 安装

源码与大型美术资源分开发布。[下载完整资源包（ZZ-Assets-v1.zip）](https://drive.google.com/file/d/1Nsa2dPwuDrpE40P3hWx-OAqbOrAonGZI/view?usp=sharing)。完整步骤、目录结构和常见问题见 [INSTALL.md](INSTALL.md)。最短流程：

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

# macOS
./launch-electron.command
```

## 内容边界

当前卡池包含基本卡与 PC01，之后会逐步更新，直至补全卡池。个人测试无法覆盖全部卡牌组合，因此可能仍有小型规则或界面 Bug。

英文版卡图直接使用官网链接，已知有图和卡没对齐的现象。英语圈的用户若能提供卡图资源和英文文本，此问题能轻易解决。

## 参与项目

特别欢迎有强化学习经验的贡献者一起研究能否训练出更适合离线运行的 ZZ AI。卡牌资料、英文图片与译文、规则测试、Bug 报告也都很重要，请通过 Issues 或 Discussions 联系。

## 权利说明

本项目是非官方、非商业的粉丝开发与研究项目。ZENONZARD 名称、角色、卡图、音乐与相关素材的权利归各自权利方所有；本项目与 BANDAI、STRAIGHT EDGE、SUNRISE 无隶属或授权关系。

仓库代码的正式开源许可证将在首个公开版本发布前确定；第三方依赖与参考项目继续适用各自许可证。
