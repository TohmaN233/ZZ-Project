# v0.5.4 - Online Reconnect and Replays

[简体中文](README.md) | [日本語](README.ja.md) | [English](README.en.md)

## 简体中文

- **断线重连**：较大的对战消息分段传输，避免重连时因消息超过单帧上限而失败。
- **对战日志与回放**：对局传输近期日志，完整的本玩家可见记录自动保存在游戏目录的 `data/replays/`，可在“回放与训练”查看。断线期间缺失的数据会尝试补齐；未补齐时会标记为不完整。
- **联机版本**：双方客户端和服务器需要同步更新到 v0.5.4。服务器重启会结束正在进行的对局。

## 日本語

- **再接続**：大きな対戦メッセージを分割して送信し、単一フレームのサイズ制限による再接続失敗を防ぎます。
- **対戦ログとリプレイ**：通信には最近のログを使い、プレイヤーに見える記録をゲームディレクトリの `data/replays/` に保存します。「リプレイとトレーニング」で確認できます。切断中のデータは再取得を試み、揃わなければ未完了と表示します。
- **オンラインのバージョン**：両プレイヤーのクライアントとサーバーを v0.5.4 に更新してください。サーバーの再起動時は進行中の対戦が終了します。

## English

- **Reconnects**: Large match messages are sent in bounded fragments to avoid failures at the single-frame size limit.
- **Battle logs and replays**: Live messages carry recent logs. Player-visible recordings are saved in `data/replays/` inside the game directory and can be opened in Replay & Training. Missing data is recovered after reconnect when available; incomplete recordings are labeled.
- **Online versions**: Both clients and the server must be updated to v0.5.4. Restarting the server ends matches in progress.

## Downloads

