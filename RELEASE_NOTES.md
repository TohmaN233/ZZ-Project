# v0.2.0 - PC02 CONTRACT

## 本版内容

- 完整的 Game Lobby、卡组制作与本地卡牌对战流程。
- 卡池扩展为基本卡、EX01、PC01、PC01R 与 PC02 CONTRACT。
- PC02 的 100 张卡、Bless 机制、目标选择、触发器与边界流程已加入运行时。
- 人 VS AI、神视点、AI VS AI 三种单机模式。
- Easy Greedy CPU，以及 Medium / High 两档强化学习模型。
- Codeman 近期对战记忆、专属模型优先加载与局内 AI 建议。
- Replay 回看与本地实验训练入口。
- LAN 与个人服务器 Online Game。
- 中文、日本语、English 界面和三语规则书。
- 可选战斗 BGM、Codeman 与卡垫配置。

## 已知限制

- PC02 已加入，但个人测试无法覆盖所有卡牌组合，可能仍有小型规则或界面 Bug。
- AI 训练规模有限，强度与原版正式运营 AI 有明显差距。
- 电脑 AI 的训练数据和训练卡池目前只覆盖 PC01；PC01R、EX01、PC02 没有进入当前训练流程，不应期待电脑 AI 对新增卡包有可靠水平。
- 英文卡图和英文文本作为独立资源包发布；未覆盖的卡图仍可能回退到官网 URL，图片与卡牌错位问题仍可能存在。
- 公网服务器位于加拿大，跨地区稳定性没有充分验证；中国大陆通常需要代理。
- Story Mode 是未来目标，本版尚未实现。

## 下载组成

1. [`ZZ-Project-v0.2.0-source.zip`](https://github.com/TohmaN233/ZZ-Project/releases/download/v0.2.0/ZZ-Project-v0.2.0-source.zip)：v0.2.0 发布快照的程序、测试、文档与默认模型。
2. [`ZZ-Assets-PC02-v1.zip.001` 与 `.002`](https://drive.google.com/drive/folders/1R8NwBsR2QBvDHUwynZqLooZYI8TlX8TZ?usp=sharing)：主卡图、角色、卡垫、视频、音效与 BGM。两个 volume 都下载后，用 7-Zip 打开 `.001` 解压。
3. [`ZZ-Assets-PC02-English-v1.zip`](https://drive.google.com/drive/folders/1R8NwBsR2QBvDHUwynZqLooZYI8TlX8TZ?usp=sharing)：英文卡图、Force 与 Mana 卡面；英语用户将它叠加到主资源包上。

资源包校验：

```text
主资源包和英文资源包的 Bytes、文件数与 SHA-256 见
[`ASSET_PACK_MANIFEST.json`](ASSET_PACK_MANIFEST.json)。
```

资源包使用同一个 Google Drive 文件夹，主资源包的两个 volume 均不小于约 500 MB，便于稳定下载；英文包保持单个 ZIP。下载完整性与准确大小见 `ASSET_PACK_MANIFEST.json`。

## 致谢

特别感谢 theFeri 提供的 50+ 张高清 playmat 图，以及 **Valkyrie** 提供的英文文本。

详细步骤见 [INSTALL.md](INSTALL.md)。
