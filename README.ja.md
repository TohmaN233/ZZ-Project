# ZENONZARD Offline Project

[简体中文](README.md) | [日本語](README.ja.md) | [English](README.en.md)

ローカル対戦を楽しみ、ルールを研究し、開発に参加したいプレイヤー向けの、非公式・非営利の ZENONZARD デスクトップ再現および AI 実験プロジェクトです。

[プロジェクト紹介サイト](https://tohman233.github.io/ZZ-Project/) · [インストールガイド](INSTALL.md) · [オンライン対戦](docs/ONLINE.md) · [日本語ルールブック](docs/rules/zz_rulebook_ja.md)

## システム要件

- Windows 10 または 11 ではインストーラーを使用できます。Linux ではポータブル版を使用できます。macOS のプレイヤーと開発者はソースから起動できます。
- ソースからの起動には Python 3.10+ と Node.js 20+ が必要です。
- 通常の対戦に専用 GPU は不要です。ローカル AI 学習には NVIDIA GPU、互換ドライバー、CUDA 対応版 PyTorch が必要です。

## インストール

v0.5.4 の Windows 版は、インストール先の `data/decks/` にデッキを保存します。初回起動時に従来の `%APPDATA%\zenonzard-clone\game-data\decks\` からデッキを移行し、元ファイルをバックアップとして残し、競合するデッキは上書きしません。聖の Force は条件を満たす自分のミニオンを保護し、加護によって相手のミニオンに付与された選択効果の対象にならないようにします。エンリコの効果では両プレイヤーが先に捨ててから引きます。オンライン対戦では切断後に最大 5 回自動再接続し、ルームコードを保持します。対戦中と結果画面のバトルログはページ分けして表示されます。大きな再接続データは分割して送信します。オンラインリプレイはゲームディレクトリの `data/replays/` に保存され、「リプレイとトレーニング」で確認できます。補完できていないリプレイには未完了と表示されます。両プレイヤーのクライアントとサーバーは同じバージョンが必要です。v0.5.4 クライアントには v0.5.4 サーバーを使用してください。以前のバージョンで追加した初手交換時の表示改善、起動診断、カードと Force の検索改善、および EX02C/SAO カードプールも引き続き含まれます。

[Windows インストーラー](https://github.com/TohmaN233/ZZ-Project/releases/download/v0.5.4/ZZ-Project-v0.5.4-Windows-Setup.exe) · [Linux ポータブル版](https://github.com/TohmaN233/ZZ-Project/releases/download/v0.5.4/ZZ-Project-v0.5.4-Linux.tar.gz) · [ソースパッケージ](https://github.com/TohmaN233/ZZ-Project/releases/download/v0.5.4/ZZ-Project-v0.5.4-source.zip) · [対戦サーバー](https://github.com/TohmaN233/ZZ-Project/releases/download/v0.5.4/ZZ-Multiplayer-v0.5.4.tar.gz) · [SHA256 チェックサム](https://github.com/TohmaN233/ZZ-Project/releases/download/v0.5.4/SHA256SUMS-PC02.txt)

Windows ではインストーラー、Linux ではポータブル版、macOS のプレイヤーと開発者はソースパッケージを使用してください。詳しい手順は[インストールガイド](INSTALL.md)を参照してください。

初回起動時に完全な `asserts/` ディレクトリがない場合、クライアントは [Google Drive のリソースフォルダー](https://drive.google.com/drive/folders/1R8NwBsR2QBvDHUwynZqLooZYI8TlX8TZ)から `asserts.7z` をダウンロードするか確認し、自動で検証・展開します。リソースアーカイブは 1.53 GB、展開後は 1.58 GB です。3.2 GB 以上の空き容量を確保してください。ダウンロードをキャンセルするとゲームは終了します。Program Files にインストールした場合、初回のリソース導入は管理者として起動してください。または書き込み可能なインストール先を選んでください。

ソースから起動する前に、プロジェクトのルートで依存関係をインストールしてください。

```powershell
python -m pip install -r requirements-runtime.txt
npm install
```

## 設定

画面言語の初期設定は簡体字中国語で、対戦相手 AI の初期難易度は High です。ロビーで難易度を変更できます。上部バーまたは設定ページでは、中国語、日本語、英語の切り替えと、BGM の選択・オフができます。Easy は Greedy 戦略、Medium と High はプロジェクトに含まれる実行時モデルを使用します。

## クイックスタート

Windows インストーラー版はスタートメニューまたはデスクトップのショートカットから起動します。Linux ポータブル版は初回起動時にユーザーのキャッシュディレクトリへランタイムを準備します。ソース版は OS に応じて次のコマンドで起動してください。

```powershell
# Windows のソース版
.\launch-electron.cmd
```

```bash
# Linux または macOS のソース版
./launch-electron.sh
```

## 現在の内容

- **対戦とデッキ**：人間 VS AI、神視点、AI VS AI に対応します。カードプールを検索し、デッキを編集・保存できます。編集中のデッキはワンクリックで空の新規デッキにリセットでき、カードと Force がクリアされ、名前と検索フィルターは初期状態に戻りますが、保存済みデッキは削除されません。
- **Codeman とローカル学習**：最近の対戦記憶をローカルに保存します。ソース版では GPU / CUDA 環境で実験的な学習を行えます。
- **Replay と AI アドバイス**：最近の対戦を振り返り、対戦中に Codeman から現在の行動への提案を確認できます。
- **オンライン対戦**：LAN と公開ルームに対応します。クライアントの接続先は既定で `wss://zz.tgy233.top/multiplayer` です。自分でサーバーを立てる場合は[オンライン対戦ガイド](docs/ONLINE.md)を参照してください。
- **カードプールと画面**：基本カード、EX01、PC01、PC01R、PC02、PC02R DIVINE の 106 枚に加え、EX02C/SAO の 70 枚と対応する EX02 オリジナルカード面を収録しています。画面は簡体字中国語、日本語、英語に対応します。
- **カード表示**：カード詳細で変身後の形態を確認できます。同名カードの再録分は合算され、デッキには最大 3 枚まで入れられます。

Story Mode は未実装です。長期的には、Agent がプレイヤーと自動で対話するゲームを設計し、GAL 形式のフロントエンドを実装することを目指しています。SillyTavern コミュニティのキャラクター、World Info、長期的な交流に関する経験も取り入れ、プレイヤーが自分の Codeman と共有できる ZZ 体験を作る計画です。

## AI の強さについて

本プロジェクトは実験モデルを強力な AI として宣伝しません。作者は統計学の学位を持っていますが、強化学習の授業を履修しておらず、研究分野も強化学習とは異なります。個人プロジェクトのため学習規模も限られており、現在の AI は ZENONZARD 正式運営時に使用された AI より明確に弱いものです。AI アドバイスも主に娯楽機能です。

コンピューター AI の学習カードプールは現在 PC01 のみです。PC01R、EX01、PC02、PC02R DIVINE、EX02、EX02C/SAO は現在の学習プロセスに含まれていないため、追加カードパックを AI が正しく理解するとは限りません。ルール上プレイできることと、AI がカードを学習していることは別です。

AI 関連コードは Codex の支援を受けています。また、[sbl1996/ygo-agent](https://github.com/sbl1996/ygo-agent) の公開手法と開発構成を参考にしています。詳しくは [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) を参照してください。

## プロジェクトへの参加

[コントリビューションガイド](CONTRIBUTING.md)を通じた参加を歓迎します。作業を始める前に、重複を避けるため Issue または Discussion で予定する内容を説明してください。

## 謝辞

50 枚以上の高解像度 playmat 画像を提供してくださった theFeri と、英語テキストを提供してくださった **Valkyrie** に感謝します。

## 権利表記

本プロジェクトは非公式・非営利のファン開発および研究プロジェクトです。ZENONZARD の名称、キャラクター、カード画像、音楽、その他の関連素材の権利は各権利者に帰属します。本プロジェクトは BANDAI、STRAIGHT EDGE、SUNRISE と提携・公認関係にありません。

リポジトリには、プロジェクトコードの正式なオープンソースライセンスが含まれていません。参照プロジェクトとサードパーティー依存関係の権利に関する説明は [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) を参照してください。この説明は各ライセンスの代わりにはなりません。
