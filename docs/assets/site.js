"use strict";

const RELEASE_CONFIG = {
  projectUrl: "https://github.com/TohmaN233/ZZ-Project",
  programUrl: "https://github.com/TohmaN233/ZZ-Project/releases/download/v0.5.4/ZZ-Project-v0.5.4-Windows-Setup.exe",
  linuxBundleUrl: "https://github.com/TohmaN233/ZZ-Project/releases/download/v0.5.4/ZZ-Project-v0.5.4-Linux.tar.gz",
  sourceUrl: "https://github.com/TohmaN233/ZZ-Project/releases/download/v0.5.4/ZZ-Project-v0.5.4-source.zip",
  serverUrl: "https://github.com/TohmaN233/ZZ-Project/releases/download/v0.5.4/ZZ-Multiplayer-v0.5.4.tar.gz",
  checksumsUrl: "https://github.com/TohmaN233/ZZ-Project/releases/download/v0.5.4/SHA256SUMS-PC02.txt",
  assetPackUrl: "https://drive.google.com/drive/folders/1R8NwBsR2QBvDHUwynZqLooZYI8TlX8TZ?usp=sharing",
};

const copy = {
  zh: {
    skip: "跳到正文",
    navFeatures: "功能", navAi: "AI 与 Codeman", navInstall: "安装", navRoadmap: "未来计划",
    heroEyebrow: "非官方 · 单机优先 · 持续开发",
    heroCopy: "在现代桌面环境中重新体验 ZZ：构筑卡组、与三档 AI 对战、回看牌局，也可以通过局域网或个人服务器联机。",
    heroInstall: "查看安装方法", heroExplore: "了解当前版本", heroPlatforms: "Windows · Linux/macOS 使用 .sh", heroLanguage: "中文 / 日本語 / English",
    statusOneTitle: "当前卡池", statusOneBody: "基础卡 + EX01 + PC01 + PC01R + PC02 + PC02R DIVINE（106 张）+ EX02C/SAO 与 EX02 对应卡面（70 组）", statusTwoTitle: "对战方式", statusTwoBody: "单机 / 局域网 / 在线",
    statusThreeTitle: "AI 档位", statusThreeBody: "Greedy + 两档 RL", statusFourTitle: "版本状态", statusFourBody: "v0.5.4 · 当前版本",
    featuresEyebrow: "Game Lobby", featuresTitle: "组卡到开局皆在游戏大厅",
    featuresLead: "选择双方卡组、Codeman、卡垫与 AI 难度，然后进入你想要的对战方式。卡池现包括 EX02C/SAO 的 70 张卡及对应 EX02 原版卡面；也可私下预览卡牌变身后的形态。",
    modeHumanTab: "人 VS AI", modeGodTab: "神视点", modeHumanTitle: "普通人机对战",
    modeHumanBody: "你控制一方，另一方由所选难度的 AI 与 Codeman 配置驱动。这是最接近普通游玩的一种模式。",
    modeGodTitle: "神视点：左手打右手", modeGodBody: "双方手牌全部可见，而且你能操作两边。适合验证规则、复盘选择，或单纯自己与自己对战。",
    modeAiTitle: "AI 自动对战", modeAiBody: "两边都交给 AI。你可以观察策略差异、快速产生对局记录，或用它检查一套卡组的基本运作。",
    featureDeck: "创建、保存与编辑卡组，一键清空卡牌和 Force，并重置名称及筛选且保留已保存卡组", featureProfile: "分别选择双方 Codeman 与卡垫", featureSides: "指定先后手与玩家所在侧",
    featureBattleTitle: "卡牌对战", featureBattleBody: "处理核心对战流程，并修正效果目标筛选、伤害与 Force 治疗、基地持有者替换和 Bless 返回；弃牌与抽牌会显示动画和增益详情。",
    featureDeckTitle: "卡组制作", featureDeckBody: "搜索卡池、检查张数与 Force 配置；可一键重置当前编辑器为空白新卡组，清空卡牌和 Force，并重置名称及筛选而不删除已保存卡组。同名重印卡合并计算，套牌最多 3 张。",
    featureReplayTitle: "Replay", featureReplayBody: "保存最近对局并按事件回看；训练结果可以关联回放，寻找输局中的其他路线。",
    featureOnlineTitle: "Online", featureOnlineBody: "支持同一局域网直连，也支持通过项目维护者的个人服务器建立房间。",
    aiEyebrow: "AI & Codeman", aiTitle: "三档离线AI对手",
    aiLead: "Easy 是 Greedy CPU；Medium 与 High 使用强化学习训练出的策略。训练规模有限，因此现阶段的定位是可玩的研究与娱乐功能，而不是高水平竞技对手。",
    difficultyLabel: "当前说明", easyTitle: "Greedy CPU", easyBody: "不加载训练模型，依据合法行动与人工启发式权重选择当前看来最有利的动作，运行快，也最容易理解。",
    mediumTitle: "公开 RL 基线", mediumBody: "使用随程序提供的线性强化学习模型，对合法行动进行评分。训练卡池仅覆盖 PC01，面对新卡可能出现明显失误。",
    highTitle: "公开 Deep RL 模型", highBody: "使用随程序提供的深度强化学习模型，训练卡池仅覆盖 PC01。此版本没有新增 AI 训练，不能保证对新卡的判断质量。",
    truthTitle: "关于 AI 水平的诚实说明",
    truthBody: "作者拥有统计学学位，但没有修读强化学习课程，研究方向也与此无关；模型训练规模同样不大。电脑 AI 的训练数据和卡池目前只覆盖 PC01，PC01R、EX01、PC02、PC02R DIVINE、EX02、EX02C/SAO 没有进入训练流程。当前 AI 与 ZENONZARD 正式运营时期万代使用的 AI 仍有明显差距。相关实现由 Codex 协助编写，并参考了 ygo-agent 的公开方法与工程结构。",
    codemanTitle: "每个 Codeman 都有自己的近期对战记忆",
    codemanBody: "对局结束后，系统会在本机保存该 Codeman 最近的一部分战斗记录与回放。若你为某个 Codeman 进行了专门训练，并生成了它自己的 .pt 模型，选择这个对手时会优先加载该专属模型；没有专属模型时则使用公开默认模型。",
    flowBattle: "完成对局", flowMemory: "近期记忆", flowTrain: "可选训练",
    advisorBody: "对战时点击自己的 Codeman，可以让 AI 对当前选择给出建议。由于模型能力有限，这更像一个可观察的娱乐助手，而不是可靠教练。",
    screensEyebrow: "Actual UI", screensTitle: "完整 ZZ 体验：包含 106 张 PC02R DIVINE 卡牌与 70 组 EX02C/SAO—EX02 对应卡面", screenBattleLabel: "实机对战界面",
    screenBattleTitle: "双方区域、手牌、Force、阶段与提示都在同一张桌面上", screenHome: "首页与功能入口", screenLobby: "卡组、模式与 Codeman 配置",
    replayTitle: "把自己的牌局变成可回看的训练材料",
    replayBody: "如果本机具备 NVIDIA GPU 与可用的 CUDA 环境，可以基于自己的对战记录运行本地训练。它仍是实验性的娱乐功能：一次输局也许能在 Replay 中发现另一个选择，但系统不会保证找到必胜解。",
    replayLink: "查看训练环境说明 →", onlineTitle: "局域网直连，或通过个人服务器联网",
    onlineBody: "联机握手要求双方客户端与所连接服务器报告的 applicationVersion 完全一致；连接前请确认三方版本一致。此规则也适用于自建服务器。Online Game 支持同一局域网内开房，也支持项目维护者的个人服务器。服务器位于加拿大，其他地区的稳定性未经充分验证；中国大陆通常需要代理才能稳定连接。",
    onlineLink: "查看联机说明 →", onlineDemo: "联机版本演示", contentEyebrow: "CONTENT STATUS", contentTitle: "当前内容边界",
    poolTitle: "卡池", poolBody: "当前包含基本卡、EX01、PC01、PC01R、PC02 与 PC02R DIVINE 的 106 张卡，以及 EX02C/SAO 的 70 张卡与对应 EX02 原版卡面。", testingTitle: "测试", testingBody: "个人项目无法覆盖足够多的组合测试，当前版本可能仍有小型规则或界面问题。",
    englishTitle: "英文版", englishBody: "asserts.7z 资源包包含英文卡图；未覆盖的图仍可能回退到官网 URL。",
    musicTitle: "BGM", musicBody: "顶部栏或基础设置中可选择对战 BGM；完整资源包包含 ZZ 各角色歌曲。",
    thanksTitle: "致谢", thanksBody: "感谢 theFeri 提供 50+ 张高清 playmat 图，以及 Valkyrie 提供英文文本。",
    installEyebrow: "INSTALLATION", installTitle: "下载 v0.5.4；首次启动可自动获取资源",
    installLead: "v0.5.4 的 Windows 版将卡组保存在安装目录 data/decks/；首次启动从旧的 %APPDATA%\\zenonzard-clone\\game-data\\decks\\ 迁移卡组，保留原文件备份且不覆盖冲突卡组。圣之 Force 会保护符合条件的己方怪物，使其不会被通过加护赋予对手怪物的选择效果选中；恩里科效果先令双方弃牌、再抽牌。联机断线后最多自动重连 5 次并保留房间码；当前对局和结果页的战斗日志支持分页。重连时较大的消息会分段传输；联机回放保存在游戏目录 data/replays/，未补齐时标记为不完整。联机双方客户端与服务器必须使用相同版本；v0.5.4 客户端需要连接 v0.5.4 服务器。Windows 安装包和 Linux 便携包包含可玩的游戏与默认模型。缺少完整 asserts/ 时，桌面客户端会询问是否下载并安装包含英文卡图的 asserts.7z。",
    installStep1Title: "选择平台发行包", installStep1Body: "Windows 使用安装包，Linux 使用便携包；macOS 和开发者使用源码包。自建服务器使用独立联机服务器包。",
    installStep2Title: "首次启动获取资源", installStep2Body: "若缺少 asserts/，客户端会询问是否下载 asserts.7z，校验 CRC 后解压到程序目录；包为 1.53 GB，展开后 1.58 GB，请预留 3.2 GB。包含英文卡图；取消后不启动，失败可重试。",
    installStep3Title: "源码版本安装依赖", installStep3Body: "Windows 安装包不需要 Python 或 Node.js；源码启动才需要 Python 3.10+、Node.js 20+ 与 npm install。",
    installStep4Title: "启动客户端", installStep4Body: "Windows 安装包从开始菜单或桌面快捷方式启动；Linux bundle 解压后运行 ./launch-electron.sh；源码版本使用 .cmd、.sh 或 npm run electron:dev。",
    requirementsTitle: "运行要求", reqOs: "系统", reqOsBody: "Windows 10/11 安装包；Linux portable bundle；macOS 源码启动（实验支持）", reqPython: "Windows 安装包无需；Linux bundle 首次启动自备 runtime；源码需要 3.10+", reqNode: "Windows 安装包无需；Linux bundle 首次启动自备 runtime；源码需要 20+", reqGpu: "显卡", reqGpuBody: "游玩不要求；本地训练需要 NVIDIA GPU / CUDA",
    downloadCode: "下载 Windows v0.5.4", downloadLinux: "下载 Linux v0.5.4", downloadAssets: "打开 asserts.7z 资源文件夹（含英文卡图）", hashNote: "asserts.7z 为 1,534,680,950 bytes，展开后为 1,577,092,255 bytes，需预留至少 3.2 GB。客户端捆绑 7-Zip 并校验 CRC；程序发行包的 SHA256 见校验清单。",
    storyTitle: "下一阶段：每位玩家自己的故事与前端",
    storyBody: "Story Mode 目前尚未开发。长期目标是设计由 Agent 自动与用户交互的游戏，对应实现 GAL 前端，并吸收 SillyTavern 相关社群在角色、世界书与长期互动方面积累的经验，构建个人专属的、与自己的 Codeman 一起经历的 ZZ 体验。",
    storyCaveat: "这是未来目标，不代表第一版已经提供生成式剧情功能。",
    contributeEyebrow: "CONTRIBUTE", contributeTitle: "欢迎懂强化学习、卡牌资料或本地化的朋友加入",
    contributeBody: "尤其希望有强化学习经验的贡献者一起研究：是否能训练出真正适合离线运行的 ZZ AI。英文卡图、卡牌译文、规则测试与 Bug 报告同样重要。",
    starGithubShort: "Star", starGithub: "在 GitHub 点个 Star", starNote: "Star 是最省事的支持方式，也是继续更新的动力。",
    reportIssue: "提交 Issue", joinDiscussion: "参与讨论", footerUnofficial: "非官方、非商业的粉丝开发与研究项目。",
    footerRights: "ZENONZARD 名称、角色、卡图、音乐与相关素材的权利归各自权利方所有。本项目与 BANDAI / STRAIGHT EDGE / SUNRISE 无隶属或授权关系。",
    backTop: "返回顶部 ↑",
    downloadSource: "下载源码",
    downloadServer: "下载联机服务器",
    downloadChecksums: "SHA256 校验清单",
  },
  ja: {
    skip: "本文へ移動",
    navFeatures: "機能", navAi: "AI と Codeman", navInstall: "導入", navRoadmap: "今後の計画",
    heroEyebrow: "非公式 · オフライン中心 · 開発継続中",
    heroCopy: "現代のデスクトップ環境で ZZ をもう一度。デッキ構築、3 段階の AI、リプレイに加え、LAN または個人サーバー経由の対戦にも対応します。",
    heroInstall: "導入方法を見る", heroExplore: "現行版を知る", heroPlatforms: "Windows · Linux/macOS は .sh", heroLanguage: "中文 / 日本語 / English",
    statusOneTitle: "現在のカードプール", statusOneBody: "ベーシック + EX01 + PC01 + PC01R + PC02 + PC02R DIVINE（106 枚）+ EX02C/SAO と EX02 の対応カード面（70 組）", statusTwoTitle: "対戦方法", statusTwoBody: "オフライン / LAN / オンライン",
    statusThreeTitle: "AI レベル", statusThreeBody: "Greedy + RL 2段階", statusFourTitle: "リリース", statusFourBody: "v0.5.4 · 現行版",
    featuresEyebrow: "Game Lobby", featuresTitle: "デッキ構築から対戦開始まで、すべてゲームロビーで",
    featuresLead: "両者のデッキ、Codeman、プレイマット、AI 難度を選び、好きな対戦形式へ進みます。カードプールには EX02C/SAO の 70 枚と対応する EX02 オリジナルカード面を収録し、変身後のカードも非公開でプレビューできます。",
    modeHumanTab: "人 VS AI", modeGodTab: "神視点", modeHumanTitle: "通常の対 AI 戦",
    modeHumanBody: "片側をプレイヤーが操作し、もう片側を選択した難度と Codeman 設定の AI が担当します。最も一般的な遊び方です。",
    modeGodTitle: "神視点：一人二役", modeGodBody: "両者の手札を公開し、両側を操作できます。ルール確認、選択の検証、自分同士の対戦に向いたモードです。",
    modeAiTitle: "AI 自動対戦", modeAiBody: "両側を AI に任せます。方策の違いを観察し、対戦履歴を生成し、デッキの基本動作を確認できます。",
    featureDeck: "デッキの作成・保存・編集。カードと Force を空にし、名前と検索条件をリセットしても保存済みデッキは保持", featureProfile: "両者の Codeman とプレイマットを個別に選択", featureSides: "先後攻とプレイヤー側を指定",
    featureBattleTitle: "カードバトル", featureBattleBody: "主要な対戦フローに加えて、効果対象の絞り込み、ダメージと Force の回復、基地所有者の変更、Bless による戻しを修正しました。捨て札・ドローのアニメーションと強化内容も表示します。",
    featureDeckTitle: "デッキ構築", featureDeckBody: "カード検索、枚数・フォース構成を確認できます。編集中のデッキをワンクリックで空の新規デッキにリセットでき、カードと Force がクリアされ、名前と検索条件は初期状態に戻りますが、保存済みデッキは削除されません。同じカードの再録分は合算し、デッキに最大 3 枚までです。",
    featureReplayTitle: "Replay", featureReplayBody: "直近の対戦をイベント単位で再生。学習結果と紐づけ、敗戦時の別ルートを探せます。",
    featureOnlineTitle: "Online", featureOnlineBody: "同一 LAN での直接接続と、プロジェクト管理者の個人サーバーを使ったルーム対戦に対応します。",
    aiEyebrow: "AI & Codeman", aiTitle: "3 段階のオフライン AI 対戦相手",
    aiLead: "Easy は Greedy CPU、Medium と High は強化学習方策です。学習規模が小さいため、現段階では競技用の強敵ではなく、遊べる研究・娯楽機能という位置づけです。",
    difficultyLabel: "現在の説明", easyTitle: "Greedy CPU", easyBody: "学習モデルを読み込まず、合法手と手作業のヒューリスティック重みに基づいて、その場で有利に見える行動を選びます。高速で理解しやすい方式です。",
    mediumTitle: "公開 RL ベースライン", mediumBody: "同梱の線形強化学習モデルで合法手を評価します。学習対象は PC01 のみで、新しいカードでは明確なミスが起こる場合があります。",
    highTitle: "公開 Deep RL モデル", highBody: "同梱の深層強化学習モデルを使用します。学習対象は PC01 のみで、この版で AI の追加学習は行っていません。新カードへの判断の質は保証できません。",
    truthTitle: "AI の強さに関する率直な説明",
    truthBody: "作者は統計学の学位を持ちますが、強化学習の授業を履修した経験はなく、研究分野も別領域です。コンピューター AI の学習データとカードプールは現在 PC01 のみで、PC01R、EX01、PC02、PC02R DIVINE、EX02、EX02C/SAO は学習に含まれていません。学習規模も小さく、正式サービス時にバンダイが使用していた AI とは大きな差があります。実装は Codex の支援を受け、ygo-agent の公開手法と構成を参考にしています。",
    codemanTitle: "各 Codeman は直近の対戦記憶を持ちます",
    codemanBody: "対戦終了後、その Codeman の最近の戦績とリプレイの一部をローカルに保存します。専用学習で固有の .pt モデルを生成した場合、対戦相手として選ぶとそのモデルを優先します。専用モデルがない場合は公開既定モデルを使用します。",
    flowBattle: "対戦終了", flowMemory: "最近の記憶", flowTrain: "任意の学習",
    advisorBody: "対戦中に自分の Codeman をクリックすると、現在の選択に対する AI の提案を確認できます。モデル能力が限られるため、信頼できるコーチではなく、観察できる娯楽アシスタントです。",
    screensEyebrow: "Actual UI", screensTitle: "ZZ を一通り体験：PC02R DIVINE の 106 枚と EX02C/SAO—EX02 の対応カード面 70 組を収録", screenBattleLabel: "実際の対戦画面",
    screenBattleTitle: "両者のゾーン、手札、フォース、フェーズ、操作案内を一つの盤面に", screenHome: "ホームと機能入口", screenLobby: "デッキ、モード、Codeman 設定",
    replayTitle: "自分の対戦を、見返せる学習素材に",
    replayBody: "NVIDIA GPU と利用可能な CUDA 環境があれば、自分の対戦記録を使ったローカル学習を実行できます。これは実験的な娯楽機能で、Replay から別の選択が見つかる場合はありますが、勝ち筋を保証しません。",
    replayLink: "学習環境の説明を見る →", onlineTitle: "LAN 直結、または個人サーバー経由で対戦",
    onlineBody: "オンライン対戦では両プレイヤーのクライアントと接続先サーバーが報告する applicationVersion が完全に一致している必要があります。接続前に三者のバージョンを確認してください。自設サーバーにも同じルールが適用されます。Online Game は同一 LAN でのルーム作成と、管理者の個人サーバーに対応します。サーバーはカナダにあり、他地域での安定性は十分に検証されていません。中国本土からは通常プロキシが必要です。",
    onlineLink: "オンライン対戦の説明を見る →", onlineDemo: "オンライン版デモ", contentEyebrow: "CONTENT STATUS", contentTitle: "現在の収録範囲",
    poolTitle: "カード", poolBody: "ベーシックカード、EX01、PC01、PC01R、PC02 と PC02R DIVINE の 106 枚に加え、EX02C/SAO の 70 枚と対応する EX02 オリジナルカード面を収録しています。", testingTitle: "テスト", testingBody: "個人開発のため、十分な組み合わせテストはできておらず、小さなルール・表示不具合が残る可能性があります。",
    englishTitle: "英語版", englishBody: "asserts.7z のリソースパックには英語カード画像が含まれます。未収録の画像は公式 URL にフォールバックする場合があります。",
    musicTitle: "BGM", musicBody: "トップバーまたは基本設定から対戦 BGM を選択できます。完全版アセットパックには ZZ のキャラクターソングが含まれます。",
    thanksTitle: "謝辞", thanksBody: "50 枚以上の高解像度 playmat 画像を提供してくださった theFeri と、英語テキストを提供してくださった Valkyrie に感謝します。",
    installEyebrow: "INSTALLATION", installTitle: "v0.5.4 をダウンロード；初回起動でアセットを取得",
    installLead: "v0.5.4 の Windows 版はインストール先の data/decks/ にデッキを保存します。初回起動時に従来の %APPDATA%\\zenonzard-clone\\game-data\\decks\\ からデッキを移行し、元ファイルをバックアップとして残し、競合するデッキは上書きしません。聖の Force は条件を満たす自分のミニオンを保護し、加護によって相手のミニオンに付与された選択効果の対象にならないようにします。エンリコの効果では両プレイヤーが先に捨ててから引きます。切断後は最大 5 回まで自動再接続し、ルームコードを保持します。対戦中と結果画面のバトルログはページ分けして表示されます。大きな再接続データは分割して送信します。オンラインリプレイはゲームディレクトリの data/replays/ に保存され、補完できていない場合は未完了と表示されます。両プレイヤーのクライアントとサーバーは同じバージョンが必要です。v0.5.4 クライアントには v0.5.4 サーバーを使用してください。Windows インストーラーと Linux ポータブル版にはゲームと既定モデルが含まれます。完全な asserts/ がない場合、英語カード画像を含む asserts.7z のダウンロードと展開を確認します。",
    installStep1Title: "プラットフォームを選択", installStep1Body: "Windows はインストーラー、Linux はポータブル版、macOS と開発者はソース版を使用します。自設サーバーには専用パッケージを使用します。",
    installStep2Title: "初回起動でアセットを取得", installStep2Body: "asserts/ がない場合、ダウンロードを確認して CRC 検証後に展開します。圧縮時 1.53 GB、展開後 1.58 GB、3.2 GB 以上の空き容量が必要です。英語カード画像も含みます。キャンセルすると起動せず、失敗時は再試行できます。",
    installStep3Title: "ソース版だけ依存関係を導入", installStep3Body: "Windows インストーラーには Python と Node.js は不要です。ソース起動では Python 3.10+、Node.js 20+、npm install が必要です。",
    installStep4Title: "クライアントを起動", installStep4Body: "インストーラー版はスタートメニューまたはデスクトップショートカットから起動します。Linux bundle は展開後に ./launch-electron.sh、ソース版は .cmd、.sh、または npm run electron:dev を使用します。",
    requirementsTitle: "動作要件", reqOs: "OS", reqOsBody: "Windows 10/11 インストーラー。Linux portable bundle。macOS はソース起動の実験対応", reqPython: "Windows インストーラー不要。Linux bundle は初回起動時に runtime を準備。ソース版は 3.10+", reqNode: "Windows インストーラー不要。Linux bundle は初回起動時に runtime を準備。ソース版は 20+", reqGpu: "GPU", reqGpuBody: "通常プレイは不要。ローカル学習には NVIDIA GPU / CUDA が必要",
    downloadCode: "Windows v0.5.4 をダウンロード", downloadLinux: "Linux v0.5.4 をダウンロード", downloadAssets: "asserts.7z のリソースフォルダを開く（英語カード画像含む）", hashNote: "asserts.7z は 1,534,680,950 bytes、展開後は 1,577,092,255 bytes です。3.2 GB 以上の空き容量が必要です。同梱の 7-Zip で CRC を検証します。プログラムの SHA256 はチェックサム一覧をご覧ください。",
    storyTitle: "次の段階：プレイヤーごとの物語とフロントエンド",
    storyBody: "Story Mode は未実装です。長期目標は、Agent がユーザーと自動的に交流するゲームと、それに対応する GAL 風フロントエンドを実現することです。SillyTavern 関連コミュニティが蓄積してきたキャラクター、世界設定、長期的な交流の知見を取り入れ、自分の Codeman と共に過ごす、プレイヤー個人専用の ZZ 体験を構築します。",
    storyCaveat: "これは将来目標であり、初回版に生成ストーリー機能が含まれるという意味ではありません。",
    contributeEyebrow: "CONTRIBUTE", contributeTitle: "強化学習、カード資料、ローカライズの協力者を歓迎します",
    contributeBody: "特に、オフラインで動く本格的な ZZ AI を学習できるか、強化学習経験者と一緒に研究したいと考えています。英語カード画像、翻訳、ルールテスト、バグ報告も重要です。",
    starGithubShort: "Star", starGithub: "GitHub で Star する", starNote: "Star はいちばん手軽な応援です。今後の更新の励みになります。",
    reportIssue: "Issue を送る", joinDiscussion: "議論に参加", footerUnofficial: "非公式・非商用のファン開発および研究プロジェクトです。",
    footerRights: "ZENONZARD の名称、キャラクター、カード画像、音楽、関連素材の権利は各権利者に帰属します。本プロジェクトは BANDAI / STRAIGHT EDGE / SUNRISE の公式・認可プロジェクトではありません。",
    backTop: "ページ上部へ ↑",
    downloadSource: "ソースをダウンロード",
    downloadServer: "対戦サーバーをダウンロード",
    downloadChecksums: "SHA256 チェックサム",
  },
  en: {
    skip: "Skip to content",
    navFeatures: "Features", navAi: "AI & Codeman", navInstall: "Install", navRoadmap: "Roadmap",
    heroEyebrow: "Unofficial · Offline first · In development",
    heroCopy: "Play ZZ on a modern desktop: build decks, face three AI tiers, review matches, or connect over LAN and a community-run personal server.",
    heroInstall: "Installation guide", heroExplore: "Explore this release", heroPlatforms: "Windows · Linux/macOS via .sh", heroLanguage: "Chinese / Japanese / English",
    statusOneTitle: "Card pool", statusOneBody: "Basic + EX01 + PC01 + PC01R + PC02 + PC02R DIVINE (106 cards); 70 paired EX02C/SAO and EX02 faces", statusTwoTitle: "Play", statusTwoBody: "Offline / LAN / Online",
    statusThreeTitle: "AI tiers", statusThreeBody: "Greedy + two RL tiers", statusFourTitle: "Version", statusFourBody: "v0.5.4 · Current",
    featuresEyebrow: "Game Lobby", featuresTitle: "Build your deck and start the match in the Game Lobby",
    featuresLead: "Choose both decks, Codemen, playmats, and AI difficulty before entering a battle mode. The card pool includes 70 EX02C/SAO cards and their corresponding EX02 original faces, and transformed forms can be previewed privately.",
    modeHumanTab: "Human VS AI", modeGodTab: "God view", modeHumanTitle: "Standard human vs AI",
    modeHumanBody: "You control one side. The other is driven by the selected AI tier and Codeman configuration. This is the closest mode to regular play.",
    modeGodTitle: "God view: play both sides", modeGodBody: "Both hands are visible and you control both players. It is useful for checking rules, reviewing decisions, or simply playing against yourself.",
    modeAiTitle: "AI autoplay", modeAiBody: "AI controls both sides. Observe policy differences, generate match records, or check whether a deck can execute its basic plan.",
    featureDeck: "Create, save, and edit decks; clear cards and Forces and reset the name and filters in one click while keeping saved decks", featureProfile: "Choose each side's Codeman and playmat", featureSides: "Set first player and the human side",
    featureBattleTitle: "Card battle", featureBattleBody: "Handles the core battle flow and corrects effect-target filtering, damage and Force healing, base-owner replacement, and Bless returns. Discard/draw animations and buff details are shown.",
    featureDeckTitle: "Deck builder", featureDeckBody: "Search the pool and validate card count and Force setup. Reset the current editor to a blank new deck with one click, clearing cards and Forces and resetting the name and filters without deleting saved decks. Reprints share one combined limit of three copies per card.",
    featureReplayTitle: "Replay", featureReplayBody: "Keep recent matches and review them event by event. Training outputs can link back to replays to explore alternatives in a loss.",
    featureOnlineTitle: "Online", featureOnlineBody: "Connect directly on the same LAN or create a room through the maintainer's personal server.",
    aiEyebrow: "AI & Codeman", aiTitle: "Three tiers of offline AI opponents",
    aiLead: "Easy is a Greedy CPU. Medium and High use reinforcement-learning policies. Training is small-scale, so these are playable research and entertainment features rather than competitive opponents.",
    difficultyLabel: "Current behavior", easyTitle: "Greedy CPU", easyBody: "Loads no trained model. It scores legal actions with hand-authored heuristics and picks the option that looks best immediately. It is fast and the easiest tier to understand.",
    mediumTitle: "Public RL baseline", mediumBody: "Uses the bundled linear reinforcement-learning model to score legal actions. Training covers PC01 only, so it may make obvious mistakes with newer cards.",
    highTitle: "Public Deep RL model", highBody: "Uses the bundled deep reinforcement-learning model, trained on PC01 only. This version adds no AI training and does not guarantee sound decisions with newer cards.",
    truthTitle: "An honest note about AI strength",
    truthBody: "The author has a statistics degree, but has not taken reinforcement-learning courses and does not research this field. The computer AI was trained only on PC01; PC01R, EX01, PC02, PC02R DIVINE, EX02, and EX02C/SAO were not included in training. Training scale is also modest. These models remain far behind the AI Bandai used while ZENONZARD was live. Codex assisted with the implementation, drawing on public methods and architecture from ygo-agent.",
    codemanTitle: "Each Codeman keeps a recent local match memory",
    codemanBody: "After a match, part of that Codeman's recent history and replay is stored locally. Dedicated training can produce a Codeman-specific .pt model; when that Codeman is selected as an opponent, its own model takes priority. Otherwise the public default model is used.",
    flowBattle: "Finish match", flowMemory: "Recent memory", flowTrain: "Optional training",
    advisorBody: "Click your own Codeman during a decision to ask the AI for a suggestion. Given the current model quality, this is an observable entertainment assistant, not a dependable coach.",
    screensEyebrow: "Actual UI", screensTitle: "The full ZZ experience, including 106 PC02R DIVINE cards and 70 paired EX02C/SAO–EX02 faces", screenBattleLabel: "In-game battle UI",
    screenBattleTitle: "Both zones, hands, Forces, phases, and prompts share one tabletop", screenHome: "Home and feature entry points", screenLobby: "Deck, mode, and Codeman setup",
    replayTitle: "Turn your own matches into reviewable training material",
    replayBody: "With an NVIDIA GPU and a working CUDA environment, you can run local training from your own battle history. This remains experimental entertainment: Replay may reveal a different choice in a loss, but the system does not promise a winning line.",
    replayLink: "Read the training setup →", onlineTitle: "Direct LAN play or a personal online server",
    onlineBody: "Online play requires both clients and the connected server to report exactly the same applicationVersion. Check all three before connecting; the same requirement applies to self-hosted servers. Online Game supports rooms on the same LAN and the maintainer's personal server. That server is in Canada; stability elsewhere has not been thoroughly tested. Mainland China will usually require a proxy for a stable connection.",
    onlineLink: "Read the online guide →", onlineDemo: "Online version demo", contentEyebrow: "CONTENT STATUS", contentTitle: "Current scope",
    poolTitle: "Card pool", poolBody: "The pool includes the basic cards, EX01, PC01, PC01R, PC02, and 106 PC02R DIVINE cards, plus 70 EX02C/SAO cards and their corresponding EX02 original faces.", testingTitle: "Testing", testingBody: "A personal project cannot cover enough card combinations, so small rules or UI bugs may remain.",
    englishTitle: "English build", englishBody: "The asserts.7z resource pack includes English card faces. Cards not covered locally may still fall back to official URLs.",
    musicTitle: "BGM", musicBody: "Choose the battle BGM from the persistent top bar or Settings. The complete asset pack contains ZZ character songs.",
    thanksTitle: "Acknowledgements", thanksBody: "Special thanks to theFeri for 50+ high-resolution playmat images, and to Valkyrie for the English text.",
    installEyebrow: "INSTALLATION", installTitle: "Download v0.5.4; fetch assets on first launch",
    installLead: "The v0.5.4 Windows build stores decks in data/decks/ inside the installation directory. On first launch, it migrates decks from the legacy %APPDATA%\\zenonzard-clone\\game-data\\decks\\ folder, keeps the original files as backups, and does not overwrite conflicting decks. The Holy Force protects eligible friendly minions from targeting effects granted to opposing minions by a Blessing. Enrico's effect makes both players discard before drawing. Online play retries a disconnected session up to five times and preserves the room code. Battle logs are paginated during a match and on the results page. Large reconnect messages are sent in fragments. Online replays are saved in data/replays/ inside the game directory; recordings with missing data are marked incomplete. Both clients and the server must use matching versions; a v0.5.4 client requires a v0.5.4 server. The Windows installer and Linux portable bundle include the playable game and default models. If a complete asserts/ directory is missing, the desktop client asks to download and install asserts.7z, including English card faces.",
    installStep1Title: "Choose your platform", installStep1Body: "Use the installer on Windows, the portable bundle on Linux, or the source package on macOS and for development. Self-hosting uses a separate multiplayer server package.",
    installStep2Title: "Fetch assets on first launch", installStep2Body: "If asserts/ is missing, the client asks before downloading asserts.7z, checks its CRC, and extracts it at the app root. The archive is 1.53 GB, expands to 1.58 GB, and needs at least 3.2 GB free. English card faces are included; cancelling exits without starting, and failed installs can be retried.",
    installStep3Title: "Dependencies for source only", installStep3Body: "The Windows installer needs no Python or Node.js. Source launch requires Python 3.10+, Node.js 20+, and npm install.",
    installStep4Title: "Launch", installStep4Body: "Launch the installed Windows build from the Start menu or desktop shortcut. Linux bundles run ./launch-electron.sh after extraction. Source builds use .cmd, .sh, or npm run electron:dev.",
    requirementsTitle: "Requirements", reqOs: "OS", reqOsBody: "Windows 10/11 installer; Linux portable bundle; experimental source launch on macOS", reqPython: "Not needed for Windows installer; Linux bundle prepares its runtime on first launch; 3.10+ for source", reqNode: "Not needed for Windows installer; Linux bundle prepares its runtime on first launch; 20+ for source", reqGpu: "GPU", reqGpuBody: "Not required to play; local training needs an NVIDIA GPU and CUDA",
    downloadCode: "Download Windows v0.5.4", downloadLinux: "Download Linux v0.5.4", downloadAssets: "Open asserts.7z asset folder (English faces included)", hashNote: "asserts.7z is 1,534,680,950 bytes and expands to 1,577,092,255 bytes; reserve at least 3.2 GB. Bundled 7-Zip checks the CRC. See the checksum list for program package SHA256 values.",
    storyTitle: "Next: a personal story and frontend for each player",
    storyBody: "Story Mode is not implemented yet. The long-term goal is to create a game in which an Agent interacts with the user automatically, together with a matching visual-novel-style frontend. It will draw on the SillyTavern community's experience with characters, world books, and long-term interaction to build a personal ZZ experience shared with the player's own Codeman.",
    storyCaveat: "This is a future goal, not a claim that generative story features ship in version one.",
    contributeEyebrow: "CONTRIBUTE", contributeTitle: "RL, card-data, and localization contributors are welcome",
    contributeBody: "The project especially welcomes reinforcement-learning experts interested in whether a genuinely useful offline ZZ AI can be trained. English card art, translations, rules testing, and bug reports matter just as much.",
    starGithubShort: "Star", starGithub: "Star on GitHub", starNote: "A star is the easiest way to support the project, and it helps keep updates coming.",
    reportIssue: "Open an issue", joinDiscussion: "Join discussions", footerUnofficial: "An unofficial, non-commercial fan development and research project.",
    footerRights: "ZENONZARD names, characters, card art, music, and related assets belong to their respective rights holders. This project is not affiliated with or endorsed by BANDAI, STRAIGHT EDGE, or SUNRISE.",
    backTop: "Back to top ↑",
    downloadSource: "Download source",
    downloadServer: "Download multiplayer server",
    downloadChecksums: "SHA256 checksums",
  },
};

