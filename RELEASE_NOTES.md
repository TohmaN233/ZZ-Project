# v0.1.0 - 首个公开版本

## 本版内容

- 完整的 Game Lobby、卡组制作与本地卡牌对战流程。
- 人 VS AI、神视点、AI VS AI 三种单机模式。
- Easy Greedy CPU，以及 Medium / High 两档强化学习模型。
- Codeman 近期对战记忆、专属模型优先加载与局内 AI 建议。
- Replay 回看与本地实验训练入口。
- LAN 与个人服务器 Online Game。
- 中文、日本语、English 界面和三语规则书。
- 可选战斗 BGM、Codeman 与卡垫配置。

## 已知限制

- 卡池目前包含基本卡与 PC01；之后会逐步更新，直至补全卡池。
- AI 训练规模有限，强度与原版正式运营 AI 有明显差距。
- 个人测试无法覆盖所有卡牌组合，可能仍有小型规则或界面 Bug。
- 英文版卡图直接使用官网 URL，已知存在图片与卡牌没有正确对齐的现象。
- 公网服务器位于加拿大，跨地区稳定性没有充分验证；中国大陆通常需要代理。
- Story Mode 是未来目标，本版尚未实现。

## 下载组成

1. GitHub 仓库 / Source Code：程序、测试、文档与当前默认模型。
2. [`ZZ-Assets-v1.zip`](https://drive.google.com/drive/folders/1R8NwBsR2QBvDHUwynZqLooZYI8TlX8TZ?usp=sharing)：卡图、角色、卡垫、视频、音效与 BGM。

资源包校验：

```text
Bytes: 917038889
SHA-256: A9E93A67FAD1BEBCDE4B790D0EE3C2C7F351191ECBAB1658FEF688E46260F5D8
```

详细步骤见 [INSTALL.md](INSTALL.md)。
