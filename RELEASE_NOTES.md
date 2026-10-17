# v0.4.1 - Multiplayer Regression Fix

[简体中文](README.md) | [日本語](README.ja.md) | [English](README.en.md)

## 简体中文

修复联机模式的回归：对手确认开局换牌后，对局可能卡死、手牌动画无法完成且无法继续操作。

双方客户端及自建服务器均需更新至 0.4.1。已有完整 `asserts/` 资源可继续使用，无需重新下载。

## 日本語

オンライン対戦の不具合を修正しました。相手が開始時の手札交換を確定すると、手札アニメーションが完了せず、対戦を続けられなくなる問題です。

両者のクライアントと自設サーバーを 0.4.1 に更新してください。既存の完全な `asserts/` はそのまま使用できます。

## English

Fixed a multiplayer regression where confirming the opponent's opening mulligan could freeze the duel, leaving hand animations unfinished and blocking further actions.

Update both clients and any self-hosted server to 0.4.1. Existing complete `asserts/` assets can be reused without downloading them again.

## Downloads

- [Windows installer](https://github.com/TohmaN233/ZZ-Project/releases/download/v0.4.1/ZZ-Project-v0.4.1-Windows-Setup.exe)
- [Linux portable bundle](https://github.com/TohmaN233/ZZ-Project/releases/download/v0.4.1/ZZ-Project-v0.4.1-Linux.tar.gz)
- [Source package](https://github.com/TohmaN233/ZZ-Project/releases/download/v0.4.1/ZZ-Project-v0.4.1-source.zip)
- [Self-hosted multiplayer server](https://github.com/TohmaN233/ZZ-Project/releases/download/v0.4.1/ZZ-Multiplayer-v0.4.1.tar.gz)
- [SHA256 checksums](https://github.com/TohmaN233/ZZ-Project/releases/download/v0.4.1/SHA256SUMS-PC02.txt)

Package sizes and SHA-256 values are recorded in [PUBLIC_RELEASE_MANIFEST.json](PUBLIC_RELEASE_MANIFEST.json).
See [INSTALL.md](INSTALL.md) for setup and [docs/ONLINE.md](docs/ONLINE.md) for online play and self-hosting.
