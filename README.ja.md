# ZENONZARD Offline Project

[简体中文](README.md) | [日本語](README.ja.md) | [English](README.en.md)

非公式・非営利の ZENONZARD デスクトップ再現および AI 実験プロジェクトです。

[紹介サイト](https://tohman233.github.io/ZZ-Project/) · [インストール手順](INSTALL.md) · [オンライン対戦](docs/ONLINE.md) · [日本語ルールブック](docs/rules/zz_rulebook_ja.md)

## 現在の主な機能

- **Game Lobby**：両プレイヤーのデッキ、Codeman、プレイマット、先攻・後攻、AI 難易度を設定します。
- **デッキ編集**：カードを検索し、対戦で使用するデッキを作成・保存できます。
- **3 種類のオフライン対戦**：人間 VS AI、両方の手札を見て双方を操作する神視点、AI VS AI。
- **3 段階の AI**：Easy は Greedy CPU、Medium と High は強化学習モデルです。
- **Codeman Memory**：最近の対戦と Replay をローカルに保存します。専用 `.pt` がある Codeman は、そのモデルを優先して使用します。
- **AI アドバイス**：対戦中に自分の Codeman をクリックすると、現在の選択に対する AI の提案を確認できます。
- **Replay & Training**：最近の対戦を再生できます。GPU / CUDA 環境では実験的なローカル学習も利用できます。
- **Online Game**：LAN 対戦と個人サーバー経由のオンライン対戦に対応します。じゃんけんで先攻を決め、対戦後は同じ部屋でデッキを変更して再戦できます。
- **3 言語 UI**：简体中文、日本語、English。
- **BGM 設定**：完全リソースパックには ZENONZARD のキャラクターソングが含まれます。
- **更新確認**：起動時に GitHub Releases を確認し、新しいバージョンがある場合は公開ページを開けます。
- **クロスプラットフォーム起動**：Windows はインストーラー、Linux は portable `tar.gz` bundle、macOS と開発者はソース用 `.sh` を使用します。今回のリリースでは独立した `.command` launcher を削除しました。

Story Mode は未実装です。長期目標は、Agent がプレイヤーと自動的に対話し、GAL 形式のフロントエンドを生成する仕組みです。SillyTavern 関連コミュニティのキャラクター、World Info、長期的な交流に関する知見も取り入れ、プレイヤーと自分の Codeman のための個別の ZZ 体験を目指します。

## AI の強さについて

本プロジェクトは実験モデルを強力な AI として宣伝しません。作者は統計学の学位を持っていますが、強化学習の授業を履修しておらず、研究分野も強化学習とは異なります。個人プロジェクトのため学習規模も限られており、現在の AI は ZENONZARD 正式運営時に使用された AI より明確に弱いものです。AI アドバイスも主に娯楽機能です。

重要な注意：コンピューター AI の学習データと学習カードプールは現在 PC01 のみです。PC01R、EX01、PC02 はこの学習に含まれていないため、追加カードパックを AI が正しく理解することは期待しないでください。PC02 のルール実装と AI の強さは別のものです。

AI 関連コードは Codex の支援を受け、[sbl1996/ygo-agent](https://github.com/sbl1996/ygo-agent) の公開手法と構成を参考にしています。詳細は [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) を参照してください。

## インストール

Windows のプレイヤーは [ZZ-Project-v0.3.0-Windows-Setup.exe](https://github.com/TohmaN233/ZZ-Project/releases/download/v0.3.0/ZZ-Project-v0.3.0-Windows-Setup.exe) をダウンロードして実行してください。インストーラーには遊べるデスクトップクライアント、凍結済み Python server、ルールコード、既定モデルが含まれ、Python と Node.js は不要です。大型アセットは別配布のため、[Google Drive のアセットフォルダ](https://drive.google.com/drive/folders/1R8NwBsR2QBvDHUwynZqLooZYI8TlX8TZ?usp=sharing)から主アセットの 2 つの ZIP volume、`ZZ-Assets-PC02-v1.zip.001` と `ZZ-Assets-PC02-v1.zip.002` を取得してください。`.001` を 7-Zip で開き、得られた `asserts/` をインストール先の `ZZ-Project.exe` と同じ階層へ配置します。英語カード画像が必要な場合は別ファイル `ZZ-Assets-PC02-English-v1.zip` も同じ `asserts/` に展開してください。詳しい手順は [INSTALL.md](INSTALL.md) にあります。

Linux のプレイヤーは [ZZ-Project-v0.3.0-Linux.tar.gz](https://github.com/TohmaN233/ZZ-Project/releases/download/v0.3.0/ZZ-Project-v0.3.0-Linux.tar.gz) を展開して `./launch-electron.sh` を実行してください。初回起動時にユーザーキャッシュへランタイムを準備します。macOS のプレイヤーと開発者は [ZZ-Project-v0.3.0-source.zip](https://github.com/TohmaN233/ZZ-Project/releases/download/v0.3.0/ZZ-Project-v0.3.0-source.zip) を使用し、下記のソースセットアップを行ってください。

```powershell
python -m pip install -r requirements-runtime.txt
npm install
```

リソースパック内の `asserts/` をリポジトリ直下に配置し、各 OS のランチャーを実行します。

```powershell
# Windows
.\launch-electron.cmd
```

```bash
# Linux
./launch-electron.sh

# macOS（ソース起動）
./launch-electron.sh
```

## 現在の制限

カードプールは基本カード、EX01、PC01、PC01R、PC02 を収録しています。個人開発のため、すべてのカード組み合わせを十分にテストできておらず、小さなルールまたは UI の不具合が残っている可能性があります。

英語カード画像と英語テキストは独立アセットパックで配布しています。未収録の画像は公式サイトの URL にフォールバックするため、一部でカードと画像が一致しない可能性があります。

## 謝辞

50 枚以上の高解像度 playmat 画像を提供してくださった theFeri と、英語テキストを提供してくださった **Valkyrie** に特別な感謝を表します。

## コントリビューション

オフライン向け ZZ AI の改善に協力してくださる強化学習経験者を歓迎します。カード資料、英語画像と翻訳、ルールテスト、Bug 報告も Issues または Discussions から受け付けています。

## 権利表記

本プロジェクトは非公式・非営利のファン開発および研究プロジェクトです。ZENONZARD の名称、キャラクター、カード画像、音楽、その他の関連素材に関する権利は各権利者に帰属します。本プロジェクトは BANDAI、STRAIGHT EDGE、SUNRISE の公認・提携プロジェクトではありません。