const modeContent = {
  human: ["01", "modeHumanTitle", "modeHumanBody"],
  god: ["02", "modeGodTitle", "modeGodBody"],
  aivai: ["03", "modeAiTitle", "modeAiBody"],
};

const difficultyContent = {
  easy: ["easyTitle", "easyBody"],
  medium: ["mediumTitle", "mediumBody"],
  high: ["highTitle", "highBody"],
};

let currentLanguage = "zh";

function translated(key) {
  return copy[currentLanguage][key] || copy.zh[key] || key;
}

function applyLanguage(language) {
  currentLanguage = copy[language] ? language : "zh";
  document.documentElement.lang = currentLanguage === "zh" ? "zh-CN" : currentLanguage === "ja" ? "ja" : "en";
  document.querySelectorAll("[data-i18n]").forEach((element) => {
    element.textContent = translated(element.dataset.i18n);
  });
  document.querySelectorAll("[data-lang]").forEach((button) => {
    button.setAttribute("aria-pressed", String(button.dataset.lang === currentLanguage));
  });
  const selectedMode = document.querySelector("[data-mode][aria-selected='true']");
  renderMode(selectedMode ? selectedMode.dataset.mode : "human");
  const selectedDifficulty = document.querySelector("[data-difficulty][aria-selected='true']");
  renderDifficulty(selectedDifficulty ? selectedDifficulty.dataset.difficulty : "easy");
  try { localStorage.setItem("zz-site-language", currentLanguage); } catch (_) {}
}