- [Windows installer](https://github.com/TohmaN233/ZZ-Project/releases/download/v0.5.4/ZZ-Project-v0.5.4-Windows-Setup.exe)
- [Linux portable bundle](https://github.com/TohmaN233/ZZ-Project/releases/download/v0.5.4/ZZ-Project-v0.5.4-Linux.tar.gz)
- [Source package](https://github.com/TohmaN233/ZZ-Project/releases/download/v0.5.4/ZZ-Project-v0.5.4-source.zip)
- [Self-hosted multiplayer server](https://github.com/TohmaN233/ZZ-Project/releases/download/v0.5.4/ZZ-Multiplayer-v0.5.4.tar.gz)
- [SHA256 checksums](https://github.com/TohmaN233/ZZ-Project/releases/download/v0.5.4/SHA256SUMS-PC02.txt)

# v0.5.3 - Rules and Online Reliability

[简体中文](README.md) | [日本語](README.ja.md) | [English](README.en.md)

## 简体中文

- **圣之 Force**：保护符合条件的己方怪物，使其不会被通过加护赋予对手怪物的选择效果选中。
- **恩里科**：效果顺序调整为双方先弃牌，再抽牌。
- **断线重连**：联机断线后最多自动重连 5 次，并保留房间码。
- **对局日志**：当前对局中的战斗日志和结果页日志均支持分页查看。
- **联机版本**：新客户端和新服务器版本需要同步，双方客户端与服务器应使用相同版本。

## 日本語

- **聖の Force**：条件を満たす自分のミニオンを保護し、加護によって相手のミニオンに付与された選択効果の対象にならないようにします。
- **エンリコ**：効果の順序を変更し、両プレイヤーが先に捨ててからカードを引きます。
- **切断後の再接続**：最大 5 回まで自動再接続し、ルームコードを保持します。
- **対局ログ**：対戦中と結果画面のバトルログをページ分けして表示します。
- **オンライン対戦のバージョン**：新しいクライアントとサーバーは同じバージョンに揃えてください。

## English

- **Holy Force**: Protects eligible friendly minions from targeting effects granted to opposing minions by a Blessing.
- **Enrico**: Both players now discard first, then draw.
- **Reconnects**: Online play retries a disconnected session up to five times and preserves the room code.
- **Battle logs**: Logs are paginated during the current match and on the results page.
- **Online versions**: New client and server releases must be kept in sync; both clients and the server should use the same version.

## Downloads

- [Windows installer](https://github.com/TohmaN233/ZZ-Project/releases/download/v0.5.3/ZZ-Project-v0.5.3-Windows-Setup.exe)
- [Linux portable bundle](https://github.com/TohmaN233/ZZ-Project/releases/download/v0.5.3/ZZ-Project-v0.5.3-Linux.tar.gz)
- [Source package](https://github.com/TohmaN233/ZZ-Project/releases/download/v0.5.3/ZZ-Project-v0.5.3-source.zip)
- [Self-hosted multiplayer server](https://github.com/TohmaN233/ZZ-Project/releases/download/v0.5.3/ZZ-Multiplayer-v0.5.3.tar.gz)
- [SHA256 checksums](https://github.com/TohmaN233/ZZ-Project/releases/download/v0.5.3/SHA256SUMS-PC02.txt)

# v0.5.2 - Deck Storage and Diagnostics

[简体中文](README.md) | [日本語](README.ja.md) | [English](README.en.md)

## 简体中文

- **Windows 卡组保存**：卡组保存在安装目录的 `data/decks/`。首次启动时从旧的 `%APPDATA%\zenonzard-clone\game-data\decks\` 迁移卡组，保留原文件作为备份；冲突卡组不会被覆盖。
- **换手选牌**：选择卡牌时不再遮挡相邻卡牌。
- **启动诊断**：启动失败时显示诊断信息。
- **卸载保护**：为保护玩家数据，卸载时可能保留部分程序资源。
- **联机兼容性**：联机握手要求双方客户端和所连接服务器的 `applicationVersion` 完全相同；连接前请确认三方版本一致。此规则也适用于自建服务器。
- **此前功能**：继续包含 v0.5.1 的一键将当前编辑器重置为空白新卡组功能（不会删除已保存卡组），以及 v0.5.0 加入的 EX02C/SAO 70 张卡（含 2 张 CAMPAIGN 卡）和对应的 EX02 原版卡面。

## 日本語

- **Windows のデッキ保存**：インストール先の `data/decks/` に保存します。初回起動時に従来の `%APPDATA%\zenonzard-clone\game-data\decks\` から移行し、元ファイルをバックアップとして残します。競合するデッキは上書きしません。
- **初手交換時のカード選択**：カードを選択しても隣のカードが隠れなくなりました。
- **起動時の診断**：起動に失敗した場合、診断情報を表示します。
- **アンインストール時の保護**：データを保護するため、一部のプログラム関連ファイルが残る場合があります。
- **オンライン互換性**：双方のクライアントと接続先サーバーの `applicationVersion` が完全に一致する必要があります。接続前に三者のバージョンを確認してください。自設サーバーにも同じルールが適用されます。
- **既存機能**：v0.5.1 の空の新規デッキへのワンクリックリセット（保存済みデッキは削除されません）と、v0.5.0 で追加した EX02C/SAO の 70 枚（CAMPAIGN 2 枚を含む）および対応する EX02 オリジナルカード面も引き続き含まれます。

## English

- **Windows deck storage**: Decks are stored in `data/decks/` inside the installation directory. On first launch, decks are migrated from the legacy `%APPDATA%\zenonzard-clone\game-data\decks\` folder, with the original files kept as backups; conflicting decks are not overwritten.
- **Opening mulligan selection**: Selecting a card no longer obscures neighboring cards.
- **Startup diagnostics**: Diagnostic information is displayed when startup fails.
- **Uninstall protection**: Some program resources may remain after uninstall to protect player data.
- **Online compatibility**: Both clients and the connected server must report exactly the same `applicationVersion`. Check all three before connecting. The same rule applies to self-hosted servers.
- **Existing features**: The v0.5.1 one-click reset to a blank deck (without deleting saved decks) and the 70 EX02C/SAO cards added in v0.5.0, including two CAMPAIGN cards and their corresponding EX02 original faces, remain included.

## Downloads

- [Windows installer](https://github.com/TohmaN233/ZZ-Project/releases/download/v0.5.2/ZZ-Project-v0.5.2-Windows-Setup.exe)
- [Linux portable bundle](https://github.com/TohmaN233/ZZ-Project/releases/download/v0.5.2/ZZ-Project-v0.5.2-Linux.tar.gz)
- [Source package](https://github.com/TohmaN233/ZZ-Project/releases/download/v0.5.2/ZZ-Project-v0.5.2-source.zip)
- [Self-hosted multiplayer server](https://github.com/TohmaN233/ZZ-Project/releases/download/v0.5.2/ZZ-Multiplayer-v0.5.2.tar.gz)
- [SHA256 checksums](https://github.com/TohmaN233/ZZ-Project/releases/download/v0.5.2/SHA256SUMS-PC02.txt)

Package sizes and SHA-256 values are recorded in [PUBLIC_RELEASE_MANIFEST.json](PUBLIC_RELEASE_MANIFEST.json).
See [INSTALL.md](INSTALL.md) for setup and [docs/ONLINE.md](docs/ONLINE.md) for online play and self-hosting.

## Earlier release: v0.5.0 - EX02C/SAO and Duel Improvements

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
