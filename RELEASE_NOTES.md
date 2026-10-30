# v0.5.1 - Deck Builder Clear Action

[简体中文](README.md) | [日本語](README.ja.md) | [English](README.en.md)

## 简体中文

- **卡组编辑器**：新增一键将当前编辑器重置为空白新卡组的操作，会清空卡牌和 Force，并重置名称及搜索筛选；已保存的卡组不会被删除。
- **联机兼容性**：联机握手要求客户端与服务器的 `applicationVersion` 完全一致；双方客户端和服务器（包括自建服务器）均须使用 v0.5.1。
- **卡池**：继续包含 v0.5.0 加入的 EX02C/SAO 70 张卡（含 2 张 CAMPAIGN 卡）及其对应的 EX02 原版卡面。

## 日本語

- **デッキ編集**：編集中のデッキをワンクリックで空の新規デッキにリセットできます。カードと Force はクリアされ、名前と検索フィルターは初期状態に戻りますが、保存済みデッキは削除されません。
- **オンライン互換性**：クライアントとサーバーの `applicationVersion` が完全に一致する必要があります。双方とサーバー（自設サーバーを含む）に v0.5.1 を使用してください。
- **カードプール**：v0.5.0 で追加した EX02C/SAO の 70 枚（CAMPAIGN 2 枚を含む）と、対応する EX02 オリジナルカード面も引き続き含まれます。

## English

- **Deck builder**: Reset the current editor to a blank new deck with one click, clearing cards and Forces and resetting the name and search filters without deleting saved decks.
- **Online compatibility**: The client and server `applicationVersion` values must match exactly. Both players and the server, including self-hosted servers, must use v0.5.1.
- **Card pool**: The 70 EX02C/SAO cards added in v0.5.0, including two CAMPAIGN cards and their corresponding EX02 original faces, remain included.

## Downloads

- [Windows installer](https://github.com/TohmaN233/ZZ-Project/releases/download/v0.5.1/ZZ-Project-v0.5.1-Windows-Setup.exe)
- [Linux portable bundle](https://github.com/TohmaN233/ZZ-Project/releases/download/v0.5.1/ZZ-Project-v0.5.1-Linux.tar.gz)
- [Source package](https://github.com/TohmaN233/ZZ-Project/releases/download/v0.5.1/ZZ-Project-v0.5.1-source.zip)
- [Self-hosted multiplayer server](https://github.com/TohmaN233/ZZ-Project/releases/download/v0.5.1/ZZ-Multiplayer-v0.5.1.tar.gz)
- [SHA256 checksums](https://github.com/TohmaN233/ZZ-Project/releases/download/v0.5.1/SHA256SUMS-PC02.txt)

Package sizes and SHA-256 values are recorded in [PUBLIC_RELEASE_MANIFEST.json](PUBLIC_RELEASE_MANIFEST.json).
See [INSTALL.md](INSTALL.md) for setup and [docs/ONLINE.md](docs/ONLINE.md) for online play and self-hosting.

## Previous release: v0.5.0 - EX02C/SAO and Duel Improvements

### 简体中文

- **EX02C/SAO 卡池**：加入 70 张卡（含 2 张 CAMPAIGN 卡）及其对应的 70 张 EX02 原版卡面，两种卡面可在各自卡包中检索。
- **规则与搜索**：完善 EX02C 的スイッチ、连锁与效果激活时点处理；修复卡包检索和 Force 搜索问题。
- **对战反馈**：改进战斗结果与相关状态反馈，并调整伤害、格挡和卡牌区域变化的前端视觉表现。

### 日本語

- **EX02C/SAO カードプール**：CAMPAIGN 2 枚を含む 70 枚と、対応する EX02 オリジナルカード面 70 枚を追加しました。それぞれのカードパックから検索できます。
- **ルールと検索**：EX02C のスイッチ、連鎖、効果発動タイミングの処理を改善し、カードパック検索と Force 検索の問題を修正しました。
- **対戦中のフィードバック**：戦闘結果と関連状態の表示を改善し、ダメージ、ブロック、カードのゾーン移動に合わせてフロントエンドの視覚表現を調整しました。

### English

- **EX02C/SAO card pool**: Adds all 70 cards, including two CAMPAIGN cards, plus their 70 corresponding EX02 original faces. Each face can be searched in its respective card pack.
- **Rules and search**: Improves EX02C switch, chain, and effect activation timing, and fixes card-pack catalog and Force search issues.
- **Duel feedback**: Improves battle result and state feedback, with frontend visuals tuned to damage, blocks, and card zone transitions.
