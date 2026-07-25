"use strict";

const RELEASE_CONFIG = {
  repoUrl: "https://github.com/TohmaN233/ZZ-Project",
  assetPackUrl: "https://drive.google.com/drive/folders/1R8NwBsR2QBvDHUwynZqLooZYI8TlX8TZ?usp=sharing",
};

const copy = {
  zh: {
    skip: "跳到正文",
    navFeatures: "功能", navAi: "AI 与 Codeman", navInstall: "安装", navRoadmap: "未来计划",
    heroEyebrow: "非官方 · 单机优先 · 持续开发",
    heroCopy: "在现代桌面环境中重新体验 ZZ：构筑卡组、与三档 AI 对战、回看牌局，也可以通过局域网或个人服务器联机。",
    heroInstall: "查看安装方法", heroExplore: "了解当前版本", heroPlatforms: "Windows · Linux / macOS 源码启动", heroLanguage: "中文 / 日本語 / English",
    statusOneTitle: "当前卡池", statusOneBody: "基础卡 + PC01", statusTwoTitle: "对战方式", statusTwoBody: "单机 / 局域网 / 在线",
    statusThreeTitle: "AI 档位", statusThreeBody: "Greedy + 两档 RL", statusFourTitle: "版本状态", statusFourBody: "首个公开版本",
    featuresEyebrow: "Game Lobby", featuresTitle: "组卡到开局皆在游戏大厅",
    featuresLead: "选择双方卡组、Codeman、卡垫与 AI 难度，然后进入你想要的对战方式。当前版本以完整的单机流程为核心。",
    modeHumanTab: "人 VS AI", modeGodTab: "神视点", modeHumanTitle: "普通人机对战",
    modeHumanBody: "你控制一方，另一方由所选难度的 AI 与 Codeman 配置驱动。这是最接近普通游玩的一种模式。",
    modeGodTitle: "神视点：左手打右手", modeGodBody: "双方手牌全部可见，而且你能操作两边。适合验证规则、复盘选择，或单纯自己与自己对战。",
    modeAiTitle: "AI 自动对战", modeAiBody: "两边都交给 AI。你可以观察策略差异、快速产生对局记录，或用它检查一套卡组的基本运作。",
    featureDeck: "创建、保存与编辑卡组", featureProfile: "分别选择双方 Codeman 与卡垫", featureSides: "指定先后手与玩家所在侧",
    featureBattleTitle: "卡牌对战", featureBattleBody: "完整处理 Mana、移动权、Force、Flash、战斗、触发与目标选择等核心流程。",
    featureDeckTitle: "卡组制作", featureDeckBody: "搜索卡池、检查张数与 Force 配置，并保存为大厅可直接选择的卡组。",
    featureReplayTitle: "Replay", featureReplayBody: "保存最近对局并按事件回看；训练结果可以关联回放，寻找输局中的其他路线。",
    featureOnlineTitle: "Online", featureOnlineBody: "支持同一局域网直连，也支持通过项目维护者的个人服务器建立房间。",
    aiEyebrow: "AI & Codeman", aiTitle: "三档离线AI对手",
    aiLead: "Easy 是 Greedy CPU；Medium 与 High 使用强化学习训练出的策略。训练规模有限，因此现阶段的定位是可玩的研究与娱乐功能，而不是高水平竞技对手。",
    difficultyLabel: "当前说明", easyTitle: "Greedy CPU", easyBody: "不加载训练模型，依据合法行动与人工启发式权重选择当前看来最有利的动作，运行快，也最容易理解。",
    mediumTitle: "RL Baseline", mediumBody: "加载当前保留的深度强化学习基线模型。它能结合完整局面评分行动，但训练覆盖面与对局量仍然有限。",
    highTitle: "Current RL Actor", highBody: "加载当前默认的增量训练 Actor，是三档中最新的策略。它并不等同于稳定的高水平 AI，遇到训练分布之外的牌局仍可能作出明显失误。",
    truthTitle: "关于 AI 水平的诚实说明",
    truthBody: "作者拥有统计学学位，但没有修读强化学习课程，研究方向也与此无关；模型训练规模同样不大。当前 AI 与 ZENONZARD 正式运营时期万代使用的 AI 仍有明显差距。相关实现由 Codex 协助编写，并参考了 ygo-agent 的公开方法与工程结构。",
    codemanTitle: "每个 Codeman 都有自己的近期对战记忆",
    codemanBody: "对局结束后，系统会在本机保存该 Codeman 最近的一部分战斗记录与回放。若你为某个 Codeman 进行了专门训练，并生成了它自己的 .pt 模型，选择这个对手时会优先加载该专属模型；没有专属模型时则使用公开默认模型。",
    flowBattle: "完成对局", flowMemory: "近期记忆", flowTrain: "可选训练",
    advisorBody: "对战时点击自己的 Codeman，可以让 AI 对当前选择给出建议。由于模型能力有限，这更像一个可观察的娱乐助手，而不是可靠教练。",
    screensEyebrow: "Actual UI", screensTitle: "完整ZZ体验：目前卡池PC01", screenBattleLabel: "实机对战界面",
    screenBattleTitle: "双方区域、手牌、Force、阶段与提示都在同一张桌面上", screenHome: "首页与功能入口", screenLobby: "卡组、模式与 Codeman 配置",
    replayTitle: "把自己的牌局变成可回看的训练材料",
    replayBody: "如果本机具备 NVIDIA GPU 与可用的 CUDA 环境，可以基于自己的对战记录运行本地训练。它仍是实验性的娱乐功能：一次输局也许能在 Replay 中发现另一个选择，但系统不会保证找到必胜解。",
    replayLink: "查看训练环境说明 →", onlineTitle: "局域网直连，或通过个人服务器联网",
    onlineBody: "Online Game 支持同一局域网内开房，也支持项目维护者的个人服务器。服务器位于加拿大，其他地区的稳定性未经充分验证；中国大陆通常需要代理才能稳定连接。",
    onlineLink: "查看联机说明 →", contentEyebrow: "CONTENT STATUS", contentTitle: "当前内容边界",
    poolTitle: "卡池", poolBody: "目前包含基本卡与 PC01，之后会逐步更新，直至补全卡池。", testingTitle: "测试", testingBody: "个人项目无法覆盖足够多的组合测试，当前版本可能仍有小型规则或界面问题。",
    englishTitle: "英文版", englishBody: "英文版卡图直接使用官网链接，已知有图和卡没对齐的现象。英语圈的用户若能提供卡图资源和英文文本，此问题能轻易解决。",
    musicTitle: "BGM", musicBody: "基础设置中可选择对战 BGM；完整资源包包含 ZZ 各角色歌曲。",
    installEyebrow: "INSTALLATION", installTitle: "代码与大型美术资源分开下载",
    installLead: "GitHub 仓库保存源码、桌面客户端和当前默认模型；卡图、角色图、视频与音乐放在独立资源包中。解压到正确位置后即可启动。",
    installStep1Title: "下载源码", installStep1Body: "从 GitHub Releases 下载源码包，或使用 Git 与 Git LFS 克隆仓库。",
    installStep2Title: "放入资源包", installStep2Body: "下载 ZZ-Assets-v1.zip，将其中的 asserts 文件夹放到项目根目录；最终应能看到 asserts/images、asserts/audio 等目录。",
    installStep3Title: "安装依赖", installStep3Body: "安装 Python 3.10+ 与 Node.js 20+，先运行 python -m pip install -r requirements-runtime.txt，再运行 npm install。",
    installStep4Title: "启动客户端", installStep4Body: "Windows 使用 .cmd，Linux 使用 .sh，macOS 使用 .command；也可以运行 npm run electron:dev。",
    requirementsTitle: "运行要求", reqOs: "系统", reqOsBody: "Windows 10/11；Linux/macOS 源码启动（实验支持）", reqGpu: "显卡", reqGpuBody: "游玩不要求；本地训练需要 NVIDIA GPU / CUDA",
    downloadCode: "打开 GitHub 仓库", downloadAssets: "下载完整资源包", hashNote: "文件大小与 SHA-256 已记录在资源清单和发布说明中，便于检查下载完整性。",
    storyTitle: "下一阶段：每位玩家自己的故事与前端",
    storyBody: "Story Mode 目前尚未开发。长期目标是设计由 Agent 自动与用户交互的游戏，对应实现 GAL 前端，并吸收 SillyTavern 相关社群在角色、世界书与长期互动方面积累的经验，构建个人专属的、与自己的 Codeman 一起经历的 ZZ 体验。",
    storyCaveat: "这是未来目标，不代表第一版已经提供生成式剧情功能。",
    contributeEyebrow: "CONTRIBUTE", contributeTitle: "欢迎懂强化学习、卡牌资料或本地化的朋友加入",
    contributeBody: "尤其希望有强化学习经验的贡献者一起研究：是否能训练出真正适合离线运行的 ZZ AI。英文卡图、卡牌译文、规则测试与 Bug 报告同样重要。",
    reportIssue: "提交 Issue", joinDiscussion: "参与讨论", footerUnofficial: "非官方、非商业的粉丝开发与研究项目。",
    footerRights: "ZENONZARD 名称、角色、卡图、音乐与相关素材的权利归各自权利方所有。本项目与 BANDAI / STRAIGHT EDGE / SUNRISE 无隶属或授权关系。",
    backTop: "返回顶部 ↑",
  },
  ja: {
    skip: "本文へ移動",
    navFeatures: "機能", navAi: "AI と Codeman", navInstall: "導入", navRoadmap: "今後の計画",
    heroEyebrow: "非公式 · オフライン中心 · 開発継続中",
    heroCopy: "現代のデスクトップ環境で ZZ をもう一度。デッキ構築、3 段階の AI、リプレイに加え、LAN または個人サーバー経由の対戦にも対応します。",
    heroInstall: "導入方法を見る", heroExplore: "現行版を知る", heroPlatforms: "Windows · Linux / macOS ソース起動", heroLanguage: "中文 / 日本語 / English",
    statusOneTitle: "現在のカードプール", statusOneBody: "ベーシック + PC01", statusTwoTitle: "対戦方法", statusTwoBody: "オフライン / LAN / オンライン",
    statusThreeTitle: "AI レベル", statusThreeBody: "Greedy + RL 2段階", statusFourTitle: "リリース", statusFourBody: "初回公開版",
    featuresEyebrow: "Game Lobby", featuresTitle: "デッキ構築から対戦開始まで、すべてゲームロビーで",
    featuresLead: "両者のデッキ、Codeman、プレイマット、AI 難度を選び、好きな対戦形式へ進みます。現行版の中心は一通り遊べるオフライン対戦です。",
    modeHumanTab: "人 VS AI", modeGodTab: "神視点", modeHumanTitle: "通常の対 AI 戦",
    modeHumanBody: "片側をプレイヤーが操作し、もう片側を選択した難度と Codeman 設定の AI が担当します。最も一般的な遊び方です。",
    modeGodTitle: "神視点：一人二役", modeGodBody: "両者の手札を公開し、両側を操作できます。ルール確認、選択の検証、自分同士の対戦に向いたモードです。",
    modeAiTitle: "AI 自動対戦", modeAiBody: "両側を AI に任せます。方策の違いを観察し、対戦履歴を生成し、デッキの基本動作を確認できます。",
    featureDeck: "デッキの作成・保存・編集", featureProfile: "両者の Codeman とプレイマットを個別に選択", featureSides: "先後攻とプレイヤー側を指定",
    featureBattleTitle: "カードバトル", featureBattleBody: "マナ、移動権、フォース、フラッシュ、戦闘、誘発、対象選択などの主要フローを処理します。",
    featureDeckTitle: "デッキ構築", featureDeckBody: "カード検索、枚数・フォース構成の確認、ロビーから選べるデッキの保存に対応します。",
    featureReplayTitle: "Replay", featureReplayBody: "直近の対戦をイベント単位で再生。学習結果と紐づけ、敗戦時の別ルートを探せます。",
    featureOnlineTitle: "Online", featureOnlineBody: "同一 LAN での直接接続と、プロジェクト管理者の個人サーバーを使ったルーム対戦に対応します。",
    aiEyebrow: "AI & Codeman", aiTitle: "3 段階のオフライン AI 対戦相手",
    aiLead: "Easy は Greedy CPU、Medium と High は強化学習方策です。学習規模が小さいため、現段階では競技用の強敵ではなく、遊べる研究・娯楽機能という位置づけです。",
    difficultyLabel: "現在の説明", easyTitle: "Greedy CPU", easyBody: "学習モデルを読み込まず、合法手と手作業のヒューリスティック重みに基づいて、その場で有利に見える行動を選びます。高速で理解しやすい方式です。",
    mediumTitle: "RL Baseline", mediumBody: "現在保持している深層強化学習の基準モデルを読み込みます。局面全体から行動を評価しますが、学習範囲と対戦数はまだ限定的です。",
    highTitle: "Current RL Actor", highBody: "現在の既定となる増分学習 Actor を読み込みます。3 段階で最も新しい方策ですが、安定した高水準 AI ではなく、学習分布外では明確なミスも起こります。",
    truthTitle: "AI の強さに関する率直な説明",
    truthBody: "作者は統計学の学位を持ちますが、強化学習の授業を履修した経験はなく、研究分野も別領域です。学習規模も小さく、正式サービス時にバンダイが使用していた AI とは大きな差があります。実装は Codex の支援を受け、ygo-agent の公開手法と構成を参考にしています。",
    codemanTitle: "各 Codeman は直近の対戦記憶を持ちます",
    codemanBody: "対戦終了後、その Codeman の最近の戦績とリプレイの一部をローカルに保存します。専用学習で固有の .pt モデルを生成した場合、対戦相手として選ぶとそのモデルを優先します。専用モデルがない場合は公開既定モデルを使用します。",
    flowBattle: "対戦終了", flowMemory: "最近の記憶", flowTrain: "任意の学習",
    advisorBody: "対戦中に自分の Codeman をクリックすると、現在の選択に対する AI の提案を確認できます。モデル能力が限られるため、信頼できるコーチではなく、観察できる娯楽アシスタントです。",
    screensEyebrow: "Actual UI", screensTitle: "ZZ を一通り体験：現在のカードプールは PC01", screenBattleLabel: "実際の対戦画面",
    screenBattleTitle: "両者のゾーン、手札、フォース、フェーズ、操作案内を一つの盤面に", screenHome: "ホームと機能入口", screenLobby: "デッキ、モード、Codeman 設定",
    replayTitle: "自分の対戦を、見返せる学習素材に",
    replayBody: "NVIDIA GPU と利用可能な CUDA 環境があれば、自分の対戦記録を使ったローカル学習を実行できます。これは実験的な娯楽機能で、Replay から別の選択が見つかる場合はありますが、勝ち筋を保証しません。",
    replayLink: "学習環境の説明を見る →", onlineTitle: "LAN 直結、または個人サーバー経由で対戦",
    onlineBody: "Online Game は同一 LAN でのルーム作成と、管理者の個人サーバーに対応します。サーバーはカナダにあり、他地域での安定性は十分に検証されていません。中国本土からは通常プロキシが必要です。",
    onlineLink: "オンライン対戦の説明を見る →", contentEyebrow: "CONTENT STATUS", contentTitle: "現在の収録範囲",
    poolTitle: "カード", poolBody: "現在はベーシックカードと PC01 を収録しています。今後、カードプールの完成に向けて段階的に追加します。", testingTitle: "テスト", testingBody: "個人開発のため、十分な組み合わせテストはできておらず、小さなルール・表示不具合が残る可能性があります。",
    englishTitle: "英語版", englishBody: "英語版のカード画像は公式 URL を直接使用しているため、画像とカードが一致しない既知の問題があります。英語圏の方からカード画像と英語テキストをご提供いただければ、容易に解決できます。",
    musicTitle: "BGM", musicBody: "基本設定から対戦 BGM を選択できます。完全版アセットパックには ZZ のキャラクターソングが含まれます。",
    installEyebrow: "INSTALLATION", installTitle: "コードと大型アセットは別々にダウンロード",
    installLead: "GitHub にはソース、デスクトップクライアント、現在の既定モデルを収録します。カード画像、キャラクター、動画、音楽は別アセットパックです。正しい場所へ展開すれば起動できます。",
    installStep1Title: "ソースを取得", installStep1Body: "GitHub Releases のソースパッケージをダウンロードするか、Git と Git LFS でリポジトリをクローンします。",
    installStep2Title: "アセットを配置", installStep2Body: "ZZ-Assets-v1.zip を取得し、中の asserts フォルダをプロジェクト直下へ配置します。asserts/images、asserts/audio などが見える状態にします。",
    installStep3Title: "依存関係を導入", installStep3Body: "Python 3.10+ と Node.js 20+ を用意し、python -m pip install -r requirements-runtime.txt、続いて npm install を実行します。",
    installStep4Title: "クライアントを起動", installStep4Body: "Windows は .cmd、Linux は .sh、macOS は .command を使用します。npm run electron:dev でも起動できます。",
    requirementsTitle: "動作要件", reqOs: "OS", reqOsBody: "Windows 10/11。Linux/macOS はソース起動の実験対応", reqGpu: "GPU", reqGpuBody: "通常プレイは不要。ローカル学習には NVIDIA GPU / CUDA が必要",
    downloadCode: "GitHub リポジトリ", downloadAssets: "完全版アセットをダウンロード", hashNote: "ファイルサイズと SHA-256 はアセットマニフェストとリリースノートに記載されています。",
    storyTitle: "次の段階：プレイヤーごとの物語とフロントエンド",
    storyBody: "Story Mode は未実装です。長期目標は、Agent がユーザーと自動的に交流するゲームと、それに対応する GAL 風フロントエンドを実現することです。SillyTavern 関連コミュニティが蓄積してきたキャラクター、世界設定、長期的な交流の知見を取り入れ、自分の Codeman と共に過ごす、プレイヤー個人専用の ZZ 体験を構築します。",
    storyCaveat: "これは将来目標であり、初回版に生成ストーリー機能が含まれるという意味ではありません。",
    contributeEyebrow: "CONTRIBUTE", contributeTitle: "強化学習、カード資料、ローカライズの協力者を歓迎します",
    contributeBody: "特に、オフラインで動く本格的な ZZ AI を学習できるか、強化学習経験者と一緒に研究したいと考えています。英語カード画像、翻訳、ルールテスト、バグ報告も重要です。",
    reportIssue: "Issue を送る", joinDiscussion: "議論に参加", footerUnofficial: "非公式・非商用のファン開発および研究プロジェクトです。",
    footerRights: "ZENONZARD の名称、キャラクター、カード画像、音楽、関連素材の権利は各権利者に帰属します。本プロジェクトは BANDAI / STRAIGHT EDGE / SUNRISE の公式・認可プロジェクトではありません。",
    backTop: "ページ上部へ ↑",
  },
  en: {
    skip: "Skip to content",
    navFeatures: "Features", navAi: "AI & Codeman", navInstall: "Install", navRoadmap: "Roadmap",
    heroEyebrow: "Unofficial · Offline first · In development",
    heroCopy: "Play ZZ on a modern desktop: build decks, face three AI tiers, review matches, or connect over LAN and a community-run personal server.",
    heroInstall: "Installation guide", heroExplore: "Explore this release", heroPlatforms: "Windows · Linux / macOS source launch", heroLanguage: "Chinese / Japanese / English",
    statusOneTitle: "Card pool", statusOneBody: "Basic + PC01", statusTwoTitle: "Play", statusTwoBody: "Offline / LAN / Online",
    statusThreeTitle: "AI tiers", statusThreeBody: "Greedy + two RL tiers", statusFourTitle: "Release", statusFourBody: "First public version",
    featuresEyebrow: "Game Lobby", featuresTitle: "Build your deck and start the match in the Game Lobby",
    featuresLead: "Choose both decks, Codemen, playmats, and AI difficulty before entering a battle mode. A complete offline match flow is the core of this release.",
    modeHumanTab: "Human VS AI", modeGodTab: "God view", modeHumanTitle: "Standard human vs AI",
    modeHumanBody: "You control one side. The other is driven by the selected AI tier and Codeman configuration. This is the closest mode to regular play.",
    modeGodTitle: "God view: play both sides", modeGodBody: "Both hands are visible and you control both players. It is useful for checking rules, reviewing decisions, or simply playing against yourself.",
    modeAiTitle: "AI autoplay", modeAiBody: "AI controls both sides. Observe policy differences, generate match records, or check whether a deck can execute its basic plan.",
    featureDeck: "Create, save, and edit decks", featureProfile: "Choose each side's Codeman and playmat", featureSides: "Set first player and the human side",
    featureBattleTitle: "Card battle", featureBattleBody: "Handles Mana, movement rights, Forces, Flash timing, combat, triggers, and target selection across the core game flow.",
    featureDeckTitle: "Deck builder", featureDeckBody: "Search the pool, validate card count and Force setup, then save decks that can be selected directly in the lobby.",
    featureReplayTitle: "Replay", featureReplayBody: "Keep recent matches and review them event by event. Training outputs can link back to replays to explore alternatives in a loss.",
    featureOnlineTitle: "Online", featureOnlineBody: "Connect directly on the same LAN or create a room through the maintainer's personal server.",
    aiEyebrow: "AI & Codeman", aiTitle: "Three tiers of offline AI opponents",
    aiLead: "Easy is a Greedy CPU. Medium and High use reinforcement-learning policies. Training is small-scale, so these are playable research and entertainment features rather than competitive opponents.",
    difficultyLabel: "Current behavior", easyTitle: "Greedy CPU", easyBody: "Loads no trained model. It scores legal actions with hand-authored heuristics and picks the option that looks best immediately. It is fast and the easiest tier to understand.",
    mediumTitle: "RL Baseline", mediumBody: "Loads the retained deep-RL baseline and evaluates actions from the broader position. Its training coverage and game count are still limited.",
    highTitle: "Current RL Actor", highBody: "Loads the current incremental-training actor, the newest of the three policies. It is not consistently strong and can make obvious mistakes outside its training distribution.",
    truthTitle: "An honest note about AI strength",
    truthBody: "The author has a statistics degree, but has not taken reinforcement-learning courses and does not research this field. Training scale is also modest. These models remain far behind the AI Bandai used while ZENONZARD was live. Codex assisted with the implementation, drawing on public methods and architecture from ygo-agent.",
    codemanTitle: "Each Codeman keeps a recent local match memory",
    codemanBody: "After a match, part of that Codeman's recent history and replay is stored locally. Dedicated training can produce a Codeman-specific .pt model; when that Codeman is selected as an opponent, its own model takes priority. Otherwise the public default model is used.",
    flowBattle: "Finish match", flowMemory: "Recent memory", flowTrain: "Optional training",
    advisorBody: "Click your own Codeman during a decision to ask the AI for a suggestion. Given the current model quality, this is an observable entertainment assistant, not a dependable coach.",
    screensEyebrow: "Actual UI", screensTitle: "The full ZZ experience: current card pool PC01", screenBattleLabel: "In-game battle UI",
    screenBattleTitle: "Both zones, hands, Forces, phases, and prompts share one tabletop", screenHome: "Home and feature entry points", screenLobby: "Deck, mode, and Codeman setup",
    replayTitle: "Turn your own matches into reviewable training material",
    replayBody: "With an NVIDIA GPU and a working CUDA environment, you can run local training from your own battle history. This remains experimental entertainment: Replay may reveal a different choice in a loss, but the system does not promise a winning line.",
    replayLink: "Read the training setup →", onlineTitle: "Direct LAN play or a personal online server",
    onlineBody: "Online Game supports rooms on the same LAN and the maintainer's personal server. That server is in Canada; stability elsewhere has not been thoroughly tested. Mainland China will usually require a proxy for a stable connection.",
    onlineLink: "Read the online guide →", contentEyebrow: "CONTENT STATUS", contentTitle: "Current scope",
    poolTitle: "Card pool", poolBody: "The current pool contains the basic cards and PC01. It will be expanded gradually until the card pool is complete.", testingTitle: "Testing", testingBody: "A personal project cannot cover enough card combinations, so small rules or UI bugs may remain.",
    englishTitle: "English build", englishBody: "The English build loads card images directly from official URLs, and some images are known to be paired with the wrong cards. This can be fixed easily if English-speaking users can provide the card images and corresponding English text.",
    musicTitle: "BGM", musicBody: "Battle BGM can be selected in Settings. The complete asset pack contains ZZ character songs.",
    installEyebrow: "INSTALLATION", installTitle: "Code and large media assets are separate downloads",
    installLead: "GitHub contains the source, desktop client, and current default models. Card art, characters, video, and music live in a separate asset pack. Extract it into the expected path and launch the client.",
    installStep1Title: "Get the source", installStep1Body: "Download the source package from GitHub Releases, or clone with Git and Git LFS.",
    installStep2Title: "Add the assets", installStep2Body: "Download ZZ-Assets-v1.zip and place its asserts folder in the project root. You should end up with asserts/images, asserts/audio, and the other asset directories.",
    installStep3Title: "Install dependencies", installStep3Body: "Install Python 3.10+ and Node.js 20+. Run python -m pip install -r requirements-runtime.txt, then npm install.",
    installStep4Title: "Launch", installStep4Body: "Use .cmd on Windows, .sh on Linux, or .command on macOS. npm run electron:dev also works.",
    requirementsTitle: "Requirements", reqOs: "OS", reqOsBody: "Windows 10/11; experimental source launch on Linux/macOS", reqGpu: "GPU", reqGpuBody: "Not required to play; local training needs an NVIDIA GPU and CUDA",
    downloadCode: "Open GitHub repository", downloadAssets: "Download full asset pack", hashNote: "The file size and SHA-256 are recorded in the asset manifest and release notes for integrity checks.",
    storyTitle: "Next: a personal story and frontend for each player",
    storyBody: "Story Mode is not implemented yet. The long-term goal is to create a game in which an Agent interacts with the user automatically, together with a matching visual-novel-style frontend. It will draw on the SillyTavern community's experience with characters, world books, and long-term interaction to build a personal ZZ experience shared with the player's own Codeman.",
    storyCaveat: "This is a future goal, not a claim that generative story features ship in version one.",
    contributeEyebrow: "CONTRIBUTE", contributeTitle: "RL, card-data, and localization contributors are welcome",
    contributeBody: "The project especially welcomes reinforcement-learning experts interested in whether a genuinely useful offline ZZ AI can be trained. English card art, translations, rules testing, and bug reports matter just as much.",
    reportIssue: "Open an issue", joinDiscussion: "Join discussions", footerUnofficial: "An unofficial, non-commercial fan development and research project.",
    footerRights: "ZENONZARD names, characters, card art, music, and related assets belong to their respective rights holders. This project is not affiliated with or endorsed by BANDAI, STRAIGHT EDGE, or SUNRISE.",
    backTop: "Back to top ↑",
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
  const repoUrl = RELEASE_CONFIG.repoUrl.replace(/\/$/, "");
  document.querySelectorAll("[data-repo-link]").forEach((link) => { link.href = repoUrl; });
  document.querySelectorAll("[data-issues-link]").forEach((link) => { link.href = `${repoUrl}/issues`; });
  document.querySelectorAll("[data-discussions-link]").forEach((link) => { link.href = `${repoUrl}/discussions`; });
  document.querySelectorAll("[data-asset-link]").forEach((link) => {
    if (!RELEASE_CONFIG.assetPackUrl) return;
    link.href = RELEASE_CONFIG.assetPackUrl;
    link.classList.remove("is-disabled");
    link.removeAttribute("aria-disabled");
    link.textContent = currentLanguage === "ja" ? "アセットをダウンロード" : currentLanguage === "en" ? "Download asset pack" : "下载完整资源包";
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