function renderMode(mode) {
  const values = modeContent[mode] || modeContent.human;
  const panel = document.querySelector("[data-mode-copy]");
  panel.querySelector(".mode-index").textContent = values[0];
  panel.querySelector("h3").textContent = translated(values[1]);
  panel.querySelector("p").textContent = translated(values[2]);
  document.querySelectorAll("[data-mode]").forEach((button) => {
    button.setAttribute("aria-selected", String(button.dataset.mode === mode));
  });
}

function renderDifficulty(level) {
  const values = difficultyContent[level] || difficultyContent.easy;
  const panel = document.querySelector("[data-difficulty-copy]");
  panel.querySelector("h3").textContent = translated(values[0]);
  panel.querySelector("p:last-child").textContent = translated(values[1]);
  document.querySelectorAll("[data-difficulty]").forEach((button) => {
    button.setAttribute("aria-selected", String(button.dataset.difficulty === level));
  });
}

function configureLinks() {
  const projectUrl = RELEASE_CONFIG.projectUrl.replace(/\/$/, "");
  document.querySelectorAll("[data-repo-link]").forEach((link) => { link.href = RELEASE_CONFIG.programUrl; });
  document.querySelectorAll("[data-linux-link]").forEach((link) => { link.href = RELEASE_CONFIG.linuxBundleUrl; });
  document.querySelectorAll("[data-source-link]").forEach((link) => { link.href = RELEASE_CONFIG.sourceUrl; });
  document.querySelectorAll("[data-server-link]").forEach((link) => { link.href = RELEASE_CONFIG.serverUrl; });
  document.querySelectorAll("[data-checksums-link]").forEach((link) => { link.href = RELEASE_CONFIG.checksumsUrl; });
  document.querySelectorAll("[data-star-link]").forEach((link) => { link.href = projectUrl; });
  document.querySelectorAll("[data-issues-link]").forEach((link) => { link.href = `${projectUrl}/issues`; });
  document.querySelectorAll("[data-discussions-link]").forEach((link) => { link.href = `${projectUrl}/discussions`; });
  document.querySelectorAll("[data-asset-link]").forEach((link) => {
    if (!RELEASE_CONFIG.assetPackUrl) return;
    link.href = RELEASE_CONFIG.assetPackUrl;
    link.classList.remove("is-disabled");
    link.removeAttribute("aria-disabled");
    link.textContent = currentLanguage === "ja" ? "asserts.7z のリソースフォルダを開く（英語カード画像含む）" : currentLanguage === "en" ? "Open asserts.7z asset folder (English faces included)" : "打开 asserts.7z 资源文件夹（含英文卡图）";
  });
}

document.addEventListener("click", (event) => {
  const language = event.target.closest("[data-lang]");
  if (language) { applyLanguage(language.dataset.lang); configureLinks(); return; }
  const mode = event.target.closest("[data-mode]");
  if (mode) { renderMode(mode.dataset.mode); return; }
  const difficulty = event.target.closest("[data-difficulty]");
  if (difficulty) renderDifficulty(difficulty.dataset.difficulty);
});

window.addEventListener("scroll", () => {
  document.querySelector("[data-header]").classList.toggle("scrolled", window.scrollY > 20);
}, { passive: true });

let savedLanguage = "zh";
try { savedLanguage = localStorage.getItem("zz-site-language") || "zh"; } catch (_) {}
applyLanguage(savedLanguage);
configureLinks();
