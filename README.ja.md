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
- **Online Game**：LAN 対戦と個人サーバー経由のオンライン対戦に対応します。
- **3 言語 UI**：简体中文、日本語、English。
- **BGM 設定**：完全リソースパックには ZENONZARD のキャラクターソングが含まれます。
- **更新確認**：起動時に GitHub Releases を確認し、新しいバージョンがある場合は公開ページを開けます。
- **クロスプラットフォーム起動**：Windows は `.cmd`、Linux は `.sh`、macOS は `.command` を使用します。Linux / macOS は現在、実験的なソース起動対応です。

Story Mode は未実装です。長期目標は、Agent がプレイヤーと自動的に対話し、GAL 形式のフロントエンドを生成する仕組みです。SillyTavern 関連コミュニティのキャラクター、World Info、長期的な交流に関する知見も取り入れ、プレイヤーと自分の Codeman のための個別の ZZ 体験を目指します。

## AI の強さについて

本プロジェクトは実験モデルを強力な AI として宣伝しません。作者は統計学の学位を持っていますが、強化学習の授業を履修しておらず、研究分野も強化学習とは異なります。個人プロジェクトのため学習規模も限られており、現在の AI は ZENONZARD 正式運営時に使用された AI より明確に弱いものです。AI アドバイスも主に娯楽機能です。

AI 関連コードは Codex の支援を受け、[sbl1996/ygo-agent](https://github.com/sbl1996/ygo-agent) の公開手法と構成を参考にしています。詳細は [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) を参照してください。

## インストール

ソースコードと大型アセットは別々に配布しています。[完全リソースパック（ZZ-Assets-v1.zip）](https://drive.google.com/drive/folders/1R8NwBsR2QBvDHUwynZqLooZYI8TlX8TZ?usp=sharing)をダウンロードしてください。詳しい手順は [INSTALL.md](INSTALL.md) にあります。

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

# macOS
./launch-electron.command
```

## 現在の制限

カードプールは基本カードと PC01 を収録しています。今後、全カードプールの収録を目指して段階的に更新します。個人開発のため、すべてのカード組み合わせを十分にテストできておらず、小さなルールまたは UI の不具合が残っている可能性があります。

英語版カード画像は公式サイトの URL を直接使用しているため、一部でカードと画像が一致しない既知の問題があります。英語圏の協力者から画像や英訳テキストを提供していただければ修正できます。

## コントリビューション

オフライン向け ZZ AI の改善に協力してくださる強化学習経験者を歓迎します。カード資料、英語画像と翻訳、ルールテスト、Bug 報告も Issues または Discussions から受け付けています。

## 権利表記

本プロジェクトは非公式・非営利のファン開発および研究プロジェクトです。ZENONZARD の名称、キャラクター、カード画像、音楽、その他の関連素材に関する権利は各権利者に帰属します。本プロジェクトは BANDAI、STRAIGHT EDGE、SUNRISE の公認・提携プロジェクトではありません。
