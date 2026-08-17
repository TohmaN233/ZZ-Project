const app = document.getElementById("app");
const MultiplayerCardPolicy = window.ZZMultiplayerCardPolicy;
if (!MultiplayerCardPolicy) throw new Error("multiplayer card policy failed to load");

let appView = "home";
let state = null;
let catalog = {
  cards: [],
  forces: [],
  filters: [],
  defaultDecks: [],
  characters: [],
  homeGuide: null,
  playmats: [],
  manaAssets: {},
  uiAssets: {},
  devMode: false,
};
let savedDecks = [];
let settings = {
  playerProfile: { codemanId: null, playmatId: null },
  opponentProfile: { codemanId: null, playmatId: null },
  opponentAiDifficulty: "deep",
  uiLanguage: "zh",
  bgmTrack: "bgm_01",
  developerMode: false,
  reducedMotion: false,
};
const AI_AUTO_STEP_DELAY_MS = 850;
const AI_AUTO_VISUAL_POLL_MS = 120;
let selectedPlayerDeckKey = null;
let selectedOpponentDeckKey = null;
let selectedLaunchMode = "human-vs-ai";
let selectedPlaymatProfileKey = "playerProfile";
let activeMatchPayload = {};
let settingsNotice = null;
let deckEditor = {
  id: null,
  name: "New Deck",
  recipe: {},
  selectedForceIds: [],
  search: "",
  filters: {},
};
let deckCompletionLoading = false;
let autoTimer = null;
let autoEnabled = false;
let autoStepInFlight = false;
let selectedCardIid = null;
let selectedForceKey = null;
let pendingChoicePromptId = null;
let draggingBlessSourceIid = null;
let pendingBlessDrag = null;
let blessDragArrow = null;
let suppressCardDetailUntil = 0;
let selectedPlayerSide = null;
let selectedTrashSide = null;
let mulliganSelectedIids = new Set();
let pendingPaymentOptionId = null;
let paymentSelectionIids = new Set();
let pendingFieldReplaceSourceIid = null;
let pendingBaseReplaceSourceIid = null;
let pendingColorlessBaseReplace = false;
let bgmAudio = null;
let bgmTrackId = null;
let bgmPlaying = false;
let bgmError = null;
let homeThemeTimer = null;
let homeThemeActive = false;
let homeThemeVideoError = null;
let applicationUpdate = { status: "idle", currentVersion: null, latestVersion: null, error: null };
let sfxContext = null;
let publicRevealQueue = [];
let activePublicReveal = null;
let publicRevealBatchTimer = null;
let animationEventQueue = [];
let activeAnimationEvent = null;
let animationOverlayTimer = null;
let pendingVisualState = null;
let visualStateStaged = false;
let hiddenZoneMoveSourceKeys = new Set();
let lastAppliedMultiplayerViewKey = null;
let effectTargetSelectionIds = new Set();
let selectedCatalogCardId = null;
let battleDebugOpen = false;
let logModalOpen = false;
let battleDebugSearch = "";
let battleDebugFilters = {};
let battleDebugSide = "P1";
let battleDebugZone = "hand";
let battleDebugRested = false;
let aiAdvice = null;
let aiAdviceLoading = false;
let aiAdviceError = null;
let codemanTrainingStatus = {};
let codemanTrainingCircles = 10;
let codemanTrainingMethod = "gae_epoch1_local";
let codemanTrainingCheckpointInterval = 5;
let codemanTrainingPollTimers = {};
const CODEMAN_MEMORY_VIEW = "codeman-memory";
const CODEMAN_REPLAY_VIEW = "codeman-replay";
const AI_TRAINING_VIEW = "ai-training";
const ONLINE_VIEW = "online";
const ONLINE_SERVER_URL = "wss://zz.tgy233.top/multiplayer";
const LAN_SERVER_URL = "ws://127.0.0.1:32145";
let multiplayerUnsubscribe = null;
let multiplayerUi = {
  mode: "online",
  status: "OFFLINE",
  url: ONLINE_SERVER_URL,
  displayName: "Player",
  connectionId: null,
  playerId: null,
  matchId: null,
  room: null,
  view: null,
  pendingAction: null,
  lastError: null,
  networkRoute: "UNSELECTED",
  lan: { state: "STOPPED", discovered: [] },
};
let lanPendingCreateRoom = false;
let lanPendingJoin = null;
const PENDING_DUEL_LAUNCH_KEY = "zz_pending_duel_launch";
const BATTLE_SFX_SELECTION_KEY = "zz_battle_sfx_map";
const BATTLE_SFX_MAP = {
  heal: "sfx_heal",
  damage: {
    force: "sfx_force_damage",
    player: "sfx_player_damage",
  },
  baseMinionPlace: "sfx_base_minion_place",
  minionSummon: "sfx_minion_summon",
  attack: "sfx_minion_rest",
  block: "sfx_minion_clash",
  draw: "sfx_draw_card",
  shuffle: "sfx_shuffle",
};

let codemanReplayState = {
  codemanId: null,
  memory: [],
  replay: null,
  matchId: null,
  mode: "original",
  index: 0,
  animatingIndex: null,
  playing: false,
  loading: false,
  correcting: false,
  error: null,
};
let replayReadonlyMode = false;
let codemanReplayTimer = null;
let codemanReplaySettleTimer = null;

const BATTLE_DEBUG_ZONES = [
  { id: "hand", labelKey: "zoneHand", label: "Hand" },
  { id: "base", labelKey: "zoneBase", label: "Base" },
  { id: "field", labelKey: "zoneField", label: "Field" },
  { id: "trash", labelKey: "zoneTrash", label: "Trash" },
  { id: "deck", labelKey: "zoneDeck", label: "Deck" },
];

const CODEMAN_TRAINING_METHODS = [
  { id: "gae_epoch1_local", label: "GAE · 1 epoch" },
  { id: "vtrace_epoch2_native", label: "V-trace · 2 epoch" },
];

const LANGUAGES = [
  { id: "zh", label: "中文" },
  { id: "ja", label: "日本語" },
  { id: "en", label: "English" },
];

const BGM_TRACKS = [
  { id: "bgm_01", label: "01 Da La Doubt" },
  { id: "bgm_02", label: "02 WakeUp" },
  { id: "bgm_03", label: "03 It's so beautiful" },
  { id: "bgm_04", label: "04 Black & White" },
  { id: "bgm_05", label: "05 Angel's mission" },
  { id: "bgm_06", label: "06 I do L I love U" },
  { id: "bgm_07", label: "07 排他的メランコリー" },
  { id: "bgm_08", label: "08 Black Thief" },
  { id: "bgm_09", label: "09 ワンダーランドパレード" },
  { id: "bgm_10", label: "10 ス・リ・ル" },
  { id: "bgm_11", label: "11 knife_the_blossom" },
  { id: "bgm_12", label: "12 ドラマティックミステリー" },
  { id: "bgm_13", label: "13 Colorful World" },
  { id: "bgm_14", label: "14 Let's Get Started" },
  { id: "bgm_15", label: "15 STAND UP!" },
  { id: "bgm_16", label: "16 battaglia" },
  { id: "bgm_17", label: "17 Lazy Daily" },
  { id: "bgm_18", label: "18 dreamy maze" },
  { id: "bgm_19", label: "19 Double" },
  { id: "bgm_20", label: "20 MaGIC x NuMBER" },
];
const HOME_THEME_IDLE_MS = 15000;

const UI_TEXT = {
  zh: {
    language: "语言",
    home: "首页",
    storyMode: "Story Mode",
    gameLobby: "Game Lobby",
    onlineGame: "Online Game",
    onlineConnect: "连接",
    onlineDisconnect: "断开连接",
    onlineServerUrl: "服务器地址",
    onlinePlayerName: "玩家名",
    onlineCreateRoom: "创建房间",
    onlineJoinRoom: "加入房间",
    onlineRoomCode: "房间码",
    onlineReady: "准备",
    onlineCancelReady: "取消准备",
    onlineLeaveRoom: "离开房间",
    onlineConnectionStatus: "连接状态",
    onlineNetworkRoute: "网络路径",
    onlineWaitingOpponent: "等待对手",
    onlineOpeningChoice: "石头剪刀布决定先手",
    onlineOpeningWaiting: "已选择，等待对手",
    onlineOpeningTie: "平局，请重新选择",
    rock: "石头",
    paper: "布",
    scissors: "剪刀",
    onlineSelectDeck: "选择卡组",
    onlinePlayers: "玩家",
    onlineUnavailable: "联网对战需要桌面版运行环境。",
    onlineReconnecting: "连接中断，正在恢复对战…",
    onlineDisconnected: "已断线",
    lanGame: "LAN Game",
    lanHost: "主机开房",
    lanStopHost: "停止主机",
    lanDiscover: "搜索房间",
    lanManualAddress: "手动 IP / 地址",
    lanServerName: "房间名称",
    lanDiscoveredRooms: "发现的房间",
    lanNoRooms: "未发现局域网房间",
    lanHosting: "局域网服务",
    lanJoinHint: "另一台电脑请切到 LAN Game，搜索房间，或填写这个 IP，不要填 127.0.0.1",
    battleReview: "回顾对战",
    first: "先攻",
    second: "后攻",
    train: "训练",
    winner: "胜者",
    drawResult: "平局",
    phaseStart: "回合开始",
    phaseRefresh: "刷新",
    phaseDraw: "抽卡",
    phaseMana: "Mana",
    phaseMain: "主要",
    phaseEnd: "回合结束",
    promptMainAction: "选择行动",
    promptMulligan: "起手调度",
    promptForceBaseChoice: "选择 Base Minion",
    aiTraining: "AI 训练",
    replayTraining: "Replay & Training",
    replayTrainingShort: "对局回放 / AI 训练",
    trainingEnvironmentShort: "需要本机训练环境",
    trainingEnvironmentHint: "需要本机可运行 Python/项目依赖、tools 训练脚本、local_ai_training 基础模型或 Codeman champion，并且 data/codeman_ai 可写。",
    setting: "Setting",
    exit: "Exit",
    comingSoon: "占位",
    updateAvailable: "发现新版本 {version}",
    updateCurrent: "当前版本 {version}",
    viewRelease: "查看更新",
    startGame: "开始游戏",
    launchMode: "模式",
    modeHumanAi: "人机对战",
    modeGod: "上帝视角",
    modeAiVsAi: "AI vs AI",
    basicSettings: "基础设置",
    developerMode: "开发者模式",
    developerPassword: "开发者密码",
    enableDeveloperMode: "打开开发者模式",
    disableDeveloperMode: "关闭开发者模式",
    developerModeEnabled: "开发者模式已打开",
    developerModeDisabled: "开发者模式已关闭",
    reducedMotion: "减少动效",
    bgmSetting: "BGM",
    deckBuilder: "卡组制作",
    deckBuilderShort: "卡组",
    playmats: "卡垫库",
    continueDuel: "继续对战",
    decksCount: "{count} 套卡组",
    battle: "对战",
    quickHumanAi: "快速人机",
    godView: "上帝视角",
    aiVsAi: "AI vs AI",
    human: "玩家",
    god: "上帝视角",
    concede: "放弃",
    auto: "自动",
    pause: "暂停",
    run: "运行",
    step: "步进",
    endTurn: "回合结束",
    pass: "跳过",
    keep: "保留",
    redraw: "重新抽卡",
    new: "新开",
    gameOver: "游戏结束",
    operator: "操作者",
    homeGuideName: "广报 AI 米娜",
    homeGuideText: "先确认规则，再选择角色、卡垫和双方卡组。",
    openRulebook: "打开规则书",
    savedDecks: "保存的卡组",
    newDeck: "新建",
    startBattle: "进入对战",
    startWithDeck: "这个卡组开战",
    aiPilot: "AI 代打",
    editCopy: "编辑副本",
    edit: "编辑",
    delete: "删除",
    cardsCount: "{count} 张卡",
    empty: "空",
    loading: "载入中",
    openingDuel: "正在打开对战",
    profilePlayer: "我方",
    profileOpponent: "对手",
    playerCodeman: "我方 Codeman",
    opponentCodeman: "对手 Codeman",
    originalAvatar: "原始头像",
    player: "玩家",
    opponent: "对手",
    diceRollParityRule: "1/3/5：{player}先手 · 2/4/6：{opponent}先手",
    playerPlaymat: "我方卡垫",
    opponentPlaymat: "对手卡垫",
    defaultPlaymat: "默认卡垫",
    default: "默认",
    back: "返回",
    opponentAi: "对手 AI",
    deckPlayer: "我方卡组",
    deckOpponent: "对手卡组",
    clearFilters: "清除筛选",
    all: "全部",
    save: "保存",
    aiCompleteDeck: "AI补全",
    playGod: "上帝视角开战",
    aiTest: "AI 代打测试",
    cards: "卡牌",
    deck: "卡组",
    forces: "Force",
    force: "Force",
    cost: "费用",
    search: "搜索",
    details: "详情",
    close: "关闭",
    active: "激活",
    rested: "疲劳",
    destroyed: "已破坏",
    selected: "已选择",
    confirm: "确定",
    publicReveal: "公开",
    trash: "废弃区",
    newestFirst: "新卡在前",
    life: "生命",
    turn: "回合",
    activeSide: "行动方",
    log: "日志",
    battleLog: "战斗日志",
    openBattleLog: "打开战斗日志",
    latestLog: "最近记录",
    noBattleLog: "暂无战斗日志",
    legacyLogUnavailable: "旧版记录没有结构化的本地化日志。",
    aiAdvicePrefix: "建议",
    aiAdviceThinking: "Codeman 正在思考...",
    aiAdviceUnavailable: "AI 建议不可用。",
    aiAdviceNoPrompt: "当前没有需要建议的操作。",
    aiAdviceUnsupportedPrompt: "当前选择暂不支持 AI 建议。",
    aiAdviceNeedsCodeman: "选择 Codeman 后才会提供 AI 建议。",
    aiAdviceNotUserTurn: "当前不是玩家操作时点。",
    aiAdviceNoOptions: "当前没有可建议的选项。",
    aiAdviceBest: "这是 AI 当前评分最高的选择。",
    aiAdviceStrongLead: "评分明显领先第二选择。",
    aiAdviceSmallLead: "评分略高于其他选择。",
    aiAdviceCloseScore: "几个选择评分接近，优先采用当前最高分。",
    codemanMemory: "对局记忆",
    codemanReplay: "回放",
    codemanReplayOriginal: "玩家原局",
    codemanReplayCorrected: "AI 修正局",
    codemanReplayTryCorrection: "尝试 AI 修正",
    codemanReplayCorrecting: "修正中...",
    codemanReplayCorrectionNoBranch: "这次没有找到可反败为胜的分支。",
    codemanAiComeback: "AI 反败为胜",
    codemanNoMemory: "还没有这个 Codeman 的对局记忆。",
    codemanDivergence: "分歧点",
    codemanDivergenceHint: "从这里开始，AI 修正局和玩家原局不同：玩家选择「{player}」，AI 选择「{ai}」。",
    codemanReplayPlay: "自动播放",
    codemanReplayPause: "暂停",
    codemanReplayStart: "开局",
    codemanReplayFrame: "局面",
    codemanReplayNoSnapshots: "旧回放没有局面快照。",
    codemanReplayOpenWindow: "新窗口",
    activeEffects: "现有效果",
    blessingDetails: "加护信息",
    blessingSource: "{name} 加护",
    activeMana: "激活 {ready} / {total}",
    battleField: "战场",
    noMinions: "无 Minion",
    noCards: "无卡",
    noGlobalActions: "无全局动作",
    manaPhase: "Mana 阶段",
    placeColorlessMana: "配置无色 Mana",
    effectTargetHint: "在画面中央选择查看的卡牌或效果目标。",
    selectForMulligan: "选入调度",
    revealFromDeck: "从卡组公开",
    revealFromTopCards: "从卡组上方公开",
    inspectTopCards: "查看卡组上方",
    chooseEffectTarget: "选择效果目标",
    variableTargetNote: "按顺序选择 {min}-{max} 个效果目标，然后按确定。",
    multiTargetNote: "选择 {selected}/{max} 个效果目标，然后按确定。",
    inspectTopCardsNote: "查看卡组上方 {count} 张。可以加入手牌的卡会高亮。",
    lookTop3MagicNote: "查看卡组上方 3 张，仅选择要公开并加入手牌的魔法卡。",
    addNoMagicCards: "不加入魔法卡",
    finishInspect: "查看完成",
    deckBaseNote: "从卡组中选择可选数量的 Base Minion，公开后放入费用区。",
    oneTargetNote: "选择一个效果目标。",
    deckTopOrBottomNote: "查看自己的卡组顶牌，然后选择放回牌顶或牌底。",
    deckTopChoice: "放回牌顶",
    deckBottomChoice: "放回牌底",
    chooseFieldReplacement: "选择场上替换对象",
    fieldReplacementNote: "选择一只己方场上的 Minion 送入 Trash，然后召唤这张卡。",
    fieldReplacementNoteMove: "选择一只己方场上的 Minion 送入 Trash，然后将这张卡移动到战场。",
    chooseBaseReplacement: "选择费用区替换对象",
    baseReplacementNotePlay: "选择一张费用区卡送入 Trash，然后配置这张卡。",
    baseReplacementNoteMove: "选择一张费用区卡送入 Trash，然后移动这张卡。",
    baseReplacementNoteBlessing: "选择一张费用区卡送入 Trash，然后将加護 Mana 以疲劳状态放回费用区。",
    colorlessReplacementNote: "选择一张费用区卡送入 Trash，然后放置无色 Mana。",
    manaPayment: "支付费用",
    paymentCost: "费用 {cost} · {selected}/{required}",
    play: "使用",
    summon: "召唤",
    playMagic: "使用魔法",
    playToBase: "配置到费用区",
    replaceWith: "挤掉 {name}",
    moveToField: "移动到战场",
    moveToBase: "移动到费用区",
    bless: "加护",
    attack: "攻击",
    activateEffect: "发动效果",
    selectAsEffectTarget: "选为效果目标",
    selectAttackTarget: "选为攻击目标",
    block: "阻挡",
    debugFixedBoard: "固定测试场",
    debugGodControl: "上帝视角控制",
    debugForceReplace: "替换 Force",
    debugSetForce: "设置 Force",
    debugSide: "阵营",
    debugZone: "区域",
    debugSearchPlaceholder: "卡牌 ID / 名称 / 文本",
    debugReset: "重置",
    debugAddMana: "+ Mana",
    zoneHand: "手牌",
    zoneBase: "费用区",
    zoneField: "战场",
    zoneTrash: "废弃区",
    zoneDeck: "卡组",
  },
  ja: {
    language: "言語",
    home: "ホーム",
    storyMode: "Story Mode",
    gameLobby: "Game Lobby",
    onlineGame: "Online Game",
    onlineConnect: "接続",
    onlineDisconnect: "切断",
    onlineServerUrl: "サーバー URL",
    onlinePlayerName: "プレイヤー名",
    onlineCreateRoom: "ルーム作成",
    onlineJoinRoom: "ルーム参加",
    onlineRoomCode: "ルームコード",
    onlineReady: "準備完了",
    onlineCancelReady: "準備解除",
    onlineLeaveRoom: "ルーム退出",
    onlineConnectionStatus: "接続状態",
    onlineNetworkRoute: "ネットワーク経路",
    onlineWaitingOpponent: "対戦相手を待っています",
    onlineOpeningChoice: "じゃんけんで先攻を決定",
    onlineOpeningWaiting: "選択済み・相手を待っています",
    onlineOpeningTie: "あいこです。もう一度選択してください",
    rock: "グー",
    paper: "パー",
    scissors: "チョキ",
    onlineSelectDeck: "デッキ選択",
    onlinePlayers: "プレイヤー",
    onlineUnavailable: "オンライン対戦にはデスクトップ版が必要です。",
    onlineReconnecting: "接続が切れました。対戦を復旧しています…",
    onlineDisconnected: "切断中",
    lanGame: "LAN Game",
    lanHost: "LAN ホスト",
    lanStopHost: "ホスト停止",
    lanDiscover: "ルーム検索",
    lanManualAddress: "手動 IP / アドレス",
    lanServerName: "ルーム名",
    lanDiscoveredRooms: "検出したルーム",
    lanNoRooms: "LAN ルームが見つかりません",
    lanHosting: "LAN サーバー",
    lanJoinHint: "もう1台は LAN Game でルーム検索するか、この IP を入力。127.0.0.1 は不可",
    battleReview: "対戦リプレイ",
    first: "先攻",
    second: "後攻",
    train: "トレーニング",
    winner: "勝者",
    drawResult: "引き分け",
    phaseStart: "ターン開始",
    phaseRefresh: "リフレッシュ",
    phaseDraw: "ドロー",
    phaseMana: "マナ",
    phaseMain: "メイン",
    phaseEnd: "ターン終了",
    promptMainAction: "行動を選択",
    promptMulligan: "マリガン",
    promptForceBaseChoice: "ベース・ミニオンを選択",
    codemanMemory: "対戦メモリー",
    codemanReplay: "リプレイ",
    codemanReplayOriginal: "プレイヤーの対局",
    codemanReplayCorrected: "AI修正版",
    codemanReplayTryCorrection: "AI修正を試す",
    codemanReplayCorrecting: "修正中...",
    codemanReplayCorrectionNoBranch: "勝利につながる修正分岐が見つかりませんでした。",
    codemanAiComeback: "AI逆転",
    codemanNoMemory: "このコードマンにはまだ対戦メモリーがありません。",
    codemanDivergence: "分岐点",
    codemanReplayPause: "一時停止",
    codemanReplayPlay: "再生",
    aiTraining: "AI トレーニング",
    replayTraining: "Replay & Training",
    replayTrainingShort: "対戦リプレイ / AI訓練",
    trainingEnvironmentShort: "ローカル訓練環境が必要",
    trainingEnvironmentHint: "Python/プロジェクト依存、tools 訓練スクリプト、local_ai_training 基礎モデルまたは Codeman champion、書き込み可能な data/codeman_ai が必要です。",
    setting: "Setting",
    exit: "Exit",
    comingSoon: "準備中",
    updateAvailable: "新しいバージョン {version} があります",
    updateCurrent: "現在のバージョン {version}",
    viewRelease: "更新を見る",
    startGame: "対戦開始",
    launchMode: "モード",
    modeHumanAi: "対AI",
    modeGod: "神視点",
    modeAiVsAi: "AI vs AI",
    basicSettings: "基本設定",
    developerMode: "開発者モード",
    developerPassword: "開発者パスワード",
    enableDeveloperMode: "開発者モードを有効化",
    disableDeveloperMode: "開発者モードを無効化",
    developerModeEnabled: "開発者モード有効",
    developerModeDisabled: "開発者モード無効",
    reducedMotion: "モーションを減らす",
    bgmSetting: "BGM",
    deckBuilder: "デッキ作成",
    deckBuilderShort: "デッキ",
    playmats: "プレイマット",
    continueDuel: "対戦へ戻る",
    decksCount: "{count} デッキ",
    battle: "対戦",
    quickHumanAi: "すぐ対戦",
    godView: "神視点",
    aiVsAi: "AI vs AI",
    human: "プレイヤー",
    god: "神視点",
    concede: "投了",
    auto: "オート",
    pause: "停止",
    run: "実行",
    step: "ステップ",
    endTurn: "ターン終了",
    pass: "パス",
    keep: "キープ",
    redraw: "引き直し",
    new: "新規",
    gameOver: "ゲーム終了",
    operator: "操作者",
    homeGuideName: "広報AIミーナ",
    homeGuideText: "ルールを確認してから、キャラクター、プレイマット、デッキを選びましょう。",
    openRulebook: "ルールブックを開く",
    savedDecks: "保存したデッキ",
    newDeck: "新規",
    startBattle: "対戦開始",
    startWithDeck: "このデッキで対戦",
    aiPilot: "AI操作",
    editCopy: "コピー編集",
    edit: "編集",
    delete: "削除",
    cardsCount: "{count} 枚",
    empty: "空",
    loading: "読み込み中",
    openingDuel: "対戦画面へ移動中",
    profilePlayer: "自分",
    profileOpponent: "相手",
    playerCodeman: "自分の Codeman",
    opponentCodeman: "相手の Codeman",
    originalAvatar: "標準アバター",
    player: "プレイヤー",
    opponent: "対戦相手",
    diceRollParityRule: "1/3/5: {player}先攻 · 2/4/6: {opponent}先攻",
    playerPlaymat: "自分のプレイマット",
    opponentPlaymat: "相手のプレイマット",
    defaultPlaymat: "標準プレイマット",
    default: "標準",
    back: "戻る",
    opponentAi: "相手 AI",
    deckPlayer: "自分のデッキ",
    deckOpponent: "相手のデッキ",
    clearFilters: "フィルター解除",
    all: "すべて",
    save: "保存",
    aiCompleteDeck: "AI補完",
    playGod: "神視点で対戦",
    aiTest: "AIテスト",
    cards: "カード",
    deck: "デッキ",
    forces: "フォース",
    force: "フォース",
    cost: "コスト",
    search: "検索",
    details: "詳細",
    close: "閉じる",
    active: "アクティブ",
    rested: "レスト",
    destroyed: "破壊済み",
    selected: "選択中",
    confirm: "決定",
    publicReveal: "公開",
    trash: "トラッシュ",
    newestFirst: "新しい順",
    life: "ライフ",
    turn: "ターン",
    activeSide: "アクティブ側",
    log: "ログ",
    battleLog: "バトルログ",
    openBattleLog: "バトルログを開く",
    latestLog: "最新ログ",
    noBattleLog: "ログはありません",
    legacyLogUnavailable: "旧形式の記録にはローカライズ可能な構造化ログがありません。",
    aiAdvicePrefix: "提案",
    aiAdviceThinking: "Codeman が考えています...",
    aiAdviceUnavailable: "AI提案を利用できません。",
    aiAdviceNoPrompt: "現在提案できる操作はありません。",
    aiAdviceUnsupportedPrompt: "現在の選択はAI提案に対応していません。",
    aiAdviceNeedsCodeman: "Codemanを選択するとAI提案を利用できます。",
    aiAdviceNotUserTurn: "現在はプレイヤーの操作タイミングではありません。",
    aiAdviceNoOptions: "提案できる選択肢がありません。",
    aiAdviceBest: "AIの現在評価が最も高い選択です。",
    aiAdviceStrongLead: "2番目の選択より評価が大きく上回っています。",
    aiAdviceSmallLead: "ほかの選択より評価がやや高いです。",
    aiAdviceCloseScore: "複数の選択肢が近い評価のため、最高点を優先します。",
    codemanReplayNoSnapshots: "古いリプレイには盤面スナップショットがありません。",
    codemanDivergenceHint: "ここからAI修正リプレイはプレイヤーの元の手順と分岐します：プレイヤー「{player}」、AI「{ai}」。",
    codemanReplayStart: "開始盤面",
    codemanReplayFrame: "盤面",
    codemanReplayOpenWindow: "別ウィンドウ",
    activeEffects: "適用中の効果",
    blessingDetails: "加護情報",
    blessingSource: "{name} の加護",
    activeMana: "アクティブ {ready} / {total}",
    battleField: "バトルフィールド",
    noMinions: "ミニオンなし",
    noCards: "カードなし",
    noGlobalActions: "全体操作なし",
    manaPhase: "マナフェイズ",
    placeColorlessMana: "無色マナを配置",
    effectTargetHint: "中央の画面で確認したカードまたは効果対象を選択してください。",
    selectForMulligan: "マリガンに選ぶ",
    revealFromDeck: "デッキから公開",
    revealFromTopCards: "上から公開",
    inspectTopCards: "デッキ上から確認",
    chooseEffectTarget: "効果対象を選択",
    variableTargetNote: "{min}-{max} 個の効果対象を順番に選び、決定してください。",
    multiTargetNote: "{selected}/{max} 個の効果対象を選び、決定してください。",
    inspectTopCardsNote: "デッキの上から{count}枚を確認します。手札に加えられるカードが強調表示されます。",
    lookTop3MagicNote: "デッキの上から3枚を確認し、公開して手札に加えるマジックカードを選択します。",
    addNoMagicCards: "マジックカードを加えない",
    finishInspect: "確認完了",
    deckBaseNote: "デッキから任意の数のベース・ミニオンを選び、公開してベースに置きます。",
    oneTargetNote: "効果対象を1つ選択してください。",
    deckTopOrBottomNote: "自分のデッキの一番上を確認し、デッキの上か下に戻します。",
    deckTopChoice: "デッキの上に戻す",
    deckBottomChoice: "デッキの下に戻す",
    chooseFieldReplacement: "フィールドの置き換えを選択",
    fieldReplacementNote: "自分のフィールドのミニオン1体をトラッシュに送り、このカードを召喚します。",
    fieldReplacementNoteMove: "自分のフィールドのミニオン1体をトラッシュに送り、このカードをフィールドに移動します。",
    chooseBaseReplacement: "ベースの置き換えを選択",
    baseReplacementNotePlay: "ベースのカード1枚をトラッシュに送り、このカードを配置します。",
    baseReplacementNoteMove: "ベースのカード1枚をトラッシュに送り、このカードを移動します。",
    baseReplacementNoteBlessing: "ベースのカード1枚をトラッシュに送り、加護マナをレスト状態でベースに戻します。",
    colorlessReplacementNote: "ベースのカード1枚をトラッシュに送り、無色マナを置きます。",
    manaPayment: "マナ支払い",
    paymentCost: "コスト {cost} · {selected}/{required}",
    play: "使用",
    summon: "召喚",
    playMagic: "マジックを使用",
    playToBase: "ベースに配置",
    replaceWith: "{name} と置換",
    moveToField: "フィールドへ移動",
    moveToBase: "ベースへ移動",
    bless: "加護",
    attack: "アタック",
    activateEffect: "効果を発動",
    selectAsEffectTarget: "効果対象に選択",
    selectAttackTarget: "攻撃対象に選択",
    block: "ブロック",
    debugFixedBoard: "固定テスト場",
    debugGodControl: "神視点操作",
    debugForceReplace: "フォース置換",
    debugSetForce: "フォース設定",
    debugSide: "陣営",
    debugZone: "ゾーン",
    debugSearchPlaceholder: "カードID / 名前 / テキスト",
    debugReset: "リセット",
    debugAddMana: "+ マナ",
    zoneHand: "手札",
    zoneBase: "ベース",
    zoneField: "フィールド",
    zoneTrash: "トラッシュ",
    zoneDeck: "デッキ",
  },
  en: {
    language: "Language",
    home: "Home",
    storyMode: "Story Mode",
    gameLobby: "Game Lobby",
    onlineGame: "Online Game",
    onlineConnect: "Connect",
    onlineDisconnect: "Disconnect",
    onlineServerUrl: "Server URL",
    onlinePlayerName: "Player Name",
    onlineCreateRoom: "Create Room",
    onlineJoinRoom: "Join Room",
    onlineRoomCode: "Room Code",
    onlineReady: "Ready",
    onlineCancelReady: "Cancel Ready",
    onlineLeaveRoom: "Leave Room",
    onlineConnectionStatus: "Connection Status",
    onlineNetworkRoute: "Network Route",
    onlineWaitingOpponent: "Waiting for opponent",
    onlineOpeningChoice: "Rock paper scissors decides first player",
    onlineOpeningWaiting: "Choice locked. Waiting for opponent",
    onlineOpeningTie: "Tie. Choose again",
    rock: "Rock",
    paper: "Paper",
    scissors: "Scissors",
    onlineSelectDeck: "Select Deck",
    onlinePlayers: "Players",
    onlineUnavailable: "Online play requires the desktop runtime.",
    onlineReconnecting: "Connection lost. Restoring the match…",
    onlineDisconnected: "Disconnected",
    lanGame: "LAN Game",
    lanHost: "Host LAN Room",
    lanStopHost: "Stop Host",
    lanDiscover: "Discover Rooms",
    lanManualAddress: "Manual IP / Address",
    lanServerName: "Room Name",
    lanDiscoveredRooms: "Discovered Rooms",
    lanNoRooms: "No LAN rooms found",
    lanHosting: "LAN Server",
    lanJoinHint: "On the other PC open LAN Game, search rooms, or type this IP. Do not use 127.0.0.1",
    battleReview: "Battle Review",
    first: "First",
    second: "Second",
    train: "Train",
    winner: "Winner",
    drawResult: "Draw",
    phaseStart: "Turn Start",
    phaseRefresh: "Refresh",
    phaseDraw: "Draw",
    phaseMana: "Mana",
    phaseMain: "Main",
    phaseEnd: "Turn End",
    promptMainAction: "Choose Action",
    promptMulligan: "Mulligan",
    promptForceBaseChoice: "Choose Base Minion",
    aiTraining: "AI Training",
    replayTraining: "Replay & Training",
    replayTrainingShort: "Battle replay / AI training",
    trainingEnvironmentShort: "Requires local training env",
    trainingEnvironmentHint: "Requires local Python/project dependencies, tools training scripts, a local_ai_training base model or Codeman champion, and writable data/codeman_ai.",
    setting: "Setting",
    exit: "Exit",
    comingSoon: "Placeholder",
    updateAvailable: "Version {version} is available",
    updateCurrent: "Current version {version}",
    viewRelease: "View update",
    startGame: "Start Game",
    launchMode: "Mode",
    modeHumanAi: "Human vs AI",
    modeGod: "God View",
    modeAiVsAi: "AI vs AI",
    basicSettings: "Basic Settings",
    developerMode: "Developer Mode",
    developerPassword: "Developer Password",
    enableDeveloperMode: "Enable Developer Mode",
    disableDeveloperMode: "Disable Developer Mode",
    developerModeEnabled: "Developer Mode Enabled",
    developerModeDisabled: "Developer Mode Disabled",
    reducedMotion: "Reduced Motion",
    bgmSetting: "BGM",
    deckBuilder: "Deck Builder",
    deckBuilderShort: "Decks",
    playmats: "Playmats",
    continueDuel: "Resume Duel",
    decksCount: "{count} decks",
    battle: "Duel",
    quickHumanAi: "Quick vs AI",
    godView: "God View",
    aiVsAi: "AI vs AI",
    human: "Human",
    god: "God",
    concede: "Concede",
    auto: "Auto",
    pause: "Pause",
    run: "Run",
    step: "Step",
    endTurn: "End Turn",
    pass: "Pass",
    keep: "Keep",
    redraw: "Redraw",
    new: "New",
    gameOver: "Game Over",
    operator: "Operator",
    homeGuideName: "Publicity AI Mina",
    homeGuideText: "Review the rules, then choose codemen, playmats, and decks for both sides.",
    openRulebook: "Open Rulebook",
    savedDecks: "Saved Decks",
    newDeck: "New",
    startBattle: "Start Duel",
    startWithDeck: "Start with this deck",
    aiPilot: "AI Pilot",
    editCopy: "Edit Copy",
    edit: "Edit",
    delete: "Delete",
    cardsCount: "{count} cards",
    empty: "empty",
    loading: "Loading",
    openingDuel: "Opening duel",
    profilePlayer: "Player",
    profileOpponent: "Opponent",
    playerCodeman: "Player Codeman",
    opponentCodeman: "Opponent Codeman",
    originalAvatar: "Default Avatar",
    player: "Player",
    opponent: "Opponent",
    diceRollParityRule: "1/3/5: {player} first · 2/4/6: {opponent} first",
    playerPlaymat: "Player Playmat",
    opponentPlaymat: "Opponent Playmat",
    defaultPlaymat: "Default Playmat",
    default: "Default",
    back: "Back",
    opponentAi: "Opponent AI",
    deckPlayer: "Player Deck",
    deckOpponent: "Opponent Deck",
    clearFilters: "Clear Filters",
    all: "All",
    save: "Save",
    aiCompleteDeck: "AI Complete",
    playGod: "Play in God View",
    aiTest: "AI Pilot Test",
    cards: "Cards",
    deck: "Deck",
    forces: "Forces",
    force: "Force",
    cost: "Cost",
    search: "Search",
    details: "Details",
    close: "Close",
    active: "active",
    rested: "rested",
    destroyed: "destroyed",
    selected: "selected",
    confirm: "Confirm",
    publicReveal: "Reveal",
    trash: "Trash",
    newestFirst: "newest first",
    life: "Life",
    turn: "Turn",
    activeSide: "Active",
    log: "Log",
    battleLog: "Battle Log",
    openBattleLog: "Open battle log",
    latestLog: "Latest log",
    noBattleLog: "No battle log yet",
    legacyLogUnavailable: "This legacy record has no structured localizable log.",
    aiAdvicePrefix: "Advice",
    aiAdviceThinking: "Codeman is thinking...",
    aiAdviceUnavailable: "AI advice unavailable.",
    aiAdviceNoPrompt: "No action needs advice right now.",
    aiAdviceUnsupportedPrompt: "AI advice does not support this choice yet.",
    aiAdviceNeedsCodeman: "Select a Codeman to enable AI advice.",
    aiAdviceNotUserTurn: "This is not the player's action timing.",
    aiAdviceNoOptions: "There are no options to advise on.",
    aiAdviceBest: "This is the AI's highest-scored choice.",
    aiAdviceStrongLead: "Its score is clearly ahead of the second choice.",
    aiAdviceSmallLead: "Its score is slightly higher than the other choices.",
    aiAdviceCloseScore: "Several choices are close, so the top score is preferred.",
    codemanMemory: "Match Memory",
    codemanReplay: "Replay",
    codemanReplayOriginal: "Player Game",
    codemanReplayCorrected: "AI Corrected",
    codemanReplayTryCorrection: "Try AI Correction",
    codemanReplayCorrecting: "Correcting...",
    codemanReplayCorrectionNoBranch: "No winning correction branch found this time.",
    codemanAiComeback: "AI comeback",
    codemanNoMemory: "No match memory for this Codeman yet.",
    codemanDivergence: "Divergence",
    codemanDivergenceHint: "From here, the AI-corrected game diverges from the player's original line: player chose “{player}”, AI chose “{ai}”.",
    codemanReplayPlay: "Autoplay",
    codemanReplayPause: "Pause",
    codemanReplayStart: "Opening board",
    codemanReplayFrame: "Board state",
    codemanReplayNoSnapshots: "This older replay has no board snapshots.",
    codemanReplayOpenWindow: "New window",
    activeEffects: "Active effects",
    blessingDetails: "Blessings",
    blessingSource: "Blessed by {name}",
    activeMana: "Active {ready} / {total}",
    battleField: "Battle Field",
    noMinions: "No minions",
    noCards: "No cards",
    noGlobalActions: "No global actions",
    manaPhase: "Mana phase",
    placeColorlessMana: "Place colorless Mana",
    effectTargetHint: "Choose inspected cards or effect targets in the center panel.",
    selectForMulligan: "Select for mulligan",
    revealFromDeck: "Reveal from deck",
    revealFromTopCards: "Reveal from top cards",
    inspectTopCards: "Inspect top cards",
    chooseEffectTarget: "Choose effect target",
    variableTargetNote: "Choose {min}-{max} effect targets in order, then confirm.",
    multiTargetNote: "Choose {selected}/{max} effect targets, then confirm.",
    inspectTopCardsNote: "Inspect the top {count} cards of the deck. Eligible cards are highlighted.",
    lookTop3MagicNote: "Inspect the top 3 cards. Choose which Magic cards to reveal and add to hand.",
    addNoMagicCards: "Add no Magic cards",
    finishInspect: "Done inspecting",
    deckBaseNote: "Choose up to the allowed number of Base Minions from the deck, reveal them, and put them into base.",
    oneTargetNote: "Choose one effect target.",
    deckTopOrBottomNote: "Inspect the top card of your deck, then return it to the top or bottom.",
    deckTopChoice: "Return to deck top",
    deckBottomChoice: "Return to deck bottom",
    chooseFieldReplacement: "Choose field replacement",
    fieldReplacementNote: "Send one allied field Minion to Trash, then summon this card.",
    fieldReplacementNoteMove: "Send one allied field Minion to Trash, then move this card to the field.",
    chooseBaseReplacement: "Choose base replacement",
    baseReplacementNotePlay: "Send one base card to Trash, then place this card.",
    baseReplacementNoteMove: "Send one base card to Trash, then move this card.",
    baseReplacementNoteBlessing: "Send one base card to Trash, then return the Bless mana to the base Rested.",
    colorlessReplacementNote: "Send one base card to Trash, then place colorless Mana.",
    manaPayment: "Mana payment",
    paymentCost: "Cost {cost} · {selected}/{required}",
    play: "Play",
    summon: "Summon",
    playMagic: "Play Magic",
    playToBase: "Place to Base",
    replaceWith: "replace {name}",
    moveToField: "Move to Field",
    moveToBase: "Move to Base",
    bless: "Bless",
    attack: "Attack",
    activateEffect: "Activate Effect",
    selectAsEffectTarget: "Select as Effect Target",
    selectAttackTarget: "Select as Attack Target",
    block: "Block",
    debugFixedBoard: "Fixed test board",
    debugGodControl: "God control",
    debugForceReplace: "Force replace",
    debugSetForce: "Set Force",
    debugSide: "Side",
    debugZone: "Zone",
    debugSearchPlaceholder: "card id / name / text",
    debugReset: "Reset",
    debugAddMana: "+ Mana",
    zoneHand: "Hand",
    zoneBase: "Base",
    zoneField: "Field",
    zoneTrash: "Trash",
    zoneDeck: "Deck",
  },
};

const ACTIVE_EFFECT_COPY = {
  zh: {
    turn_stat_modifier: "本回合能力修正",
    permanent_stat_modifier: "永久能力修正",
    keyword_modifier: "获得关键字",
    action_lock: "不能攻击、阻挡或移动",
    magic_selection_immunity: "不能被对手的 Magic 选为对象",
    battle_auto_win: "战斗时不比较 BP，直接获胜",
    cannot_attack: "本回合不能攻击",
    must_block: "本回合必须阻挡",
    must_be_blocked: "攻击时必须被阻挡",
    unblockable_by_cost_at_most_3: "不能被费用 3 以下的 Minion 阻挡",
    forced_blocker: "必须由指定 Minion 阻挡",
    skip_next_refresh: "下次 Refresh 时不能激活",
    force_passive: "Force 持续效果",
    turn_stat_aura: "本回合持续修正",
    card_aura: "卡牌持续效果",
    keyword_aura: "获得持续关键字",
    next_red_minion_rush: "本回合下一只红色 Minion 获得[袭击]",
    opponent_magic_cost_increase: "本回合 Magic 费用增加 3",
    battle_win_damage: "本回合战斗获胜时对敌方 Player 和 Force 造成伤害",
    hunter_must_be_blocked: "Hunter 攻击时必须被阻挡",
    return_enemy_damager: "本回合受到敌方 Minion 伤害后将其返回手牌",
    next_blue_magic_free: "本回合下一张蓝色 Magic 费用变为 0",
    draw_on_enemy_destroy: "本回合敌方 Minion 被破坏时抽 1 张卡",
    damage_reduction_blocked: "不能回复生命或减轻伤害",
    prevent_player_damage: "Player 伤害减轻",
    player_damage_reduction: "Player 伤害减轻",
    prevent_force_damage: "Force 伤害减轻",
    damage: "伤害",
    opponent_turn: "对手回合",
    enemy_minion_dp: "敌方 Minion 的 DP 伤害",
  },
  ja: {
    turn_stat_modifier: "このターンの能力修正",
    permanent_stat_modifier: "永続能力修正",
    keyword_modifier: "付与キーワード",
    action_lock: "アタック・ブロック・移動不可",
    magic_selection_immunity: "相手のマジックの効果で選択されない",
    battle_auto_win: "BPに関係なくバトルに勝利する",
    cannot_attack: "このターン、アタックできない",
    must_block: "このターン、必ずブロックする",
    must_be_blocked: "アタック時、必ずブロックされる",
    unblockable_by_cost_at_most_3: "コスト3以下のミニオンにブロックされない",
    forced_blocker: "指定されたミニオンが必ずブロックする",
    skip_next_refresh: "次のリフレッシュでアクティブにならない",
    force_passive: "フォース常時効果",
    turn_stat_aura: "このターンの継続修正",
    card_aura: "カードの常時効果",
    keyword_aura: "常時付与キーワード",
    next_red_minion_rush: "このターン、次の赤のミニオンに[襲撃]を付与",
    opponent_magic_cost_increase: "このターン、マジックのコストを3増やす",
    battle_win_damage: "このターン、バトル勝利時に相手プレイヤーとフォースへダメージ",
    hunter_must_be_blocked: "ハンターのアタックは必ずブロックされる",
    return_enemy_damager: "このターン、敵ミニオンからダメージを受けた後、そのミニオンを手札に戻す",
    next_blue_magic_free: "このターン、次の青のマジックのコストは0",
    draw_on_enemy_destroy: "このターン、相手のミニオンが破壊された時に1枚ドロー",
    damage_reduction_blocked: "ライフ回復とダメージ軽減ができない",
    prevent_player_damage: "プレイヤーダメージ軽減",
    player_damage_reduction: "プレイヤーダメージ軽減",
    prevent_force_damage: "フォースダメージ軽減",
    damage: "ダメージ",
    opponent_turn: "相手のターン",
    enemy_minion_dp: "相手ミニオンのDPダメージ",
  },
  en: {
    turn_stat_modifier: "Turn stat modifier",
    permanent_stat_modifier: "Permanent stat modifier",
    keyword_modifier: "Granted keyword",
    action_lock: "Cannot attack, block, or move",
    magic_selection_immunity: "Cannot be selected by opposing Magic effects",
    battle_auto_win: "Wins battles regardless of BP",
    cannot_attack: "Cannot attack this turn",
    must_block: "Must block this turn",
    must_be_blocked: "Must be blocked when attacking",
    unblockable_by_cost_at_most_3: "Cannot be blocked by Minions costing 3 or less",
    forced_blocker: "Must be blocked by the selected Minion",
    skip_next_refresh: "Does not become Active during the next Refresh",
    force_passive: "Force passive effect",
    turn_stat_aura: "Turn-long stat effect",
    card_aura: "Card passive effect",
    keyword_aura: "Granted passive keyword",
    next_red_minion_rush: "The next Red Minion this turn gains Charge",
    opponent_magic_cost_increase: "Magic costs 3 more this turn",
    battle_win_damage: "Battle wins this turn damage the opposing Player and Forces",
    hunter_must_be_blocked: "Hunter attacks must be blocked",
    return_enemy_damager: "After an enemy Minion deals damage this turn, return it to hand",
    next_blue_magic_free: "The next Blue Magic this turn costs 0",
    draw_on_enemy_destroy: "Draw 1 when an enemy Minion is destroyed this turn",
    damage_reduction_blocked: "Life cannot be restored and damage cannot be reduced",
    prevent_player_damage: "Player damage reduction",
    player_damage_reduction: "Player damage reduction",
    prevent_force_damage: "Force damage reduction",
    damage: "Damage",
    opponent_turn: "opponent turn",
    enemy_minion_dp: "enemy Minion DP damage",
  },
};

const KEYWORD_COPY = {
  zh: {
    REAWAKEN: "再起", RUSH: "袭击", REACTIVE: "Reactive", PENETRATE: "贯通",
    FLYING: "飞来", SNEAKING: "潜入", DEATH_BLOW: "夺命", COOPERATION: "协力",
    BLESS: "加护", COST_REDUCTION: "费用减免", CANNOT_BLOCK: "不能阻挡",
    KAGO: "加护", UNBLOCKABLE: "不能被阻挡",
  },
  ja: {
    REAWAKEN: "再起", RUSH: "襲撃", REACTIVE: "リアクティブ", PENETRATE: "貫通",
    FLYING: "飛来", SNEAKING: "潜入", DEATH_BLOW: "奪命", COOPERATION: "協力",
    BLESS: "加護", COST_REDUCTION: "コスト軽減", CANNOT_BLOCK: "ブロックできない",
    KAGO: "加護", UNBLOCKABLE: "ブロックされない",
  },
  en: {
    REAWAKEN: "Resurge", RUSH: "Charge", REACTIVE: "Reactive", PENETRATE: "Pierce",
    FLYING: "Flying", SNEAKING: "Infiltrate", DEATH_BLOW: "Revenge", COOPERATION: "Cooperation",
    BLESS: "Boost", COST_REDUCTION: "Cost Reduction", CANNOT_BLOCK: "Cannot Block",
    KAGO: "Boost", UNBLOCKABLE: "Unblockable",
  },
};

const LOG_ACTION_LABELS = {
  zh: {
    play_card: "使用",
    play_to_base: "配置到 Base",
    place_colorless_mana: "配置无色 Mana",
    skip_mana: "不放置 Mana",
    end_turn: "回合结束",
    move_card: "移动",
    attack: "攻击",
    flash_pass: "Pass",
    activate_flash_ability: "发动 Reactive",
    swap_mana_color: "变更 Mana 颜色",
  },
  ja: {
    play_card: "使用",
    play_to_base: "ベースに配置",
    place_colorless_mana: "無色マナを配置",
    skip_mana: "マナ配置なし",
    end_turn: "ターン終了",
    move_card: "移動",
    attack: "攻撃",
    flash_pass: "Pass",
    activate_flash_ability: "リアクティブ使用",
    swap_mana_color: "マナ色変更",
  },
  en: {
    play_card: "plays",
    play_to_base: "places to Base",
    place_colorless_mana: "places colorless Mana",
    skip_mana: "skips Mana",
    end_turn: "ends turn",
    move_card: "moves",
    attack: "attacks",
    flash_pass: "passes",
    activate_flash_ability: "uses Reactive",
    swap_mana_color: "changes Mana color",
  },
};

const LOG_EVENT_LABELS = {
  zh: {
    block: "防御",
    noBlock: "不防御",
    forcePlaced: "放置",
    reveal: "公开",
    targetSelected: "选择了效果对象",
    usedOptional: "使用了可选效果",
    skippedOptional: "跳过了可选效果",
    gameOver: "游戏结束",
    replace: "替换",
  },
  ja: {
    block: "ブロック",
    noBlock: "ブロックしない",
    forcePlaced: "配置",
    reveal: "公開",
    targetSelected: "効果対象を選択",
    usedOptional: "任意効果を使用",
    skippedOptional: "任意効果をスキップ",
    gameOver: "ゲーム終了",
    replace: "置換",
  },
  en: {
    block: "blocks with",
    noBlock: "no block",
    forcePlaced: "places",
    reveal: "reveals",
    targetSelected: "selected effect target",
    usedOptional: "used optional effect",
    skippedOptional: "skipped optional effect",
    gameOver: "Game over",
    replace: "replaces",
  },
};

function createEmptyDeckEditor() {
  return {
    id: null,
    name: "New Deck",
    recipe: {},
    selectedForceIds: [],
    search: "",
    filters: {},
  };
}

function syncUiStateFromCurrentState() {
  syncMulliganSelection();
  syncPaymentSelection();
  syncFieldReplaceSelection();
  syncBaseReplaceSelection();
  syncColorlessBaseReplaceSelection();
  syncEffectTargetSelection();
  syncAiAdvice();
}

function shouldHoldStateForAnimationEvents(previousState, nextState, events) {
  if (!previousState || !nextState || previousState === nextState || !events || !events.length) return false;
  return events.some((event) => animationEventNeedsHeldState(event));
}

function cloneVisualState(value) {
  if (!value) return value;
  if (typeof structuredClone === "function") return structuredClone(value);
  return JSON.parse(JSON.stringify(value));
}

function playerBySideFromState(sourceState, side) {
  const players = sourceState && sourceState.players;
  if (!players || !side) return null;
  return Object.values(players).find((player) => player && player.side === side) || null;
}

function preservePreSettlementLifeTotals(previousState, stagedState, events) {
  const shouldPreserveLife = (events || []).some((event) => (
    event && ["damage", "heal"].includes(event.type)
  ));
  if (!shouldPreserveLife || !previousState || !stagedState || !stagedState.players) {
    return stagedState;
  }
  Object.values(stagedState.players).forEach((player) => {
    const previousPlayer = playerBySideFromState(previousState, player && player.side);
    if (!player || !previousPlayer) return;
    player.life = previousPlayer.life;
    const previousForces = previousPlayer.forces || [];
    (player.forces || []).forEach((force, index) => {
      const previousForce = previousForces[index];
      if (!previousForce) return;
      force.life = previousForce.life;
      force.destroyed = previousForce.destroyed;
    });
  });
  return stagedState;
}

function pendingVisualEvents() {
  return [activeAnimationEvent, ...animationEventQueue].filter(Boolean);
}

function animationEventNeedsHeldState(event) {
  if (!event) return false;
  return ["attack", "block", "damage", "heal", "destroy", "zone_move", "effect", "draw", "effect_target"].includes(event.type);
}

function animationEventSettlesVisualState(event) {
  return Boolean(event && ["zone_move", "draw"].includes(event.type));
}

function zoneMoveSourceKey(iid, area) {
  return `${String(iid || "")}:${String(area || "")}`;
}

function rememberZoneMoveSource(event) {
  if (!event || event.type !== "zone_move" || event.fromArea === "deck") return;
  const card = event.card || {};
  if (!card.iid || !event.fromArea) return;
  hiddenZoneMoveSourceKeys.add(zoneMoveSourceKey(card.iid, event.fromArea));
}

function promptWaitsForVisualSetup(prompt) {
  if (!prompt) return false;
  return ["effect_target", "optional_effect"].includes(prompt.kind);
}

function animationEventBlocksPrompt(event, prompt = rawActivePrompt()) {
  if (!event) return false;
  if (promptWaitsForVisualSetup(prompt) && animationEventNeedsHeldState(event)) return true;
  return ["dice_roll", "rock_paper_scissors", "effect", "game_result"].includes(event.type);
}

function promptBlockedByAnimation(prompt = rawActivePrompt()) {
  if (replayReadonlyMode) return false;
  return pendingVisualEvents().some((event) => animationEventBlocksPrompt(event, prompt));
}

function pendingVisualStateStillNeeded() {
  if (!pendingVisualState) return false;
  if (visualStateStaged) return false;
  return pendingVisualEvents().some((event) => animationEventNeedsHeldState(event));
}

function commitPendingVisualStateIfSettled() {
  if (!pendingVisualState || pendingVisualStateStillNeeded()) return false;
  return commitPendingVisualState({ rerender: false });
}

function deckVisualTier(count) {
  const size = Number(count || 0);
  if (size <= 0) return "empty";
  if (size <= 10) return "low";
  if (size <= 30) return "mid";
  return "many";
}

function playerAreaCards(player, area) {
  if (!player) return null;
  if (area === "hand") return player.hand || (player.hand = []);
  if (area === "field") return player.field || (player.field = []);
  if (area === "base") return player.base || (player.base = []);
  if (area === "trash") return player.trash || (player.trash = []);
  return null;
}

function playerAreaCardsFromState(sourceState, side, area) {
  const player = playerBySideFromState(sourceState, side);
  return playerAreaCards(player, area) || [];
}

function pendingVisualCard(event, area) {
  const card = event && event.card ? event.card : {};
  if (!card.iid || !pendingVisualState || !pendingVisualState.state) return card;
  const pendingCards = playerAreaCardsFromState(pendingVisualState.state, event.side, area);
  return pendingCards.find((item) => String(item.iid || "") === String(card.iid || "")) || card;
}

function refreshPlayerZoneCounts(player) {
  if (!player) return;
  player.handCount = (player.hand || []).length;
  player.trashCount = (player.trash || []).length;
  player.deckCount = Math.max(0, Number(player.deckCount || 0));
  player.deckVisualTier = deckVisualTier(player.deckCount);
  const colors = {};
  let ready = 0;
  (player.base || []).forEach((card) => {
    const color = card.manaColor || "COLORLESS";
    colors[color] = (colors[color] || 0) + 1;
    if (!card.rested) ready += 1;
  });
  player.baseSummary = {
    total: (player.base || []).length,
    ready,
    colors,
  };
}

function removeVisualCardFromArea(player, area, iid) {
  if (!player || !area) return null;
  if (area === "deck") {
    player.deckCount = Math.max(0, Number(player.deckCount || 0) - 1);
    return null;
  }
  const cards = playerAreaCards(player, area);
  if (!cards) return null;
  const index = cards.findIndex((card) => String(card.iid || "") === String(iid || ""));
  if (index < 0) return null;
  return cards.splice(index, 1)[0];
}

function addVisualCardToArea(player, area, card) {
  if (!player || !area || !card) return false;
  if (area === "deck") {
    player.deckCount = Math.max(0, Number(player.deckCount || 0) + 1);
    return true;
  }
  const cards = playerAreaCards(player, area);
  if (!cards) return false;
  const iid = card.iid;
  if (cards.some((item) => String(item.iid || "") === String(iid || ""))) return false;
  cards.push({ ...card, ownerSide: card.ownerSide || player.side, area });
  return true;
}

function settleZoneMoveVisualState(event) {
  if (!state || !pendingVisualState || visualStateStaged || !event || event.type !== "zone_move") return false;
  const card = event.card || {};
  const player = findPlayerBySide(event.side || card.ownerSide);
  if (!player || !card.iid) return false;
  removeVisualCardFromArea(player, event.fromArea, card.iid);
  addVisualCardToArea(player, event.toArea, pendingVisualCard(event, event.toArea));
  refreshPlayerZoneCounts(player);
  syncUiStateFromCurrentState();
  return true;
}

function settleDrawVisualState(event) {
  if (!state || !pendingVisualState || visualStateStaged || !event || event.type !== "draw") return false;
  const player = findPlayerBySide(event.side);
  if (!player) return false;
  const cards = Array.isArray(event.cards) && event.cards.length ? event.cards : [];
  const count = Math.max(cards.length, Number(event.count || 0));
  for (let index = 0; index < count; index += 1) {
    const card = cards[index];
    removeVisualCardFromArea(player, "deck", card && card.iid);
    if (card) {
      addVisualCardToArea(player, "hand", pendingVisualCard({ ...event, card }, "hand"));
    }
  }
  refreshPlayerZoneCounts(player);
  syncUiStateFromCurrentState();
  return count > 0;
}

function settleFinishedAnimationEvent(event) {
  if (!animationEventSettlesVisualState(event)) return false;
  if (event.type === "zone_move") return settleZoneMoveVisualState(event);
  if (event.type === "draw") return settleDrawVisualState(event);
  return false;
}

function stagePendingVisualStateForEffect() {
  if (!pendingVisualState || visualStateStaged) return false;
  if (pendingVisualEvents().some((event) => event !== activeAnimationEvent && animationEventSettlesVisualState(event))) {
    return false;
  }
  const stagedState = preservePreSettlementLifeTotals(
    state,
    cloneVisualState(pendingVisualState.state),
    pendingVisualEvents()
  );
  state = stagedState;
  visualStateStaged = true;
  syncUiStateFromCurrentState();
  return true;
}

function commitPendingVisualState({ rerender = true } = {}) {
  if (!pendingVisualState) return false;
  const next = pendingVisualState;
  pendingVisualState = null;
  visualStateStaged = false;
  hiddenZoneMoveSourceKeys.clear();
  state = next.state;
  syncUiStateFromCurrentState();
  activatePublicRevealIfIdle();
  if (rerender) render(next.error || (state && state.error));
  if (!hasBlockingAutoVisuals()) scheduleAutoStep(AI_AUTO_VISUAL_POLL_MS);
  return true;
}

function stageDuelState(nextState, nextError = null) {
  const previousState = state;
  const animationEvents = (nextState && nextState.animationEvents) || [];
  const holdPreviousState = shouldHoldStateForAnimationEvents(previousState, nextState, animationEvents);
  if (holdPreviousState) {
    pendingVisualState = { state: nextState, error: nextError };
    visualStateStaged = false;
    state = previousState;
  } else {
    pendingVisualState = null;
    visualStateStaged = false;
    state = nextState;
  }
  enqueueAnimationEvents(animationEvents);
  enqueuePublicReveals((nextState && nextState.publicReveals) || []);
  syncUiStateFromCurrentState();
}

function api(path, body = null) {
  commitPendingVisualState({ rerender: false });
  return ZZApi.request(path, body).then((payload) => {
    const nextState = payload.state || state;
    const nextError = payload.error || (nextState && nextState.error);
    stageDuelState(nextState, nextError);
    render(nextError);
    if (!hasBlockingAutoVisuals()) scheduleAutoStep(AI_AUTO_VISUAL_POLL_MS);
    return payload;
  });
}

function esc(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

async function loadCatalog() {
  const payload = await ZZApi.request("/api/catalog");
  if (payload.ok) {
    catalog = payload;
    if (multiplayerUi.view) hydrateMultiplayerViewAssets(multiplayerUi.view);
  }
  render();
}

async function loadSavedDecks() {
  const payload = await ZZApi.request("/api/decks");
  if (payload.ok) {
    savedDecks = payload.decks || [];
  }
  render(payload.error || null);
}

async function loadSettings() {
  const payload = await ZZApi.request("/api/settings");
  if (payload.ok) {
    settings = normalizeSettings(payload.settings || {});
  }
  render(payload.error || null);
}

async function saveSettings() {
  const payload = await ZZApi.request("/api/settings", settings);
  if (payload.ok) {
    settings = normalizeSettings(payload.settings || {});
  }
  render(payload.error || null);
}

function deckTotal(recipe = deckEditor.recipe) {
  return Object.values(recipe || {}).reduce((sum, count) => sum + Number(count || 0), 0);
}

function deckIsValid(deck = deckEditor) {
  return deckTotal(deck.recipe) === 40 &&
    deck.selectedForceIds.length === 2 &&
    new Set(deck.selectedForceIds).size === 2;
}

function deckCanAiComplete(deck = deckEditor) {
  const total = deckTotal(deck.recipe);
  return total >= 15 &&
    total < 40 &&
    deck.selectedForceIds.length === 2 &&
    new Set(deck.selectedForceIds).size === 2;
}

function deckCardMaxCopies(cardId) {
  const card = cardById(cardId);
  return Number((card && card.maxCopies) || 3);
}

function canAddDeckCard(cardId) {
  const count = deckEditor.recipe[cardId] || 0;
  if (deckTotal() >= 40) return false;
  if (count >= deckCardMaxCopies(cardId)) return false;
  return true;
}

function cardById(cardId) {
  return catalog.cards.find((card) => card.id === cardId) || null;
}

function forceById(forceId) {
  return catalog.forces.find((force) => force.id === forceId) || null;
}

function normalizeProfile(profile = {}) {
  return {
    codemanId: profile && profile.codemanId ? String(profile.codemanId) : null,
    playmatId: profile && profile.playmatId ? String(profile.playmatId) : null,
  };
}

function normalizeOpponentAiDifficulty(value) {
  return ["easy", "normal", "deep"].includes(value) ? value : "deep";
}

function normalizeUiLanguage(value) {
  const language = String(value || "zh").toLowerCase();
  return LANGUAGES.some((item) => item.id === language) ? language : "zh";
}

function normalizeBgmTrack(value) {
  const track = String(value || "bgm_01").toLowerCase();
  return BGM_TRACKS.some((item) => item.id === track) ? track : "bgm_01";
}

function selectedBgmTrack() {
  const trackId = normalizeBgmTrack(settings.bgmTrack);
  return BGM_TRACKS.find((item) => item.id === trackId) || BGM_TRACKS[0];
}

function normalizeBool(value) {
  if (typeof value === "boolean") return value;
  if (typeof value === "number") return value !== 0;
  return ["1", "true", "yes", "on"].includes(String(value || "").trim().toLowerCase());
}

function currentLanguage() {
  return normalizeUiLanguage(settings && settings.uiLanguage);
}

function t(key, params = {}) {
  const lang = currentLanguage();
  const table = UI_TEXT[lang] || UI_TEXT.zh;
  const fallback = UI_TEXT.zh || {};
  let text = table[key] || fallback[key] || key;
  for (const [name, value] of Object.entries(params || {})) {
    text = text.replaceAll(`{${name}}`, String(value));
  }
  return text;
}

function localizedName(item, fallback = "") {
  if (!item) return fallback;
  const lang = currentLanguage();
  const neutralFallback = item.id || item.cardId || item.forceId || fallback;
  if (lang === "zh") return item.nameZh || neutralFallback;
  if (lang === "en") return item.nameEn || neutralFallback;
  return item.nameJp || fallback;
}

function localizedAbility(item) {
  if (!item) return "";
  const lang = currentLanguage();
  if (lang === "zh") return item.abilityZh || "";
  if (lang === "en") return item.abilityEn || "";
  return item.abilityJp || "";
}

function localAssetUrl(assetId) {
  return assetId ? `/assets/${encodeURIComponent(assetId)}` : null;
}

function localizedCardAssetUrl(card) {
  if (card && currentLanguage() === "en" && card.assetUrlEn) return card.assetUrlEn;
  return card && card.assetUrl ? card.assetUrl : null;
}

function localizedForceAssetUrl(force) {
  if (force && currentLanguage() === "en" && force.assetUrlEn) return force.assetUrlEn;
  return force && force.assetUrl ? force.assetUrl : null;
}

function hydrateMultiplayerViewAssets(view) {
  if (!view || typeof view !== "object") return view;
  const cardsById = new Map((catalog.cards || []).map((card) => [card.id, card]));
  const forcesById = new Map((catalog.forces || []).map((force) => [force.id, force]));
  const fillCardUrls = (card) => {
    if (!card || typeof card !== "object") return;
    if (card.faceDown) {
      card.assetId = "card_back";
      card.assetUrl = localAssetUrl("card_back");
      return;
    }
    if (card.type === "mana_token") {
      const manaUrl = (catalog.manaAssets || {})[card.manaColor]
        || localAssetUrl(card.manaColor ? `mana:${card.manaColor}` : null);
      card.assetUrl = manaUrl;
      card.assetUrlEn = manaUrl;
      return;
    }
    const localCard = cardsById.get(card.cardId || card.assetId);
    const assetId = card.assetId || card.cardId;
    card.assetUrl = (localCard && localCard.assetUrl) || localAssetUrl(assetId);
    card.assetUrlEn = (localCard && localCard.assetUrlEn) || card.assetUrl;
  };
  const fillForceUrls = (force) => {
    if (!force || typeof force !== "object") return;
    const localForce = forcesById.get(force.forceId || force.id || force.assetId);
    const assetId = force.assetId || force.forceId || force.id;
    force.assetUrl = (localForce && localForce.assetUrl) || localAssetUrl(assetId);
    force.assetUrlEn = (localForce && localForce.assetUrlEn) || force.assetUrl;
  };
  const visit = (value) => {
    if (!value || typeof value !== "object") return;
    if (Array.isArray(value)) {
      value.forEach(visit);
      return;
    }
    if (value.forceId || value.type === "force" || value.type === "force_ability") {
      fillForceUrls(value);
    } else if (value.cardId || value.type === "mana_token" || Object.prototype.hasOwnProperty.call(value, "faceDown")) {
      fillCardUrls(value);
    }
    Object.values(value).forEach(visit);
  };
  visit(view);
  Object.values(view.players || {}).forEach((player) => {
    (player.forces || []).forEach(fillForceUrls);
    const profile = player.profile || {};
    const codeman = characterById(profile.codemanId);
    const playmat = playmatById(profile.playmatId);
    profile.codeman = codeman || null;
    profile.playmatUrl = playmat ? playmat.assetUrl : null;
    player.profile = profile;
  });
  return view;
}

function forceTitle(force) {
  if (force && currentLanguage() === "zh") return force.nameZh || force.id || "Force";
  if (force && currentLanguage() === "en") return force.nameEn || force.id || "Force";
  return localizedName(force, (force && force.id) || "Force");
}

function forceAbilityText(force) {
  return localizedAbility(force);
}

function characterTitle(character) {
  return localizedName(character, (character && character.id) || "");
}

function characterCatchphrase(character) {
  if (!character) return "";
  const lang = currentLanguage();
  if (lang === "zh") return character.catchphraseZh || character.role || "";
  if (lang === "en") return character.catchphraseEn || character.role || "";
  return character.catchphraseJp || character.role || "";
}

function rulebookUrl() {
  return `/rules/${currentLanguage()}`;
}

function renderLanguageSwitch() {
  return `
    <label class="language-switch">
      <span>${esc(t("language"))}</span>
      <select data-ui-language aria-label="${esc(t("language"))}">
        ${LANGUAGES.map((language) => `
          <option value="${esc(language.id)}" ${language.id === currentLanguage() ? "selected" : ""}>
            ${esc(language.label)}
          </option>
        `).join("")}
      </select>
    </label>
  `;
}

function renderBgmTrackPicker() {
  const selected = selectedBgmTrack().id;
  return `
    <label class="bgm-track-picker">
      <span>${esc(t("bgmSetting"))}</span>
      <select data-bgm-track aria-label="${esc(t("bgmSetting"))}">
        ${BGM_TRACKS.map((track) => `
          <option value="${esc(track.id)}" ${track.id === selected ? "selected" : ""}>
            ${esc(track.label)}
          </option>
        `).join("")}
      </select>
    </label>
  `;
}

function renderTopbarBgmControl() {
  const selected = selectedBgmTrack().id;
  return `
    <div class="topbar-bgm-control">
      <span class="topbar-bgm-label">${esc(t("bgmSetting"))}</span>
      <select data-bgm-track aria-label="${esc(t("bgmSetting"))}">
        ${BGM_TRACKS.map((track) => `
          <option value="${esc(track.id)}" ${track.id === selected ? "selected" : ""}>
            ${esc(track.label)}
          </option>
        `).join("")}
      </select>
      <button class="bgm-toggle ${bgmPlaying ? "active" : ""}" data-bgm-toggle
              title="${esc(bgmError || selectedBgmTrack().label)}">${bgmPlaying ? "BGM On" : "BGM"}</button>
    </div>
  `;
}

function normalizeSettings(raw = {}) {
  return {
    playerProfile: normalizeProfile(raw.playerProfile),
    opponentProfile: normalizeProfile(raw.opponentProfile),
    opponentAiDifficulty: normalizeOpponentAiDifficulty(raw.opponentAiDifficulty),
    uiLanguage: normalizeUiLanguage(raw.uiLanguage),
    bgmTrack: normalizeBgmTrack(raw.bgmTrack),
    developerMode: normalizeBool(raw.developerMode),
    reducedMotion: normalizeBool(raw.reducedMotion),
  };
}

function opponentAiDifficultyPayload() {
  return {
    opponentAiDifficulty: normalizeOpponentAiDifficulty(settings.opponentAiDifficulty),
  };
}

function setUiLanguage(language) {
  settings = {
    ...normalizeSettings(settings),
    uiLanguage: normalizeUiLanguage(language),
  };
  render();
  saveSettings();
}

function profilePayload() {
  return {
    playerProfile: normalizeProfile(settings.playerProfile),
    opponentProfile: normalizeProfile(settings.opponentProfile),
    ...opponentAiDifficultyPayload(),
  };
}

function characters() {
  return catalog.characters || [];
}

function characterById(characterId) {
  return characters().find((character) => character.id === characterId) || null;
}

function selectedPlayerCodeman() {
  const profile = normalizeProfile(settings.playerProfile);
  return characterById(profile.codemanId) || characters()[0] || null;
}

function playmats() {
  return catalog.playmats || [];
}

function playmatById(playmatId) {
  return playmats().find((playmat) => playmat.id === playmatId) || null;
}

function homeGuide() {
  return catalog.homeGuide || null;
}

function validProfileKey(profileKey) {
  return ["playerProfile", "opponentProfile"].includes(profileKey) ? profileKey : "playerProfile";
}

function profileSideLabel(profileKey) {
  return validProfileKey(profileKey) === "opponentProfile" ? t("profileOpponent") : t("profilePlayer");
}

function uiAssetUrl(assetId) {
  return (catalog.uiAssets || {})[assetId] || null;
}

function devModeEnabled() {
  return Boolean(catalog.devMode || (state && state.devMode));
}

function updateCodemanProfile(profileKey, codemanId) {
  if (!["playerProfile", "opponentProfile"].includes(profileKey)) return;
  settings = {
    ...settings,
    [profileKey]: {
      ...normalizeProfile(settings[profileKey]),
      codemanId: codemanId || null,
    },
  };
  render();
  saveSettings();
}

function updatePlaymatProfile(profileKey, playmatId) {
  if (!["playerProfile", "opponentProfile"].includes(profileKey)) return;
  settings = {
    ...settings,
    [profileKey]: {
      ...normalizeProfile(settings[profileKey]),
      playmatId: playmatId || null,
    },
  };
  render();
  saveSettings();
}

function updateOpponentAiDifficulty(difficulty) {
  settings = {
    ...settings,
    opponentAiDifficulty: normalizeOpponentAiDifficulty(difficulty),
  };
  render();
  saveSettings();
}

function updateReducedMotion(enabled) {
  settings = {
    ...normalizeSettings(settings),
    reducedMotion: Boolean(enabled),
  };
  render();
  saveSettings();
}

function updateBgmTrack(trackId) {
  const wasPlaying = bgmPlaying;
  stopBgm();
  settings = {
    ...normalizeSettings(settings),
    bgmTrack: normalizeBgmTrack(trackId),
  };
  render();
  saveSettings();
  if (wasPlaying) toggleBgm();
}

async function setDeveloperMode(enabled) {
  const passwordInput = app.querySelector("[data-dev-mode-password]");
  const password = passwordInput ? passwordInput.value : "";
  const payload = await ZZApi.request("/api/settings/developer-mode", {
    enabled: Boolean(enabled),
    password,
  });
  if (payload.ok) {
    settings = normalizeSettings(payload.settings || {});
    catalog = { ...catalog, devMode: Boolean(payload.devMode) };
    if (state) state = { ...state, devMode: Boolean(payload.devMode) };
    settingsNotice = enabled ? t("developerModeEnabled") : t("developerModeDisabled");
  } else {
    settingsNotice = null;
  }
  render(payload.error || null);
}

function normalizeCodemanTrainingMethod(method) {
  const cleaned = String(method || "gae_epoch1_local").trim().toLowerCase();
  return CODEMAN_TRAINING_METHODS.some((item) => item.id === cleaned) ? cleaned : "gae_epoch1_local";
}

function normalizePositiveInt(value, fallback) {
  const parsed = Math.max(1, Math.round(Number(value)));
  return Number.isFinite(parsed) ? parsed : fallback;
}

function codemanTrainingRunId(codemanId) {
  const stamp = Date.now().toString(36);
  const random = Math.random().toString(36).slice(2, 8);
  return `web_${String(codemanId || "codeman").replace(/[^A-Za-z0-9_.-]+/g, "_")}_${stamp}_${random}`;
}

function codemanTrainingProgressPercent(status) {
  if (!status || status.percent == null) return null;
  const percent = Math.max(0, Math.min(100, Math.round(Number(status.percent))));
  return Number.isFinite(percent) ? percent : null;
}

function codemanTrainingProgressMessage(progress) {
  const percent = codemanTrainingProgressPercent(progress);
  const completed = progress && progress.completedEpisodes != null ? Number(progress.completedEpisodes) : null;
  const total = progress && progress.totalEpisodes != null ? Number(progress.totalEpisodes) : null;
  if (percent == null) return progress && progress.message ? progress.message : "Training...";
  if (Number.isFinite(completed) && Number.isFinite(total) && total > 0) {
    return `${percent}% · ${completed}/${total}`;
  }
  return `${percent}%`;
}

function stopCodemanTrainingProgressPolling(codemanId) {
  const timer = codemanTrainingPollTimers[codemanId];
  if (timer) clearInterval(timer);
  delete codemanTrainingPollTimers[codemanId];
}

function startCodemanTrainingProgressPolling(codemanId, runId) {
  stopCodemanTrainingProgressPolling(codemanId);
  pollCodemanTrainingProgress(codemanId, runId);
  codemanTrainingPollTimers[codemanId] = setInterval(
    () => pollCodemanTrainingProgress(codemanId, runId),
    1200,
  );
}

async function pollCodemanTrainingProgress(codemanId, runId) {
  if (!codemanId || !runId) return;
  const current = codemanTrainingStatus[codemanId];
  if (!current || current.runId !== runId || current.state !== "running") return;
  try {
    const payload = await ZZApi.request(
      `/api/codeman-ai/${encodeURIComponent(codemanId)}/training-progress?runId=${encodeURIComponent(runId)}`,
    );
    const latest = codemanTrainingStatus[codemanId];
    if (!latest || latest.runId !== runId || latest.state !== "running") return;
    const progress = payload.progress || {};
    if (progress.state === "idle") return;
    const percent = codemanTrainingProgressPercent(progress);
    codemanTrainingStatus = {
      ...codemanTrainingStatus,
      [codemanId]: {
        ...latest,
        percent: percent == null ? latest.percent : percent,
        message: codemanTrainingProgressMessage(progress),
      },
    };
    renderPreservingActiveViewScroll();
  } catch (error) {
    // Keep the original training request authoritative; polling failures should not fail the run UI.
  }
}

async function requestCodemanTraining(codemanId) {
  if (!codemanId) return;
  const runId = codemanTrainingRunId(codemanId);
  codemanTrainingStatus = {
    ...codemanTrainingStatus,
    [codemanId]: { state: "running", message: "0%", percent: 0, runId },
  };
  renderPreservingActiveViewScroll();
  startCodemanTrainingProgressPolling(codemanId, runId);
  try {
    const payload = await ZZApi.request(`/api/codeman-ai/${encodeURIComponent(codemanId)}/train`, {
      circles: codemanTrainingCircles,
      trainingMethod: codemanTrainingMethod,
      checkpointInterval: codemanTrainingCheckpointInterval,
      runId,
    });
    stopCodemanTrainingProgressPolling(codemanId);
    const report = payload.report || {};
    codemanTrainingStatus = {
      ...codemanTrainingStatus,
      [codemanId]: {
        state: payload.ok ? "done" : "error",
        percent: payload.ok ? 100 : codemanTrainingStatus[codemanId].percent,
        runId,
        message: payload.ok
          ? (report.promoted ? "Champion updated" : "Report saved")
          : ((payload.error && (payload.error.message || payload.error.code)) || "Training failed"),
      },
    };
  } catch (error) {
    stopCodemanTrainingProgressPolling(codemanId);
    codemanTrainingStatus = {
      ...codemanTrainingStatus,
      [codemanId]: {
        state: "error",
        percent: codemanTrainingStatus[codemanId].percent,
        runId,
        message: error && error.message ? error.message : "Training failed",
      },
    };
  }
  renderPreservingActiveViewScroll();
}

function encodeReplayRoutePart(value) {
  return encodeURIComponent(String(value || ""));
}

function codemanMemoryHash(codemanId) {
  return `#/codeman-memory/${encodeReplayRoutePart(codemanId)}`;
}

function codemanReplayHash(codemanId, matchId) {
  return `#/replay/${encodeReplayRoutePart(codemanId)}/${encodeReplayRoutePart(matchId)}`;
}

function parseCodemanReplayHash(hash = window.location.hash) {
  const value = String(hash || "").replace(/^#\/?/, "");
  const parts = value.split("/").map((part) => decodeURIComponent(part || ""));
  if (parts[0] === "codeman-memory" && parts[1]) {
    return { view: CODEMAN_MEMORY_VIEW, codemanId: parts[1] };
  }
  if (parts[0] === "replay" && parts[1] && parts[2]) {
    return { view: CODEMAN_REPLAY_VIEW, codemanId: parts[1], matchId: parts[2] };
  }
  return null;
}

function setCodemanReplayHash(hash) {
  if (window.location.hash === hash) {
    handleCodemanReplayRoute();
    return;
  }
  window.location.hash = hash;
}

function navigateCodemanMemory(codemanId) {
  if (!codemanId) return;
  setCodemanReplayHash(codemanMemoryHash(codemanId));
}

function navigateCodemanReplay(codemanId, matchId) {
  if (!codemanId || !matchId) return;
  setCodemanReplayHash(codemanReplayHash(codemanId, matchId));
}

function currentCodemanReplayUrl() {
  if (!codemanReplayState.codemanId || !codemanReplayState.matchId) return "";
  const base = `${window.location.origin}${window.location.pathname}`;
  return `${base}${codemanReplayHash(codemanReplayState.codemanId, codemanReplayState.matchId)}`;
}

async function openCodemanReplayWindow() {
  const url = currentCodemanReplayUrl();
  if (!url) return;
  if (ZZApi.desktop && typeof ZZApi.desktop.openReplayWindow === "function") {
    const result = await ZZApi.desktop.openReplayWindow({
      codemanId: codemanReplayState.codemanId,
      matchId: codemanReplayState.matchId,
      url,
    });
    if (result && result.ok) return;
  }
  navigateCodemanReplay(codemanReplayState.codemanId, codemanReplayState.matchId);
}

function handleCodemanReplayRoute() {
  const route = parseCodemanReplayHash();
  if (!route) return false;
  if (route.view === CODEMAN_MEMORY_VIEW) {
    if (appView !== CODEMAN_MEMORY_VIEW || codemanReplayState.codemanId !== route.codemanId) {
      requestCodemanMemory(route.codemanId);
    } else {
      renderPreservingActiveViewScroll();
    }
    return true;
  }
  if (route.view === CODEMAN_REPLAY_VIEW) {
    if (
      codemanReplayState.codemanId !== route.codemanId ||
      !Array.isArray(codemanReplayState.memory) ||
      !codemanReplayState.memory.length
    ) {
      requestCodemanMemory(route.codemanId);
    }
    if (
      appView !== CODEMAN_REPLAY_VIEW ||
      codemanReplayState.codemanId !== route.codemanId ||
      codemanReplayState.matchId !== route.matchId ||
      !codemanReplayState.replay
    ) {
      requestCodemanReplay(route.codemanId, route.matchId);
    } else {
      renderPreservingActiveViewScroll();
    }
    return true;
  }
  return false;
}

async function requestCodemanMemory(codemanId) {
  if (!codemanId) return;
  stopCodemanReplayAutoplay();
  clearCodemanReplayAnimationWindow();
  appView = CODEMAN_MEMORY_VIEW;
  codemanReplayState = {
    ...codemanReplayState,
    codemanId,
    memory: [],
    replay: null,
    matchId: null,
    mode: "original",
    index: 0,
    animatingIndex: null,
    playing: false,
    loading: true,
    correcting: false,
    error: null,
  };
  render();
  try {
    const payload = await ZZApi.request(`/api/codeman-ai/${encodeURIComponent(codemanId)}/memory?limit=24`);
    codemanReplayState = {
      ...codemanReplayState,
      memory: payload.memory || [],
      loading: false,
      error: null,
    };
  } catch (error) {
    codemanReplayState = {
      ...codemanReplayState,
      loading: false,
      error: error && error.message ? error.message : "Codeman memory unavailable.",
    };
  }
  render();
}

async function requestCodemanReplay(codemanId, matchId, mode = "original") {
  if (!codemanId || !matchId) return;
  stopCodemanReplayAutoplay();
  clearCodemanReplayAnimationWindow();
  appView = CODEMAN_REPLAY_VIEW;
  codemanReplayState = {
    ...codemanReplayState,
    codemanId,
    matchId,
    replay: null,
    mode,
    index: 0,
    animatingIndex: null,
    playing: false,
    loading: true,
    correcting: false,
    error: null,
  };
  render();
  try {
    const payload = await ZZApi.request(`/api/codeman-ai/${encodeURIComponent(codemanId)}/memory/${encodeURIComponent(matchId)}`);
    const replay = payload.replay || null;
    const nextMode = mode === "corrected" && replay && replay.correctedReplay ? "corrected" : "original";
    codemanReplayState = {
      ...codemanReplayState,
      replay,
      mode: nextMode,
      index: 0,
      animatingIndex: null,
      playing: false,
      loading: false,
      error: null,
    };
  } catch (error) {
    codemanReplayState = {
      ...codemanReplayState,
      loading: false,
      error: error && error.message ? error.message : "Codeman replay unavailable.",
    };
  }
  render();
}

function codemanReplayCanCorrect(replay = codemanReplayState.replay) {
  const memory = replay && replay.memory;
  if (!memory || !memory.hasTrace) return false;
  const playerSide = memory.playerSide;
  const winnerSide = memory.winnerSide;
  return Boolean(playerSide && winnerSide && playerSide !== winnerSide);
}

async function requestCodemanReplayCorrection(codemanId, matchId) {
  if (!codemanId || !matchId || !codemanReplayCanCorrect()) return;
  stopCodemanReplayAutoplay();
  clearCodemanReplayAnimationWindow();
  codemanReplayState = {
    ...codemanReplayState,
    correcting: true,
    error: null,
  };
  renderPreservingActiveViewScroll();
  try {
    const payload = await ZZApi.request(
      `/api/codeman-ai/${encodeURIComponent(codemanId)}/memory/${encodeURIComponent(matchId)}/correct`,
      { decisionWindow: 10, alternativesPerDecision: 3 },
    );
    if (!payload || payload.ok === false) {
      const message = payload && payload.error && payload.error.message
        ? payload.error.message
        : "Codeman replay correction unavailable.";
      throw new Error(message);
    }
    const result = payload.result || {};
    if (!result.corrected) {
      codemanReplayState = {
        ...codemanReplayState,
        correcting: false,
        error: result.reason || t("codemanReplayCorrectionNoBranch"),
      };
      renderPreservingActiveViewScroll();
      return;
    }
    await requestCodemanReplay(codemanId, matchId, "corrected");
  } catch (error) {
    codemanReplayState = {
      ...codemanReplayState,
      correcting: false,
      error: error && error.message ? error.message : "Codeman replay correction unavailable.",
    };
    renderPreservingActiveViewScroll();
  }
}

function codemanReplayPayload() {
  const replay = codemanReplayState.replay;
  if (!replay) return null;
  if (codemanReplayState.mode === "corrected" && replay.correctedReplay) {
    return replay.correctedReplay;
  }
  return replay.trace || null;
}

function codemanReplayEvents() {
  const payload = codemanReplayPayload();
  return payload && Array.isArray(payload.logEvents) ? payload.logEvents : [];
}

function codemanReplayEventSnapshotIndex(event, eventIndex = 0) {
  const snapshotIndex = Number(event && event.snapshotIndex);
  return Number.isFinite(snapshotIndex) ? snapshotIndex : eventIndex;
}

function codemanReplaySnapshots() {
  const payload = codemanReplayPayload();
  if (!payload) return [];
  return Array.isArray(payload.stateSnapshots || payload.snapshots)
    ? (payload.stateSnapshots || payload.snapshots)
    : [];
}

function codemanReplayFrameCount() {
  const events = codemanReplayEvents();
  const snapshots = codemanReplaySnapshots();
  if (!snapshots.length) return events.length;
  const highestEventFrame = events.reduce(
    (highest, event, eventIndex) => Math.max(highest, codemanReplayEventSnapshotIndex(event, eventIndex)),
    -1,
  );
  return Math.max(snapshots.length, highestEventFrame + 1);
}

function codemanReplaySnapshotForIndex(index = codemanReplayState.index) {
  const snapshots = codemanReplaySnapshots();
  if (!snapshots.length) return null;
  const clamped = Math.max(0, Math.min(snapshots.length - 1, Number(index) || 0));
  return snapshots[clamped] || null;
}

function codemanReplayCurrentSnapshot(index = codemanReplayState.index) {
  return codemanReplaySnapshotForIndex(index);
}

function clearCodemanReplaySettleTimer() {
  if (codemanReplaySettleTimer) {
    clearTimeout(codemanReplaySettleTimer);
    codemanReplaySettleTimer = null;
  }
}

function clearCodemanReplayAnimationWindow({ rerender = false } = {}) {
  clearCodemanReplaySettleTimer();
  if (codemanReplayState.animatingIndex == null) return;
  codemanReplayState = {
    ...codemanReplayState,
    animatingIndex: null,
  };
  if (rerender) renderPreservingActiveViewScroll();
}

function replayAnimationKey(event) {
  try {
    return JSON.stringify(event);
  } catch (_) {
    return String(event && event.type ? event.type : "");
  }
}

function codemanReplayFrameAnimationEvents(index = codemanReplayState.index) {
  const snapshot = codemanReplaySnapshotForIndex(index);
  if (!snapshot || !Array.isArray(snapshot.animationEvents)) return [];
  let events = snapshot.animationEvents.filter((event) => event && event.type);
  const previous = codemanReplaySnapshotForIndex(Number(index) - 1);
  const previousEvents = previous && Array.isArray(previous.animationEvents)
    ? previous.animationEvents.filter((event) => event && event.type)
    : [];
  if (previousEvents.length && events.length) {
    const previousCounts = new Map();
    previousEvents.forEach((event) => {
      const key = replayAnimationKey(event);
      previousCounts.set(key, (previousCounts.get(key) || 0) + 1);
    });
    events = events.filter((event) => {
      const key = replayAnimationKey(event);
      const count = previousCounts.get(key) || 0;
      if (!count) return true;
      previousCounts.set(key, count - 1);
      return false;
    });
  }
  return events;
}

function codemanReplayFrameAnimationDuration(index = codemanReplayState.index, events = codemanReplayFrameAnimationEvents(index)) {
  return events.reduce((sum, event) => sum + Math.max(0, animationEventDuration(event)), 0);
}

function codemanReplayDisplaySnapshotIndex(index = codemanReplayState.index) {
  const frameIndex = Math.max(0, Number(index) || 0);
  return codemanReplayState.animatingIndex === frameIndex && frameIndex > 0 ? frameIndex - 1 : frameIndex;
}

function enqueueCodemanReplayFrameAnimations(index = codemanReplayState.index) {
  const events = codemanReplayFrameAnimationEvents(index);
  if (!events.length) {
    clearCodemanReplayAnimationWindow();
    return false;
  }
  const frameIndex = Math.max(0, Number(index) || 0);
  clearCodemanReplaySettleTimer();
  codemanReplayState = {
    ...codemanReplayState,
    animatingIndex: frameIndex,
  };
  enqueueAnimationEvents(events);
  const duration = codemanReplayFrameAnimationDuration(frameIndex, events);
  codemanReplaySettleTimer = setTimeout(() => {
    codemanReplaySettleTimer = null;
    if (appView !== CODEMAN_REPLAY_VIEW || codemanReplayState.animatingIndex !== frameIndex) return;
    codemanReplayState = {
      ...codemanReplayState,
      animatingIndex: null,
    };
    renderPreservingActiveViewScroll();
  }, Math.max(120, duration + 60));
  return true;
}

function setCodemanReplayIndex(index, { animate = false } = {}) {
  stopCodemanReplayAutoplay();
  clearCodemanReplayAnimationWindow();
  const count = codemanReplayFrameCount();
  const max = Math.max(0, count - 1);
  const nextIndex = Math.max(0, Math.min(max, Number(index) || 0));
  codemanReplayState = {
    ...codemanReplayState,
    index: nextIndex,
    playing: false,
  };
  if (animate) enqueueCodemanReplayFrameAnimations(nextIndex);
  renderPreservingActiveViewScroll();
}

function setCodemanReplayMode(mode) {
  stopCodemanReplayAutoplay();
  clearCodemanReplayAnimationWindow();
  const replay = codemanReplayState.replay;
  const nextMode = mode === "corrected" && replay && replay.correctedReplay ? "corrected" : "original";
  codemanReplayState = {
    ...codemanReplayState,
    mode: nextMode,
    playing: false,
  };
  const max = Math.max(0, codemanReplayFrameCount() - 1);
  codemanReplayState = {
    ...codemanReplayState,
    index: Math.min(codemanReplayState.index, max),
  };
  renderPreservingActiveViewScroll();
}

function advanceCodemanReplay(step = 1) {
  const count = codemanReplayFrameCount();
  if (!count) return;
  clearCodemanReplayAnimationWindow();
  const nextIndex = Math.max(0, Math.min(count - 1, codemanReplayState.index + step));
  codemanReplayState = {
    ...codemanReplayState,
    index: nextIndex,
  };
  enqueueCodemanReplayFrameAnimations(nextIndex);
  if (nextIndex >= count - 1) stopCodemanReplayAutoplay();
  renderPreservingActiveViewScroll();
}

function startCodemanReplayAutoplay() {
  stopCodemanReplayAutoplay();
  clearCodemanReplayAnimationWindow();
  const count = codemanReplayFrameCount();
  if (!count || codemanReplayState.index >= count - 1) return;
  codemanReplayState = {
    ...codemanReplayState,
    playing: true,
  };
  renderPreservingActiveViewScroll();
  scheduleCodemanReplayTick();
}

function scheduleCodemanReplayTick() {
  if (!codemanReplayState.playing) return;
  const delay = Math.max(360, codemanReplayFrameAnimationDuration(codemanReplayState.index) + 120);
  codemanReplayTimer = setTimeout(() => {
    const count = codemanReplayFrameCount();
    if (!count || codemanReplayState.index >= count - 1) {
      stopCodemanReplayAutoplay();
      renderPreservingActiveViewScroll();
      return;
    }
    const nextIndex = Math.min(count - 1, codemanReplayState.index + 1);
    clearCodemanReplayAnimationWindow();
    codemanReplayState = {
      ...codemanReplayState,
      index: nextIndex,
    };
    enqueueCodemanReplayFrameAnimations(nextIndex);
    if (nextIndex >= count - 1) {
      stopCodemanReplayAutoplay();
      renderPreservingActiveViewScroll();
      return;
    }
    renderPreservingActiveViewScroll();
    scheduleCodemanReplayTick();
  }, delay);
}

function stopCodemanReplayAutoplay() {
  if (codemanReplayTimer) {
    clearTimeout(codemanReplayTimer);
    codemanReplayTimer = null;
  }
  if (codemanReplayState.playing) {
    codemanReplayState = {
      ...codemanReplayState,
      playing: false,
    };
  }
}

function closeCodemanReplayView() {
  stopCodemanReplayAutoplay();
  clearCodemanReplayAnimationWindow();
  if (appView === CODEMAN_REPLAY_VIEW && codemanReplayState.codemanId) {
    navigateCodemanMemory(codemanReplayState.codemanId);
    return;
  }
  codemanReplayState = {
    ...codemanReplayState,
    replay: null,
    matchId: null,
    index: 0,
    playing: false,
    loading: false,
    error: null,
  };
  if (window.location.hash && parseCodemanReplayHash()) {
    window.location.hash = "";
  }
  showHome();
}

function launchDeckEntries() {
  return [
    ...((catalog.defaultDecks || []).map((deck) => ({
      key: `template:${deck.id}`,
      source: "Template",
      deck,
    }))),
    ...(savedDecks || []).map((deck) => ({
      key: `saved:${deck.id}`,
      source: "Saved",
      deck,
    })),
  ];
}

function selectedOpponentDeckEntry() {
  const entries = launchDeckEntries();
  if (!entries.length) return null;
  return entries.find((entry) => entry.key === selectedOpponentDeckKey) || entries[0];
}

function selectedPlayerDeckEntry() {
  const entries = launchDeckEntries();
  if (!entries.length) return null;
  return entries.find((entry) => entry.key === selectedPlayerDeckKey) || entries[0];
}

function setOpponentDeckKey(key) {
  selectedOpponentDeckKey = key;
  render();
}

function setPlayerDeckKey(key) {
  selectedPlayerDeckKey = key;
  render();
}

function filterGroups() {
  return catalog.filters || [];
}

function localizedCatalogLabel(item, fallback = "") {
  if (!item) return fallback;
  const lang = currentLanguage();
  if (lang === "zh") return item.labelZh || fallback;
  if (lang === "en") return item.labelEn || fallback;
  return item.labelJp || fallback;
}

function localizedFilterValue(groupId, value, fallback = "") {
  const group = filterGroups().find((item) => item.id === groupId);
  const option = group && (group.options || []).find((item) => String(item.value) === String(value));
  return option ? localizedCatalogLabel(option, fallback) : fallback;
}

function localizedCardType(card) {
  return localizedFilterValue("cardtype", card.cardTypeJp, card.type || "");
}

function localizedCardAttribute(card) {
  return localizedFilterValue("attribute", card.attributeJp, card.manaColor || "");
}

function localizedCardSeries(card) {
  return localizedFilterValue("series", card.packJp, "");
}

function localizedCardRace(value) {
  return localizedFilterValue("race", value, "");
}

function localizedCardRarity(card) {
  return localizedFilterValue("reality", card.rarity, card.rarity || "");
}

function activeOfficialFilters() {
  return Object.entries(deckEditor.filters || {}).filter(([, value]) => Boolean(value));
}

function cardMatchesOfficialFilters(card) {
  return activeOfficialFilters().every(([groupId, value]) => {
    const values = ((card.filterValues || {})[groupId] || []).map((item) => String(item));
    return values.includes(String(value));
  });
}

function cardMatchesSearch(card, search) {
  if (!search) return true;
  const values = [
    card.id,
    card.nameJp,
    card.nameEn,
    card.nameZh,
    card.type,
    card.cardTypeJp,
    card.attributeJp,
    card.officialCost,
    card.packJp,
    card.rarity,
    card.abilityJp,
    card.abilityEn,
    card.abilityZh,
    ...(card.raceJp || []),
    ...(card.effectTagsJp || []),
    ...(card.effectTimingJp || []),
    ...(card.conditionTagsJp || []),
  ];
  return values.some((value) => String(value || "").toLowerCase().includes(search));
}

function setDeckFilter(groupId, value) {
  deckEditor.filters = { ...(deckEditor.filters || {}) };
  if (value) deckEditor.filters[groupId] = value;
  else delete deckEditor.filters[groupId];
  render();
}

function resetDeckFilters() {
  deckEditor.filters = {};
  render();
}

function loadDeckIntoEditor(deck) {
  deckEditor = {
    id: deck.id || null,
    name: deck.name || "New Deck",
    recipe: { ...(deck.recipe || {}) },
    selectedForceIds: [...(deck.forces || [])],
    search: deckEditor.search || "",
    filters: { ...(deckEditor.filters || {}) },
  };
}

function startDeckBuilder(deck = null) {
  stopAuto(false);
  appView = "deckbuilder";
  if (deck) loadDeckIntoEditor(deck);
  render();
}

function newDeckInEditor() {
  stopAuto(false);
  appView = "deckbuilder";
  deckEditor = createEmptyDeckEditor();
  selectedCatalogCardId = null;
  render();
}

function showHome() {
  stopAuto(false);
  appView = "home";
  settingsNotice = null;
  if (window.location.hash && parseCodemanReplayHash()) {
    window.history.replaceState(null, "", `${window.location.pathname}${window.location.search}`);
  }
  render();
}

function showLobby() {
  stopAuto(false);
  appView = "lobby";
  render();
}

function multiplayerBridge() {
  return window.zzMultiplayer && typeof window.zzMultiplayer.status === "function"
    ? window.zzMultiplayer
    : null;
}

function isOnlineDuel() {
  return Boolean(activeMatchPayload && activeMatchPayload.multiplayer);
}

function multiplayerErrorText(error = multiplayerUi.lastError) {
  if (!error) return "";
  if (typeof error === "string") return error;
  return String(error.message || error.code || error);
}

function applyMultiplayerSnapshot(snapshot, { rerender = true } = {}) {
  if (!snapshot || typeof snapshot !== "object") return;
  const previousOnlineDuel = isOnlineDuel();
  const previousDisplayName = multiplayerUi.displayName;
  const previousOpening = isOnlineOpeningChoice();
  const previousOpeningPlayer = currentOnlineRoomPlayer();
  const previousChoiceSubmitted = Boolean(previousOpeningPlayer && previousOpeningPlayer.openingChoiceSubmitted);
  const previousOpeningTie = Boolean(
    multiplayerUi.room
    && multiplayerUi.room.lastOpeningResult
    && multiplayerUi.room.lastOpeningResult.result === "tie"
  );
  multiplayerUi = {
    ...multiplayerUi,
    ...snapshot,
    room: snapshot.room || null,
    view: hydrateMultiplayerViewAssets(snapshot.view || null),
    pendingAction: snapshot.pendingAction || null,
    lastError: snapshot.lastError || null,
    lan: { ...(multiplayerUi.lan || {}), ...(snapshot.lan || {}) },
    displayName: previousDisplayName,
  };
  const roomPlayer = currentOnlineRoomPlayer();
  if (roomPlayer && roomPlayer.displayName) {
    multiplayerUi.displayName = roomPlayer.displayName;
  }
  const openingVisible = multiplayerUi.status === "MATCH_STARTING";
  const matchVisible = ["IN_MATCH", "MATCH_FINISHED"].includes(multiplayerUi.status)
    || Boolean(multiplayerUi.view && multiplayerUi.view.gameOver);
  const reconnecting = multiplayerUi.status === "RECONNECTING";
  if (openingVisible) {
    if (!previousOnlineDuel) clearDuelUiState();
    state = null;
    activeMatchPayload = { multiplayer: true };
    pendingChoicePromptId = null;
    lastAppliedMultiplayerViewKey = null;
    appView = "duel";
  } else if (matchVisible && multiplayerUi.view) {
    if (!previousOnlineDuel) clearDuelUiState();
    const viewKey = [
      multiplayerUi.matchId || "match",
      multiplayerUi.view.revision,
      multiplayerUi.view.stateHash,
    ].join(":");
    if (viewKey !== lastAppliedMultiplayerViewKey) {
      if (previousOnlineDuel && pendingVisualState) {
        commitPendingVisualState({ rerender: false });
      }
      stageDuelState(multiplayerUi.view, null);
      lastAppliedMultiplayerViewKey = viewKey;
    }
    activeMatchPayload = { multiplayer: true };
    pendingChoicePromptId = multiplayerUi.pendingAction && state.prompt ? state.prompt.id : null;
    appView = "duel";
  } else if (reconnecting && (previousOnlineDuel || state || multiplayerUi.view)) {
    activeMatchPayload = { multiplayer: true };
    appView = "duel";
    if (!state && multiplayerUi.view) {
      stageDuelState(multiplayerUi.view, null);
    }
  } else if (previousOnlineDuel && !matchVisible && !reconnecting) {
    clearDuelUiState();
    state = null;
    activeMatchPayload = {};
    pendingChoicePromptId = null;
    lastAppliedMultiplayerViewKey = null;
    appView = ONLINE_VIEW;
  }
  if (multiplayerUi.status === "CONNECTED" && !multiplayerUi.room) {
    if (lanPendingCreateRoom) {
      lanPendingCreateRoom = false;
      queueMicrotask(() => createOnlineRoom());
    } else if (lanPendingJoin) {
      const pending = lanPendingJoin;
      lanPendingJoin = null;
      queueMicrotask(() => runMultiplayerCommand("joinRoom", pending));
    }
  }
  if (rerender && previousOpening && isOnlineOpeningChoice()) {
    const nextPlayer = currentOnlineRoomPlayer();
    const nextChoiceSubmitted = Boolean(nextPlayer && nextPlayer.openingChoiceSubmitted);
    const nextOpeningTie = Boolean(
      multiplayerUi.room
      && multiplayerUi.room.lastOpeningResult
      && multiplayerUi.room.lastOpeningResult.result === "tie"
    );
    if (previousChoiceSubmitted === nextChoiceSubmitted && previousOpeningTie === nextOpeningTie) {
      rerender = false;
    }
  }
  if (rerender) {
    const hideRecoveryNoise = !multiplayerUi.room && ["RECONNECTING", "OFFLINE", "ERROR"].includes(multiplayerUi.status);
    render(hideRecoveryNoise ? null : multiplayerUi.lastError);
  }
}

async function refreshMultiplayerSnapshot({ rerender = true } = {}) {
  const bridge = multiplayerBridge();
  if (!bridge) return null;
  try {
    const snapshot = await bridge.status();
    applyMultiplayerSnapshot(snapshot, { rerender });
    return snapshot;
  } catch (error) {
    multiplayerUi.lastError = { code: "DESKTOP_IPC_ERROR", message: error.message || String(error) };
    if (rerender) render(multiplayerUi.lastError);
    return null;
  }
}

async function initMultiplayerBridge() {
  if (parseCodemanReplayHash()) return null;
  const bridge = multiplayerBridge();
  if (!bridge) return null;
  if (!multiplayerUnsubscribe && typeof bridge.onEvent === "function") {
    multiplayerUnsubscribe = bridge.onEvent((event) => {
      if (event && event.snapshot) {
        const rejection = event.message
          && event.message.payload
          && event.message.payload.result
          && event.message.payload.result.rejection;
        applyMultiplayerSnapshot({
          ...event.snapshot,
          lastError: rejection || event.snapshot.lastError,
        });
      } else {
        refreshMultiplayerSnapshot();
      }
    });
  }
  return refreshMultiplayerSnapshot({ rerender: false });
}

async function runMultiplayerCommand(command, ...args) {
  const bridge = multiplayerBridge();
  if (!bridge || typeof bridge[command] !== "function") {
    multiplayerUi.lastError = { code: "DESKTOP_REQUIRED", message: t("onlineUnavailable") };
    render(multiplayerUi.lastError);
    return null;
  }
  try {
    multiplayerUi.lastError = null;
    const result = await bridge[command](...args);
    await refreshMultiplayerSnapshot();
    return result;
  } catch (error) {
    multiplayerUi.lastError = { code: "MULTIPLAYER_COMMAND_FAILED", message: error.message || String(error) };
    render(multiplayerUi.lastError);
    return null;
  }
}

function onlineInputValue(selector, fallback = "") {
  const input = app.querySelector(selector);
  return input ? String(input.value || "").trim() : fallback;
}

const ONLINE_DISPLAY_NAME_KEY = "zz_online_display_name";

function rememberedOnlineDisplayName() {
  try {
    const raw = window.localStorage.getItem(ONLINE_DISPLAY_NAME_KEY);
    const name = String(raw || "").trim().slice(0, 40);
    return name || "Player";
  } catch (_) {
    return "Player";
  }
}

function persistOnlineDisplayName(name = onlineInputValue("[data-online-name]", multiplayerUi.displayName || "Player")) {
  const trimmed = String(name || "").trim().slice(0, 40);
  multiplayerUi.displayName = trimmed || "Player";
  try {
    window.localStorage.setItem(ONLINE_DISPLAY_NAME_KEY, multiplayerUi.displayName);
  } catch (_) {
    // Renderer storage is optional; the in-memory name still survives snapshot rerenders.
  }
  return multiplayerUi.displayName;
}

async function connectOnlineServer() {
  persistOnlineDisplayName();
  const rawUrl = onlineInputValue("[data-online-url]", multiplayerUi.url);
  const url = multiplayerUi.mode === "lan" ? normalizeLanUrl(rawUrl) : rawUrl;
  if (url) multiplayerUi.url = url;
  if (multiplayerUi.status === "ERROR") {
    await runMultiplayerCommand("disconnect");
  }
  return runMultiplayerCommand("connect", { url });
}

function createOnlineRoom() {
  const displayName = persistOnlineDisplayName();
  return runMultiplayerCommand("createRoom", { displayName });
}

function joinOnlineRoom() {
  const displayName = persistOnlineDisplayName();
  const roomCode = onlineInputValue("[data-online-room-code]").toUpperCase();
  if (!roomCode) return null;
  return runMultiplayerCommand("joinRoom", { roomCode, displayName });
}

function submitOnlineDeck() {
  const entry = selectedPlayerDeckEntry();
  if (!entry || !entry.deck) return null;
  return runMultiplayerCommand("selectDeck", {
    deck: { ...(entry.deck.recipe || {}) },
    forces: [...(entry.deck.forces || [])],
    profile: normalizeProfile(settings.playerProfile),
  });
}

function currentOnlineRoomPlayer() {
  const players = (multiplayerUi.room && multiplayerUi.room.players) || [];
  return players.find((player) => player.playerId === multiplayerUi.playerId) || null;
}

function toggleOnlineReady() {
  const player = currentOnlineRoomPlayer();
  return runMultiplayerCommand("setReady", !Boolean(player && player.ready));
}

function submitOnlineOpeningChoice(choice) {
  return runMultiplayerCommand("selectOpeningChoice", choice);
}

async function leaveOnlineRoom({ surrender = false } = {}) {
  if (surrender && ["IN_MATCH", "MATCH_STARTING"].includes(multiplayerUi.status)) {
    await runMultiplayerCommand("surrender");
  }
  return runMultiplayerCommand("leaveRoom");
}

function normalizeLanUrl(value) {
  const raw = String(value || "").trim();
  if (!raw) return LAN_SERVER_URL;
  if (/^wss?:\/\//i.test(raw)) return raw;
  return `ws://${raw.includes(":") ? raw : `${raw}:32145`}`;
}

async function switchMultiplayerMode(mode) {
  const nextMode = mode === "lan" ? "lan" : "online";
  if (multiplayerUi.status !== "OFFLINE") {
    const snapshot = await runMultiplayerCommand("disconnect");
    if (!snapshot || multiplayerUi.status !== "OFFLINE") return;
  }
  multiplayerUi.mode = nextMode;
  multiplayerUi.url = multiplayerUi.mode === "lan" ? LAN_SERVER_URL : ONLINE_SERVER_URL;
  multiplayerUi.lastError = null;
  render();
}

async function startLanRoom() {
  const serverName = onlineInputValue("[data-lan-server-name]", "ZZ LAN Room") || "ZZ LAN Room";
  persistOnlineDisplayName();
  const result = await runMultiplayerCommand("startLanHost", { port: 32145, serverName });
  if (!result) return null;
  const localUrl = (result && result.lan && result.lan.localUrl)
    || (multiplayerUi.lan && multiplayerUi.lan.localUrl)
    || LAN_SERVER_URL;
  multiplayerUi.url = localUrl;
  lanPendingCreateRoom = true;
  return runMultiplayerCommand("connect", { url: localUrl });
}

async function stopLanHost() {
  if (multiplayerUi.room) return null;
  if (multiplayerUi.status !== "OFFLINE") await runMultiplayerCommand("disconnect");
  return runMultiplayerCommand("stopLanHost");
}

async function discoverLanRooms() {
  const bridge = multiplayerBridge();
  if (!bridge || typeof bridge.discoverLan !== "function") return null;
  persistOnlineDisplayName();
  multiplayerUi.lan = { ...(multiplayerUi.lan || {}), discovering: true };
  render();
  try {
    const discovered = await bridge.discoverLan({ timeoutMs: 4000 });
    multiplayerUi.lan = {
      ...(multiplayerUi.lan || {}),
      discovering: false,
      discovered: Array.isArray(discovered) ? discovered : [],
    };
    render();
    return discovered;
  } catch (error) {
    multiplayerUi.lan = { ...(multiplayerUi.lan || {}), discovering: false };
    multiplayerUi.lastError = { code: "LAN_DISCOVERY_FAILED", message: error.message || String(error) };
    render(multiplayerUi.lastError);
    return null;
  }
}

function joinDiscoveredLanRoom(target) {
  const host = String(target.dataset.lanAddress || "");
  const port = Number(target.dataset.lanPort || 32145);
  const roomCode = String(target.dataset.lanRoomCode || "");
  if (!host || !roomCode) return null;
  const displayName = persistOnlineDisplayName();
  multiplayerUi.url = `ws://${host}:${port}`;
  lanPendingJoin = { roomCode, displayName };
  return runMultiplayerCommand("connect", { url: multiplayerUi.url });
}

function openPlaymatDatabase(profileKey = selectedPlaymatProfileKey) {
  stopAuto(false);
  selectedPlaymatProfileKey = validProfileKey(profileKey);
  appView = "playmats";
  render();
}

function battleDebugSides() {
  const sides = players().map((player) => ({
    id: player.side,
    label: `${player.side} ${player.name || ""}`.trim(),
  }));
  return sides.length ? sides : [
    { id: "P1", label: "P1" },
    { id: "P2", label: "P2" },
  ];
}

function battleDebugFilterGroups() {
  const wanted = ["series", "cardtype", "attribute", "cost", "effect", "effect_timing", "conditions"];
  return wanted
    .map((groupId) => filterGroups().find((group) => group.id === groupId))
    .filter(Boolean);
}

function setBattleDebugFilter(groupId, value) {
  battleDebugFilters = { ...(battleDebugFilters || {}) };
  if (value) battleDebugFilters[groupId] = value;
  else delete battleDebugFilters[groupId];
  renderPreservingBattleDebugScroll();
}

function resetBattleDebugFilters() {
  battleDebugSearch = "";
  battleDebugFilters = {};
  renderPreservingBattleDebugScroll();
}

function cardMatchesBattleDebugFilters(card) {
  return Object.entries(battleDebugFilters || {}).every(([groupId, value]) => {
    const values = ((card.filterValues || {})[groupId] || []).map((item) => String(item));
    return values.includes(String(value));
  });
}

function battleDebugCards() {
  const search = battleDebugSearch.trim().toLowerCase();
  return (catalog.cards || [])
    .filter(cardMatchesBattleDebugFilters)
    .filter((card) => cardMatchesSearch(card, search))
    .slice(0, 120);
}

function refreshBattleDebugSearchResults() {
  const list = app.querySelector(".battle-debug-card-list");
  if (!list) throw new Error("Battle debug search result list is missing.");
  const cards = battleDebugCards();
  list.innerHTML = cards.length
    ? cards.map((card) => renderBattleDebugCard(card)).join("")
    : `<div class="empty">${esc(t("noCards"))}</div>`;
}

function captureBattleDebugScroll() {
  if (appView !== "duel" || !battleDebugOpen) return null;
  const list = document.querySelector(".battle-debug-card-list");
  return {
    cardListTop: list ? list.scrollTop : 0,
  };
}

function restoreBattleDebugScroll(snapshot) {
  if (!snapshot || appView !== "duel" || !battleDebugOpen) return;
  requestAnimationFrame(() => {
    const list = document.querySelector(".battle-debug-card-list");
    if (list) list.scrollTop = snapshot.cardListTop;
  });
}

function renderPreservingBattleDebugScroll(error = null) {
  const snapshot = captureBattleDebugScroll();
  render(error);
  restoreBattleDebugScroll(snapshot);
}

async function battleDebugApi(path, body = null) {
  const snapshot = captureBattleDebugScroll();
  const payload = await api(path, body);
  restoreBattleDebugScroll(snapshot);
  return payload;
}

async function addBattleDebugCard(cardId) {
  if (!devModeEnabled() || !cardId) return;
  await battleDebugApi("/api/debug/add-card", {
    cardId,
    side: battleDebugSide,
    zone: battleDebugZone,
    rested: cardZoneCanBeRested(battleDebugZone) && battleDebugRested,
  });
}

async function moveBattleDebugCard(iid, zone) {
  if (!devModeEnabled() || !iid || !zone) return;
  await battleDebugApi("/api/debug/move-card", {
    iid: Number(iid),
    zone,
  });
}

async function setBattleDebugCardRested(iid, rested) {
  if (!devModeEnabled() || !iid) return;
  await battleDebugApi("/api/debug/card-state", {
    iid: Number(iid),
    rested: Boolean(rested),
  });
}

async function toggleBattleDebugControlBoth(controlBoth) {
  if (!devModeEnabled()) return;
  await battleDebugApi("/api/debug/control", { controlBoth: Boolean(controlBoth) });
}

async function setupBattleDebugFixedBoard() {
  if (!devModeEnabled()) return;
  await battleDebugApi("/api/debug/fixed-board", {});
}

async function replaceBattleDebugForces(side) {
  if (!devModeEnabled() || !side) return;
  const selects = [...document.querySelectorAll(`[data-battle-debug-force-select="${CSS.escape(side)}"]`)];
  const forceIds = selects.map((select) => select.value).filter(Boolean);
  if (forceIds.length !== 2) return;
  await battleDebugApi("/api/debug/forces", { side, forceIds });
}

function playerDeckPayload(deck) {
  return {
    playerDeck: { ...(deck.recipe || {}) },
    playerForces: [...(deck.forces || deck.selectedForceIds || [])],
  };
}

function cloneLaunchPayload(payload = {}) {
  const clone = {};
  if (payload.playerDeck) clone.playerDeck = { ...payload.playerDeck };
  if (payload.playerForces) clone.playerForces = [...payload.playerForces];
  if (payload.opponentDeck) clone.opponentDeck = { ...payload.opponentDeck };
  if (payload.opponentForces) clone.opponentForces = [...payload.opponentForces];
  if (payload.playerProfile) clone.playerProfile = normalizeProfile(payload.playerProfile);
  if (payload.opponentProfile) clone.opponentProfile = normalizeProfile(payload.opponentProfile);
  if (payload.opponentAiDifficulty) clone.opponentAiDifficulty = normalizeOpponentAiDifficulty(payload.opponentAiDifficulty);
  if (payload.playerSide) clone.playerSide = normalizeChallengePlayerSide(payload.playerSide);
  if (payload.humanSide) clone.humanSide = normalizeChallengePlayerSide(payload.humanSide);
  if (payload.playerDeckId) clone.playerDeckId = String(payload.playerDeckId);
  if (payload.playerDeckName) clone.playerDeckName = String(payload.playerDeckName);
  if (payload.opponentDeckId) clone.opponentDeckId = String(payload.opponentDeckId);
  return clone;
}

function opponentDeckPayload(deck) {
  if (!deck || deckTotal(deck.recipe) !== 40 || new Set(deck.forces || []).size !== 2) return {};
  return {
    opponentDeck: { ...(deck.recipe || {}) },
    opponentForces: [...(deck.forces || [])],
  };
}

function selectedPlayerPayload() {
  const entry = selectedPlayerDeckEntry();
  const deck = entry && entry.deck;
  if (!deck || deckTotal(deck.recipe) !== 40 || new Set(deck.forces || []).size !== 2) return {};
  return playerDeckPayload(deck);
}

function selectedOpponentPayload() {
  const entry = selectedOpponentDeckEntry();
  return opponentDeckPayload(entry && entry.deck);
}

function selectedBattlePayload() {
  return {
    ...selectedPlayerPayload(),
    ...selectedOpponentPayload(),
    ...opponentAiDifficultyPayload(),
  };
}

function launchModeOptions() {
  const modes = [
    { id: "human-vs-ai", label: t("modeHumanAi") },
  ];
  if (devModeEnabled()) {
    modes.push(
      { id: "god", label: t("modeGod") },
      { id: "ai-vs-ai", label: t("modeAiVsAi") },
    );
  }
  return modes;
}

function currentLaunchMode() {
  const modes = launchModeOptions();
  return modes.some((mode) => mode.id === selectedLaunchMode)
    ? selectedLaunchMode
    : modes[0].id;
}

function setLaunchMode(mode) {
  selectedLaunchMode = ["human-vs-ai", "god", "ai-vs-ai"].includes(mode) ? mode : "human-vs-ai";
  render();
}

function startGameWithDeck(mode, deck) {
  if (!deck || deckTotal(deck.recipe) !== 40 || new Set(deck.forces || []).size !== 2) return;
  startNew(mode, {
    ...playerDeckPayload(deck),
    ...selectedOpponentPayload(),
  });
}

function startEditorDeck(mode) {
  if (!deckIsValid()) return;
  startGameWithDeck(mode, {
    name: deckEditor.name,
    recipe: { ...deckEditor.recipe },
    forces: [...deckEditor.selectedForceIds],
  });
}

function normalizeChallengePlayerSide(side) {
  return String(side || "").toUpperCase() === "P2" ? "P2" : "P1";
}

function updateDeckName(name) {
  deckEditor.name = name;
}

function captureDeckBuilderScroll() {
  if (appView !== "deckbuilder") return null;
  const catalogList = document.querySelector(".card-catalog-list");
  const deckList = document.querySelector(".deck-list");
  return {
    windowX: window.scrollX || 0,
    windowY: window.scrollY || 0,
    catalogTop: catalogList ? catalogList.scrollTop : 0,
    deckTop: deckList ? deckList.scrollTop : 0,
  };
}

function restoreDeckBuilderScroll(snapshot) {
  if (!snapshot || appView !== "deckbuilder") return;
  requestAnimationFrame(() => {
    const catalogList = document.querySelector(".card-catalog-list");
    const deckList = document.querySelector(".deck-list");
    if (catalogList) catalogList.scrollTop = snapshot.catalogTop;
    if (deckList) deckList.scrollTop = snapshot.deckTop;
    window.scrollTo(snapshot.windowX, snapshot.windowY);
  });
}

function renderPreservingDeckBuilderScroll(error = null) {
  const snapshot = captureDeckBuilderScroll();
  render(error);
  restoreDeckBuilderScroll(snapshot);
}

function captureCodemanReplayScroll() {
  if (appView !== CODEMAN_MEMORY_VIEW && appView !== CODEMAN_REPLAY_VIEW) return null;
  if (!document.querySelector(".codeman-replay-page")) return null;
  const memoryList = document.querySelector(".codeman-memory-list");
  const replayPlayer = document.querySelector(".codeman-replay-player");
  return {
    windowX: window.scrollX || 0,
    windowY: window.scrollY || 0,
    memoryTop: memoryList ? memoryList.scrollTop : 0,
    replayTop: replayPlayer ? replayPlayer.scrollTop : 0,
  };
}

function restoreCodemanReplayScroll(snapshot) {
  if (!snapshot || (appView !== CODEMAN_MEMORY_VIEW && appView !== CODEMAN_REPLAY_VIEW)) return;
  requestAnimationFrame(() => {
    const memoryList = document.querySelector(".codeman-memory-list");
    const replayPlayer = document.querySelector(".codeman-replay-player");
    if (memoryList) memoryList.scrollTop = snapshot.memoryTop;
    if (replayPlayer) replayPlayer.scrollTop = snapshot.replayTop;
    window.scrollTo(snapshot.windowX, snapshot.windowY);
  });
}

function renderPreservingCodemanReplayScroll(error = null) {
  const snapshot = captureCodemanReplayScroll();
  render(error);
  restoreCodemanReplayScroll(snapshot);
}

function renderPreservingActiveViewScroll(error = null) {
  if (appView === "deckbuilder") {
    renderPreservingDeckBuilderScroll(error);
    return;
  }
  if (appView === CODEMAN_MEMORY_VIEW || appView === CODEMAN_REPLAY_VIEW) {
    renderPreservingCodemanReplayScroll(error);
    return;
  }
  render(error);
}

function addDeckCard(cardId) {
  if (!canAddDeckCard(cardId)) return;
  deckEditor.recipe[cardId] = (deckEditor.recipe[cardId] || 0) + 1;
  renderPreservingDeckBuilderScroll();
}

function removeDeckCard(cardId) {
  const count = deckEditor.recipe[cardId] || 0;
  if (count <= 1) delete deckEditor.recipe[cardId];
  else deckEditor.recipe[cardId] = count - 1;
  renderPreservingDeckBuilderScroll();
}

function toggleDeckForce(forceId) {
  if (deckEditor.selectedForceIds.includes(forceId)) {
    deckEditor.selectedForceIds = deckEditor.selectedForceIds.filter((id) => id !== forceId);
  } else if (deckEditor.selectedForceIds.length < 2) {
    deckEditor.selectedForceIds.push(forceId);
  } else {
    deckEditor.selectedForceIds = [deckEditor.selectedForceIds[1], forceId];
  }
  render();
}

async function saveCurrentDeck() {
  if (!deckIsValid()) return;
  const payload = await ZZApi.request("/api/decks", {
    id: deckEditor.id,
    name: deckEditor.name.trim() || "Unnamed Deck",
    recipe: { ...deckEditor.recipe },
    forces: [...deckEditor.selectedForceIds],
  });
  if (!payload.ok) {
    render(payload.error);
    return;
  }
  loadDeckIntoEditor(payload.deck);
  await loadSavedDecks();
}

async function requestDeckAiCompletion() {
  if (!deckCanAiComplete() || deckCompletionLoading) return;
  deckCompletionLoading = true;
  renderPreservingDeckBuilderScroll();
  let payload;
  try {
    payload = await ZZApi.request("/api/decks/ai-complete", {
      recipe: { ...deckEditor.recipe },
      forces: [...deckEditor.selectedForceIds],
    });
  } catch (error) {
    deckCompletionLoading = false;
    renderPreservingDeckBuilderScroll(error);
    return;
  }
  deckCompletionLoading = false;
  if (!payload.ok) {
    renderPreservingDeckBuilderScroll(payload.error);
    return;
  }
  deckEditor.recipe = { ...(payload.completion.recipe || {}) };
  deckEditor.selectedForceIds = [...(payload.completion.forces || deckEditor.selectedForceIds)];
  renderPreservingDeckBuilderScroll();
}

async function deleteSavedDeck(deckId) {
  await ZZApi.delete(`/api/decks/${encodeURIComponent(deckId)}`);
  if (deckEditor.id === deckId) deckEditor.id = null;
  await loadSavedDecks();
}

function rawActivePrompt() {
  return state && state.prompt ? state.prompt : null;
}

function activePrompt() {
  const prompt = rawActivePrompt();
  if (prompt && pendingChoicePromptId === prompt.id) return null;
  if (promptBlockedByAnimation(prompt)) return null;
  return prompt;
}

function isMulliganPrompt() {
  const prompt = activePrompt();
  return Boolean(prompt && prompt.kind === "mulligan");
}

function promptPlayerSide() {
  const prompt = activePrompt();
  return prompt ? prompt.playerSide : null;
}

function syncMulliganSelection() {
  if (!state || !state.players || !state.players.human || !isMulliganPrompt()) {
    mulliganSelectedIids.clear();
    return;
  }
  const side = promptPlayerSide();
  const valid = new Set(players()
    .flatMap((player) => player.hand)
    .filter((card) => !side || card.ownerSide === side)
    .map((card) => card.iid));
  for (const iid of [...mulliganSelectedIids]) {
    if (!valid.has(iid)) mulliganSelectedIids.delete(iid);
  }
}

function optionById(optionId) {
  const prompt = activePrompt();
  if (!prompt) return null;
  return prompt.options.find((option) => option.id === optionId) || null;
}

function syncAiAdvice() {
  const prompt = activePrompt();
  if (!prompt) {
    aiAdvice = null;
    aiAdviceError = null;
    return;
  }
  if (aiAdvice && aiAdvice.promptId !== prompt.id) {
    aiAdvice = null;
  }
}

async function requestAiAdvice() {
  const prompt = activePrompt();
  if (!prompt || aiAdviceLoading) return;
  aiAdviceLoading = true;
  aiAdviceError = null;
  render();
  try {
    const payload = await ZZApi.request("/api/advice", {});
    aiAdvice = payload.advice || null;
    if (!payload.ok) {
      aiAdviceError = (payload.error && (payload.error.message || payload.error.code)) || "AI advice unavailable.";
    }
  } catch (error) {
    aiAdviceError = error && error.message ? error.message : "AI advice unavailable.";
  } finally {
    aiAdviceLoading = false;
    syncAiAdvice();
    render();
  }
}

function effectPromptRequiredCount(prompt = activePrompt()) {
  return Math.max(1, Number((prompt && prompt.requiredTargetCount) || 1));
}

function effectPromptMinimumCount(prompt = activePrompt()) {
  return Math.max(0, Number((prompt && prompt.minimumTargetCount) ?? effectPromptRequiredCount(prompt)));
}

function effectPromptMaximumCount(prompt = activePrompt()) {
  return Math.max(effectPromptMinimumCount(prompt), Number((prompt && prompt.maximumTargetCount) || effectPromptRequiredCount(prompt)));
}

function isMultiEffectPrompt(prompt = activePrompt()) {
  return Boolean(prompt && prompt.kind === "effect_target" && effectPromptMaximumCount(prompt) > 1);
}

function syncEffectTargetSelection() {
  const prompt = activePrompt();
  if (!isMultiEffectPrompt(prompt)) {
    effectTargetSelectionIds.clear();
    return;
  }
  const valid = new Set((prompt.options || [])
    .filter((option) => option.kind !== "effect_target_skip")
    .map((option) => option.id));
  for (const optionId of [...effectTargetSelectionIds]) {
    if (!valid.has(optionId)) effectTargetSelectionIds.delete(optionId);
  }
  const maximum = effectPromptMaximumCount(prompt);
  while (effectTargetSelectionIds.size > maximum) {
    const last = [...effectTargetSelectionIds].at(-1);
    effectTargetSelectionIds.delete(last);
  }
}

function toggleEffectTargetSelection(optionId) {
  const prompt = activePrompt();
  const option = optionById(optionId);
  if (!option) return;
  if (!isMultiEffectPrompt(prompt)) {
    choose(optionId);
    return;
  }
  if (effectTargetSelectionIds.has(optionId)) {
    effectTargetSelectionIds.delete(optionId);
  } else {
    const maximum = effectPromptMaximumCount(prompt);
    if (effectTargetSelectionIds.size >= maximum) {
      const first = effectTargetSelectionIds.values().next().value;
      effectTargetSelectionIds.delete(first);
    }
    effectTargetSelectionIds.add(optionId);
  }
  render();
}

function confirmEffectTargetSelection() {
  const prompt = activePrompt();
  if (!isMultiEffectPrompt(prompt)) return;
  const selectedOptionIds = [...effectTargetSelectionIds];
  if (selectedOptionIds.length < effectPromptMinimumCount(prompt)) return;
  if (selectedOptionIds.length > effectPromptMaximumCount(prompt)) return;
  if (!selectedOptionIds.length) {
    const skipOption = (prompt.options || []).find((option) => option.kind === "effect_target_skip");
    if (skipOption) choose(skipOption.id, { selectedOptionIds });
    return;
  }
  choose(selectedOptionIds[0], { selectedOptionIds });
}

function syncPaymentSelection() {
  if (!pendingPaymentOptionId) return;
  const option = optionById(pendingPaymentOptionId);
  if (!option || !isPaymentConfigurable(option)) {
    closePaymentEditor(false);
    return;
  }
  const valid = new Set((option.paymentCandidates || []).map((candidate) => candidate.iid));
  for (const iid of [...paymentSelectionIids]) {
    if (!valid.has(iid)) paymentSelectionIids.delete(iid);
  }
}

function syncFieldReplaceSelection() {
  if (!pendingFieldReplaceSourceIid) return;
  const source = findCardByIid(pendingFieldReplaceSourceIid);
  if (!source || !fieldReplacementOptionsForCard(source).length) {
    closeFieldReplaceEditor(false);
  }
}

function syncBaseReplaceSelection() {
  if (!pendingBaseReplaceSourceIid) return;
  const source = findCardByIid(pendingBaseReplaceSourceIid);
  if (!source || !baseReplacementOptionsForCard(source).length) {
    closeBaseReplaceEditor(false);
  }
}

function syncColorlessBaseReplaceSelection() {
  if (pendingColorlessBaseReplace && !colorlessBaseReplacementOptions().length) {
    closeColorlessBaseReplaceEditor(false);
  }
}

function actionOptionsForCard(card) {
  if (replayReadonlyMode) return [];
  const prompt = activePrompt();
  if (!prompt) return [];
  return MultiplayerCardPolicy.actionOptionsForCard(card, prompt.options).sort(cardActionPriority);
}

function blessActionsForMana(card) {
  return actionOptionsForCard(card).filter((option) => option.kind === "bless");
}

function blessActionsForTarget(card) {
  if (replayReadonlyMode) return [];
  const prompt = activePrompt();
  if (!prompt) return [];
  return prompt.options.filter((option) =>
    option.kind === "bless" && option.target_iid === card.iid
  );
}

function blessOptionForPair(sourceIid, targetIid) {
  const prompt = activePrompt();
  if (!prompt) return null;
  return prompt.options.find((option) =>
    option.kind === "bless" &&
    Number(option.mana_iid) === Number(sourceIid) &&
    Number(option.target_iid) === Number(targetIid)
  ) || null;
}

function isFieldReplacementOption(option) {
  return Boolean(
    option &&
    option.replace_field_iid &&
    (
      option.kind === "play_card" ||
      (option.kind === "move_card" && option.direction === "base_to_field")
    )
  );
}

function isBaseReplacementOption(option) {
  return Boolean(
    option &&
    option.replace_base_iid &&
    ["play_to_base", "move_card", "base_replacement"].includes(option.kind)
  );
}

function fieldReplacementOptionsForCard(card) {
  if (!card) return [];
  return actionOptionsForCard(card).filter(isFieldReplacementOption);
}

function baseReplacementOptionsForCard(card) {
  if (!card) return [];
  const prompt = activePrompt();
  if (
    prompt &&
    prompt.kind === "blessing_base_replacement" &&
    prompt.card &&
    Number(prompt.card.iid) === Number(card.iid)
  ) {
    return prompt.options.filter(isBaseReplacementOption);
  }
  return actionOptionsForCard(card).filter(isBaseReplacementOption);
}

function colorlessBaseReplacementOptions() {
  if (replayReadonlyMode) return [];
  const prompt = activePrompt();
  if (!prompt || prompt.kind !== "main_action" || !state || state.step !== "mana") return [];
  return prompt.options.filter((option) =>
    option.kind === "place_colorless_mana" && option.replace_base_iid
  );
}

function cardActionPriority(a, b) {
  const priority = (option) => {
    if (option.kind === "activate_flash_ability" || option.kind === "effect_target") return 0;
    if (option.kind === "attack") return 1;
    if (option.kind === "blocker" || option.kind === "minion") return 2;
    if (option.kind === "play_card") return 3;
    if (option.kind === "move_card" && option.direction === "base_to_field") return 4;
    if (option.kind === "move_card") return 5;
    if (option.kind === "play_to_base") return 6;
    return 9;
  };
  return priority(a) - priority(b);
}

function optionForCard(card) {
  return actionOptionsForCard(card)[0] || null;
}

function isPlayableCard(card) {
  return actionOptionsForCard(card).some((option) => option.kind === "play_card");
}

function isPaymentConfigurable(option) {
  return Boolean(
    option &&
    option.kind === "play_card" &&
    paymentRequiredCount(option) > 0 &&
    option.paymentCandidates &&
    option.paymentCandidates.length
  );
}

function isCardActionOption(option) {
  if (option.cardIid || option.attacker_iid) return true;
  return ["play_card", "play_to_base", "move_card", "bless", "attack", "activate_flash_ability"].includes(option.kind);
}

function isVisibleManaPromptOption(option) {
  if (option.kind === "skip_mana") return true;
  if (option.kind === "place_colorless_mana" && !option.replace_base_iid) return true;
  if (option.kind === "swap_mana_color") return true;
  return false;
}

function visiblePromptOptions(prompt) {
  if (replayReadonlyMode) return [];
  if (!prompt) return [];
  if (prompt.kind === "effect_target") return [];
  if (prompt.kind === "main_action" && state && state.step === "mana") {
    return prompt.options
      .filter((option) => isVisibleManaPromptOption(option))
      .sort((a, b) => (a.kind === "skip_mana" ? -1 : 0) - (b.kind === "skip_mana" ? -1 : 0));
  }
  const cardDrivenPrompts = ["main_action", "flash_action", "blocker", "attack_target"];
  if (!cardDrivenPrompts.includes(prompt.kind)) return prompt.options;
  return prompt.options.filter((option) => !isCardActionOption(option));
}

function optionForForce(force) {
  if (replayReadonlyMode) return null;
  const prompt = activePrompt();
  if (!prompt) return null;
  return prompt.options.find((option) =>
    option.forceId === force.id &&
    (!option.ownerSide || option.ownerSide === force.ownerSide)
  );
}

function optionForPlayer(player) {
  if (replayReadonlyMode) return null;
  const prompt = activePrompt();
  if (!prompt) return null;
  return prompt.options.find((option) => option.side === player.side);
}

function choose(optionId, extraPayload = null) {
  const prompt = activePrompt();
  if (!prompt || !optionId) return;
  const body = { promptId: prompt.id, optionId };
  if (extraPayload) Object.assign(body, extraPayload);
  if (prompt.kind === "mulligan" && optionId === "redraw_selected") {
    body.selectedCardIids = [...mulliganSelectedIids];
  }
  closePaymentEditor(false);
  closeFieldReplaceEditor(false);
  closeBaseReplaceEditor(false);
  closeColorlessBaseReplaceEditor(false);
  closeTrashDetail(false);
  closeCardDetail(false);
  effectTargetSelectionIds.clear();
  pendingChoicePromptId = prompt.id;
  renderPreservingActiveViewScroll();
  if (isOnlineDuel()) {
    const payload = { ...body };
    delete payload.promptId;
    delete payload.optionId;
    runMultiplayerCommand("submitAction", {
      kind: "CHOOSE_PROMPT_OPTION",
      promptId: prompt.id,
      optionId,
      payload,
    }).then((result) => {
      if (!result && pendingChoicePromptId === prompt.id) {
        pendingChoicePromptId = null;
        renderPreservingActiveViewScroll(multiplayerUi.lastError);
      }
    });
    return;
  }
  api("/api/choose", body).finally(() => {
    if (pendingChoicePromptId === prompt.id) {
      pendingChoicePromptId = null;
      renderPreservingActiveViewScroll(state && state.error);
    }
  });
}

function players() {
  if (!state) return [];
  return [state.players.opponent, state.players.human].filter(Boolean);
}

function cardsFor(player) {
  return [...player.hand, ...player.field, ...player.base, ...(player.trash || [])];
}

function findPlayerBySide(side) {
  return players().find((player) => player.side === side) || null;
}

function findCardByIid(iid) {
  const id = Number(iid);
  for (const player of players()) {
    const found = cardsFor(player).find((card) => card.iid === id);
    if (found) return found;
  }
  return null;
}

function forceKey(force) {
  return `${force.ownerSide || ""}:${force.id}`;
}

function findForceByKey(key) {
  for (const player of players()) {
    const found = (player.forces || []).find((force) => forceKey(force) === key);
    if (found) return found;
  }
  return null;
}

function openCardDetail(iid) {
  selectedCardIid = Number(iid);
  selectedForceKey = null;
  selectedPlayerSide = null;
  selectedTrashSide = null;
  closePaymentEditor(false);
  closeFieldReplaceEditor(false);
  closeBaseReplaceEditor(false);
  closeColorlessBaseReplaceEditor(false);
  render();
}

function openForceDetail(key) {
  selectedForceKey = key;
  selectedCardIid = null;
  selectedPlayerSide = null;
  selectedTrashSide = null;
  closePaymentEditor(false);
  closeFieldReplaceEditor(false);
  closeBaseReplaceEditor(false);
  closeColorlessBaseReplaceEditor(false);
  render();
}

function openTrashDetail(side) {
  selectedTrashSide = side;
  selectedCardIid = null;
  selectedForceKey = null;
  selectedPlayerSide = null;
  closePaymentEditor(false);
  closeFieldReplaceEditor(false);
  closeBaseReplaceEditor(false);
  closeColorlessBaseReplaceEditor(false);
  render();
}

function openPlayerDetail(side) {
  selectedPlayerSide = side;
  selectedCardIid = null;
  selectedForceKey = null;
  selectedTrashSide = null;
  closePaymentEditor(false);
  closeFieldReplaceEditor(false);
  closeBaseReplaceEditor(false);
  closeColorlessBaseReplaceEditor(false);
  render();
}

function openCatalogCardDetail(cardId) {
  selectedCatalogCardId = cardId;
  render();
}

function closeCatalogCardDetail(rerender = true) {
  selectedCatalogCardId = null;
  if (rerender) render();
}

function closeCardDetail(rerender = true) {
  selectedCardIid = null;
  selectedForceKey = null;
  selectedPlayerSide = null;
  if (rerender) render();
}

function closeTrashDetail(rerender = true) {
  selectedTrashSide = null;
  if (rerender) render();
}

function openPaymentEditor(optionId) {
  const option = optionById(optionId);
  if (!isPaymentConfigurable(option)) {
    choose(optionId);
    return;
  }
  pendingPaymentOptionId = optionId;
  paymentSelectionIids = new Set(option.paymentDefaultIids || []);
  closeFieldReplaceEditor(false);
  closeBaseReplaceEditor(false);
  closeColorlessBaseReplaceEditor(false);
  closeTrashDetail(false);
  closeCardDetail(false);
  render();
}

function closePaymentEditor(rerender = true) {
  pendingPaymentOptionId = null;
  paymentSelectionIids.clear();
  if (rerender) render();
}

function openFieldReplaceEditor(sourceIid) {
  pendingFieldReplaceSourceIid = Number(sourceIid);
  closePaymentEditor(false);
  closeBaseReplaceEditor(false);
  closeColorlessBaseReplaceEditor(false);
  closeTrashDetail(false);
  closeCardDetail(false);
  render();
}

function closeFieldReplaceEditor(rerender = true) {
  pendingFieldReplaceSourceIid = null;
  if (rerender) render();
}

function openBaseReplaceEditor(sourceIid) {
  pendingBaseReplaceSourceIid = Number(sourceIid);
  closePaymentEditor(false);
  closeFieldReplaceEditor(false);
  closeColorlessBaseReplaceEditor(false);
  closeTrashDetail(false);
  closeCardDetail(false);
  render();
}

function closeBaseReplaceEditor(rerender = true) {
  pendingBaseReplaceSourceIid = null;
  if (rerender) render();
}

function openColorlessBaseReplaceEditor() {
  if (!colorlessBaseReplacementOptions().length) return;
  pendingColorlessBaseReplace = true;
  closePaymentEditor(false);
  closeFieldReplaceEditor(false);
  closeBaseReplaceEditor(false);
  closeTrashDetail(false);
  closeCardDetail(false);
  render();
}

function closeColorlessBaseReplaceEditor(rerender = true) {
  pendingColorlessBaseReplace = false;
  if (rerender) render();
}

function paymentRequiredCount(option) {
  return Object.values(option.paymentCost || {}).reduce((sum, value) => sum + Number(value || 0), 0);
}

function paymentCandidateValue(candidate) {
  const value = Number(candidate && candidate.manaValue);
  return Number.isFinite(value) && value > 0 ? value : 0;
}

function paymentSelectionValue(option) {
  const candidates = new Map((option && option.paymentCandidates || []).map((candidate) => [candidate.iid, candidate]));
  let total = 0;
  for (const iid of paymentSelectionIids) {
    const candidate = candidates.get(iid);
    const value = paymentCandidateValue(candidate);
    if (!candidate || value <= 0) return null;
    total += value;
  }
  return total;
}

function consumeSelectedPaymentColor(colorCounts, color, amount, colorlessAsAny) {
  let missing = Number(amount || 0);
  const direct = Math.min(colorCounts[color] || 0, missing);
  colorCounts[color] = (colorCounts[color] || 0) - direct;
  missing -= direct;
  if (missing > 0 && colorlessAsAny && color !== "COLORLESS") {
    const colorless = Math.min(colorCounts.COLORLESS || 0, missing);
    colorCounts.COLORLESS = (colorCounts.COLORLESS || 0) - colorless;
    missing -= colorless;
  }
  return missing <= 0;
}

function paymentSelectionIsValid(option) {
  if (!option) return false;
  const selectedValue = paymentSelectionValue(option);
  if (selectedValue == null || selectedValue < paymentRequiredCount(option)) return false;
  const candidates = new Map((option.paymentCandidates || []).map((candidate) => [candidate.iid, candidate]));
  const colorCounts = {};
  for (const iid of paymentSelectionIids) {
    const candidate = candidates.get(iid);
    if (!candidate) return false;
    colorCounts[candidate.color] = (colorCounts[candidate.color] || 0) + paymentCandidateValue(candidate);
  }
  for (const [color, amount] of Object.entries(option.paymentCost || {})) {
    if (color === "COLORLESS") continue;
    if (!consumeSelectedPaymentColor(colorCounts, color, amount, option.paymentColorlessAsAny)) return false;
  }
  const freeCost = Number((option.paymentCost || {}).COLORLESS || 0);
  return Object.values(colorCounts).reduce((sum, value) => sum + Number(value || 0), 0) >= freeCost;
}

function togglePaymentMana(iid) {
  const id = Number(iid);
  if (paymentSelectionIids.has(id)) paymentSelectionIids.delete(id);
  else paymentSelectionIids.add(id);
  render();
}

function resetPaymentSelection() {
  const option = optionById(pendingPaymentOptionId);
  paymentSelectionIids = new Set((option && option.paymentDefaultIids) || []);
  render();
}

function confirmPaymentSelection() {
  const option = optionById(pendingPaymentOptionId);
  if (!option || !paymentSelectionIsValid(option)) return;
  choose(option.id, { paymentBaseIids: [...paymentSelectionIids] });
}

function toggleMulliganSelection(iid) {
  const id = Number(iid);
  if (mulliganSelectedIids.has(id)) mulliganSelectedIids.delete(id);
  else mulliganSelectedIids.add(id);
  render();
}

function canMulliganSelect(card) {
  if (replayReadonlyMode) return false;
  return MultiplayerCardPolicy.canMulliganSelect(card, activePrompt(), state && state.humanSide, isOnlineDuel());
}

function cardTitle(card) {
  if (card.faceDown) return "CARD";
  return localizedName(card, card.cardId || "Card");
}

function cardImage(card) {
  const assetUrl = localizedCardAssetUrl(card);
  if (assetUrl) {
    return `<img src="${esc(assetUrl)}" alt="${esc(cardTitle(card))}">`;
  }
  return "";
}

function normalizeLineBreaks(value) {
  return String(value ?? "")
    .replaceAll("\r\n", "\n")
    .replaceAll("\\n", "\n")
    .replaceAll("/n", "\n");
}

function multiline(value) {
  return esc(normalizeLineBreaks(value)).replaceAll("\n", "<br>");
}

function cardEffectText(card) {
  return localizedAbility(card);
}

function visualPlaybackActive() {
  return Boolean(activeAnimationEvent || animationEventQueue.length || pendingVisualStateStillNeeded());
}

const OPEN_REVEAL_REASONS = new Set(["top_four", "top_cards", "top_deck_search", "deck_search"]);

function isOpenRevealRecord(reveal) {
  const reason = String(reveal && reveal.reason || "");
  return Boolean(
    reveal &&
    reveal.card &&
    (OPEN_REVEAL_REASONS.has(reason) || reason.startsWith("top"))
  );
}

function clearPublicRevealBatchTimer() {
  if (publicRevealBatchTimer) {
    clearTimeout(publicRevealBatchTimer);
    publicRevealBatchTimer = null;
  }
}

function schedulePublicRevealBatchDismiss() {
  clearPublicRevealBatchTimer();
  if (!activePublicReveal || !activePublicReveal.batch) return;
  publicRevealBatchTimer = setTimeout(() => {
    publicRevealBatchTimer = null;
    if (activePublicReveal && activePublicReveal.batch) closePublicReveal();
  }, 1200);
}

function activatePublicRevealIfIdle() {
  if (activePublicReveal || !publicRevealQueue.length || visualPlaybackActive()) return false;
  activePublicReveal = publicRevealQueue.shift() || null;
  schedulePublicRevealBatchDismiss();
  return Boolean(activePublicReveal);
}

function enqueuePublicReveals(reveals) {
  if (!reveals || !reveals.length) return;
  for (let index = 0; index < reveals.length;) {
    const first = reveals[index];
    if (!isOpenRevealRecord(first)) {
      publicRevealQueue.push(first);
      index += 1;
      continue;
    }
    const batch = [first];
    while (
      index + batch.length < reveals.length &&
      isOpenRevealRecord(reveals[index + batch.length]) &&
      reveals[index + batch.length].playerSide === first.playerSide
    ) {
      batch.push(reveals[index + batch.length]);
    }
    if (batch.length > 1 || String(first.reason || "").startsWith("top")) {
      publicRevealQueue.push({
        batch: true,
        cards: batch.map((reveal) => reveal.card),
        playerName: first.playerName,
        playerSide: first.playerSide,
        reason: first.reason,
      });
    } else {
      publicRevealQueue.push(first);
    }
    index += batch.length;
  }
  activatePublicRevealIfIdle();
}

function closePublicReveal() {
  clearPublicRevealBatchTimer();
  activePublicReveal = null;
  activatePublicRevealIfIdle();
  if (!activePublicReveal) scheduleAutoStep(AI_AUTO_VISUAL_POLL_MS);
  renderPreservingActiveViewScroll();
}

function enqueueAnimationEvents(events) {
  if (!events || !events.length) return;
  animationEventQueue.push(...events);
  if (!activeAnimationEvent) showNextAnimationEvent(false);
}

function animationEventDuration(event) {
  if (!event) return 0;
  if (event.type === "turn_begin") return 760;
  if (event.type === "phase") return 920;
  if (event.type === "dice_roll") return 3200;
  if (event.type === "rock_paper_scissors") return 3200;
  if (event.type === "effect") return 1200;
  if (event.type === "destroy") return 920;
  if (event.type === "draw") return 820;
  if (event.type === "shuffle") return 520;
  if (event.type === "attack") return 860;
  if (event.type === "block") return 1060;
  if (event.type === "zone_move") return 900;
  if (event.type === "damage" || event.type === "heal") return 840;
  if (event.type === "game_result") return 1800;
  return 1200;
}

function showNextAnimationEvent(rerender = true) {
  if (animationOverlayTimer) {
    clearTimeout(animationOverlayTimer);
    animationOverlayTimer = null;
  }
  const finishedEvent = activeAnimationEvent;
  settleFinishedAnimationEvent(finishedEvent);
  activeAnimationEvent = animationEventQueue.shift() || null;
  commitPendingVisualStateIfSettled();
  if (activeAnimationEvent) {
    if (activeAnimationEvent.type === "zone_move") {
      rememberZoneMoveSource(activeAnimationEvent);
    }
    if (activeAnimationEvent.type === "effect") {
      stagePendingVisualStateForEffect();
    }
    playBattleSfx(activeAnimationEvent);
    const duration = animationEventDuration(activeAnimationEvent);
    if (duration > 0) {
      animationOverlayTimer = setTimeout(() => showNextAnimationEvent(true), duration);
    }
  } else {
    if (commitPendingVisualState({ rerender })) return;
    hiddenZoneMoveSourceKeys.clear();
    activatePublicRevealIfIdle();
    scheduleAutoStep(AI_AUTO_VISUAL_POLL_MS);
  }
  if (rerender) render();
}

function animationEventAssetId(event) {
  if (!event) return null;
  if (event.type === "phase") {
    return {
      flash: "timing_flash",
      block: "timing_block",
    }[event.phase] || null;
  }
  if (event.type === "game_result") {
    return event.winnerSide === state?.humanSide ? "result_win" : "result_lose";
  }
  return null;
}

function animationEventLabel(event) {
  if (!event) return "";
  if (event.type === "turn_begin") return "Turn Begin";
  if (event.type === "phase") return String(event.phase || "").toUpperCase();
  if (event.type === "dice_roll") return `D6 ${event.value} / ${event.firstSeat || ""}`;
  if (event.type === "rock_paper_scissors") return t("onlineOpeningChoice");
  if (event.type === "damage") return `-${event.amount}`;
  if (event.type === "heal") return `+${event.amount}`;
  if (event.type === "effect") return cardTitle(event.card || {});
  if (event.type === "effect_target") return "Magic target";
  if (event.type === "destroy") return "Destroyed";
  if (event.type === "zone_move") return zoneMoveLabel(event);
  return event.type || "";
}

function animationEventLayerMode(event) {
  if (!event) return "none";
  if (event.type === "shuffle") return "none";
  if (event.type === "phase") return "none";
  if (event.type === "draw") return "board";
  if (
    event.type === "zone_move" ||
    event.type === "attack" ||
    event.type === "block" ||
    event.type === "damage" ||
    event.type === "heal" ||
    event.type === "destroy" ||
    event.type === "effect_target"
  ) {
    return "board";
  }
  return "overlay";
}

function boardSideForEventSide(side) {
  if (!state || !side) return "bottom";
  return side === state.humanSide ? "bottom" : "top";
}

function boardAnchorKey(...parts) {
  return parts.map((part) => part ?? "").join(":");
}

function boardAnchorCssName(...parts) {
  return boardAnchorKey(...parts)
    .toLowerCase()
    .replace(/[^a-z0-9_-]+/g, "-")
    .replace(/^-+|-+$/g, "") || "unknown";
}

function boardAnchorAttr(side, zone) {
  return `data-board-anchor="${esc(boardAnchorKey(side, zone))}"`;
}

function boardForceAnchorAttr(force) {
  if (!force || !force.id || !force.ownerSide) return "";
  return `data-board-force-anchor="${esc(boardAnchorKey(force.ownerSide, "force", force.id))}"`;
}

function boardCardAnchorAttr(card) {
  if (!card || !card.iid || !card.ownerSide) return "";
  return `data-board-card-anchor="${esc(boardAnchorKey(card.ownerSide, "card", card.iid))}"`;
}

function boardAnchorForZone(side, zone) {
  const boardSide = boardSideForEventSide(side);
  const zones = {
    top: {
      hand: [78, 9],
      deck: [12, 16],
      base: [26, 31],
      field: [48, 36],
      trash: [10, 46],
      removed: [18, 48],
      force: [88, 25],
      player: [86, 20],
    },
    bottom: {
      hand: [78, 91],
      deck: [12, 84],
      base: [26, 69],
      field: [48, 64],
      trash: [10, 54],
      removed: [18, 52],
      force: [88, 75],
      player: [86, 80],
    },
  };
  const sideZones = zones[boardSide] || zones.bottom;
  const point = sideZones[zone] || sideZones.field;
  return {
    side: boardSide,
    zone,
    x: point[0],
    y: point[1],
    cssX: `${point[0]}%`,
    cssY: `${point[1]}%`,
    varName: boardAnchorCssName(side || boardSide, zone || "field"),
  };
}

function cardAreaAnchorFallback(iid, side, area = "field") {
  const fallback = boardAnchorForZone(side, area);
  const player = findPlayerBySide(side);
  const cards = playerAreaCards(player, area) || [];
  const index = cards.findIndex((card) => String(card.iid || "") === String(iid || ""));
  if (index < 0 || !cards.length) return fallback;
  const spacing = { field: 8.4, base: 5.8, hand: 5.6 }[area] || 7;
  const offset = (index - ((cards.length - 1) / 2)) * spacing;
  const x = Math.max(4, Math.min(96, fallback.x + offset));
  const sign = offset >= 0 ? "+" : "-";
  return {
    ...fallback,
    zone: "card",
    x,
    cssX: `calc(${fallback.cssX} ${sign} ${Math.abs(offset)}%)`,
  };
}

function boardAnchorForCardInState(iid, side, fallbackZone = "field") {
  return cardAreaAnchorFallback(iid, side, fallbackZone);
}

function boardAnchorForCard(iid, side, fallbackZone = "field") {
  const fallback = boardAnchorForCardInState(iid, side, fallbackZone);
  if (!iid) return fallback;
  return {
    ...fallback,
    zone: "card",
    varName: boardAnchorCssName(side || fallback.side, "card", iid),
  };
}

function boardAnchorForForce(side, forceId) {
  const fallback = boardAnchorForZone(side, "force");
  if (!forceId) return fallback;
  return {
    ...fallback,
    zone: "force",
    varName: boardAnchorCssName(side || fallback.side, "force", forceId),
  };
}

function boardAnchorStyle(anchor, prefix = "anchor") {
  const fallbackX = anchor.cssX || `${anchor.x}%`;
  const fallbackY = anchor.cssY || `${anchor.y}%`;
  if (anchor.varName) {
    return `--${prefix}-x:var(--anchor-${anchor.varName}-x, ${esc(fallbackX)}); --${prefix}-y:var(--anchor-${anchor.varName}-y, ${esc(fallbackY)});`;
  }
  return `--${prefix}-x:${esc(fallbackX)}; --${prefix}-y:${esc(fallbackY)};`;
}

function refreshBoardAttackVectors(layer, anchorPoints) {
  const attacks = layer.querySelectorAll(".board-attack[data-from-anchor][data-to-anchor]");
  attacks.forEach((attack) => {
    const from = anchorPoints.get(attack.getAttribute("data-from-anchor"));
    const to = anchorPoints.get(attack.getAttribute("data-to-anchor"));
    if (!from || !to) return;
    const dx = to.x - from.x;
    const dy = to.y - from.y;
    attack.style.setProperty("--from-x", `${Math.round(from.x)}px`);
    attack.style.setProperty("--from-y", `${Math.round(from.y)}px`);
    attack.style.setProperty("--to-x", `${Math.round(to.x)}px`);
    attack.style.setProperty("--to-y", `${Math.round(to.y)}px`);
    attack.style.setProperty("--attack-length", `${Math.max(8, Math.round(Math.sqrt((dx * dx) + (dy * dy))))}px`);
    attack.style.setProperty("--attack-angle", `${Math.atan2(dy, dx) * 180 / Math.PI}deg`);
  });
}

function refreshBoardAnimationAnchors() {
  document.querySelectorAll(".board-animation-layer").forEach((layer) => {
    const board = layer.closest(".duel-board") || layer.parentElement;
    if (!board) return;
    const layerRect = layer.getBoundingClientRect();
    if (!layerRect.width || !layerRect.height) return;
    const anchorPoints = new Map();
    const measureAnchor = (element, key) => {
      if (!key) return;
      const varName = boardAnchorCssName(...key.split(":"));
      const rect = element.getBoundingClientRect();
      if (!rect.width && !rect.height) return;
      const x = rect.left - layerRect.left + rect.width / 2;
      const y = rect.top - layerRect.top + rect.height / 2;
      anchorPoints.set(key, { x, y });
      layer.style.setProperty(`--anchor-${varName}-x`, `${Math.round(x)}px`);
      layer.style.setProperty(`--anchor-${varName}-y`, `${Math.round(y)}px`);
    };
    const anchors = board.querySelectorAll("[data-board-anchor]");
    anchors.forEach((element) => {
      measureAnchor(element, element.getAttribute("data-board-anchor"));
    });
    const cardAnchors = board.querySelectorAll("[data-board-card-anchor]");
    cardAnchors.forEach((element) => {
      measureAnchor(element, element.getAttribute("data-board-card-anchor"));
    });
    const forceAnchors = board.querySelectorAll("[data-board-force-anchor]");
    forceAnchors.forEach((element) => {
      measureAnchor(element, element.getAttribute("data-board-force-anchor"));
    });
    refreshBoardAttackVectors(layer, anchorPoints);
  });
}

function queueBoardAnimationAnchorRefresh() {
  if (typeof requestAnimationFrame === "function") {
    requestAnimationFrame(refreshBoardAnimationAnchors);
  } else {
    refreshBoardAnimationAnchors();
  }
}

function setAppHtml(html) {
  app.innerHTML = html;
  hydrateHomeThemeVideo();
  syncHomeThemeIdle();
  queueBoardAnimationAnchorRefresh();
}

function clearHomeThemeTimer() {
  if (homeThemeTimer) {
    window.clearTimeout(homeThemeTimer);
    homeThemeTimer = null;
  }
}

function scheduleHomeThemeIdle() {
  clearHomeThemeTimer();
  if (appView !== "home" || homeThemeActive) return;
  homeThemeTimer = window.setTimeout(startHomeThemeVideo, HOME_THEME_IDLE_MS);
}

function syncHomeThemeIdle() {
  if (appView === "home") {
    scheduleHomeThemeIdle();
    return;
  }
  clearHomeThemeTimer();
  homeThemeActive = false;
}

function recordHomeActivity() {
  if (appView !== "home" || homeThemeActive) return;
  scheduleHomeThemeIdle();
}

function startHomeThemeVideo() {
  if (appView !== "home") return;
  clearHomeThemeTimer();
  stopBgm();
  homeThemeVideoError = null;
  homeThemeActive = true;
  render();
}

function stopHomeThemeVideo(renderAfter = true) {
  clearHomeThemeTimer();
  const video = app.querySelector("[data-home-theme-video]");
  if (video) {
    video.pause();
    video.currentTime = 0;
  }
  const wasActive = homeThemeActive;
  homeThemeActive = false;
  homeThemeVideoError = null;
  if (renderAfter && wasActive) {
    render();
    return;
  }
  scheduleHomeThemeIdle();
}

function hydrateHomeThemeVideo() {
  if (!homeThemeActive) return;
  const video = app.querySelector("[data-home-theme-video]");
  if (!video) return;
  video.muted = true;
  video.play().then(() => {
    video.muted = false;
    video.volume = 1;
    window.setTimeout(() => {
      if (!video.paused) return;
      video.muted = true;
      video.play().catch(() => {});
    }, 120);
  }).catch((error) => {
    homeThemeVideoError = error && error.message ? error.message : "Video unavailable";
  });
}

function renderBoardEventCard(card, className) {
  const safeCard = card || {};
  const art = localizedCardAssetUrl(safeCard) || "";
  const name = cardTitle(safeCard);
  return `
    <div class="${esc(className)}">
      ${art ? `<img src="${esc(art)}" alt="${esc(name)}">` : `<span>${esc(name.slice(0, 1) || "?")}</span>`}
    </div>
  `;
}

function renderBoardAnchoredDraw(event) {
  const from = boardAnchorForZone(event.side, "deck");
  const to = boardAnchorForZone(event.side, "hand");
  const count = Math.max(1, Math.min(Number(event.count || 1), 4));
  const back = drawCardBackUrl(event);
  const baseStyle = `${boardAnchorStyle(from, "from")} ${boardAnchorStyle(to, "to")} --draw-card-back:url(${esc(cssUrl(back))})`;
  return `
    <div class="board-draw" style="${baseStyle}">
      ${Array.from({ length: count }).map((_, index) => {
        const offset = Math.round((index - (count - 1) / 2) * 22);
        return `
          <span class="board-draw-card"
                style="--draw-index:${index}; --draw-delay:${index * 70}ms; --draw-offset:${offset}px">
            <span class="draw-card-face"></span>
          </span>
        `;
      }).join("")}
    </div>
  `;
}

function renderBoardAnchoredZoneMove(event) {
  if (event.summonFx === "graveyard") return renderBoardAnchoredGraveyardSummon(event);
  const summonFx = ["hand", "graveyard"].includes(event.summonFx) ? event.summonFx : "";
  const from = event.summonFx === "hand"
    ? boardAnchorForZone(event.side, "hand")
    : event.fromArea === "deck"
    ? boardAnchorForZone(event.side, event.fromArea || "field")
    : boardAnchorForCard(event.card && event.card.iid, event.side, event.fromArea || "field");
  const to = boardAnchorForZone(event.side, event.toArea || "field");
  const card = event.card || {};
  const art = localizedCardAssetUrl(card) || "";
  const name = cardTitle(card);
  return `
    <div class="board-zone-move ${esc(summonFx)}" style="${boardAnchorStyle(from, "from")} ${boardAnchorStyle(to, "to")}">
      <div class="board-zone-move-card">
        ${art ? `<img src="${esc(art)}" alt="${esc(name)}">` : `<span>${esc(name.slice(0, 1) || "?")}</span>`}
      </div>
    </div>
  `;
}

function renderBoardAnchoredGraveyardSummon(event) {
  const from = boardAnchorForZone(event.side, "trash");
  const to = boardAnchorForZone(event.side, "field");
  return `
    <div class="board-zone-move graveyard" style="${boardAnchorStyle(from, "from")} ${boardAnchorStyle(to, "to")}">
      <span class="board-graveyard-summon"></span>
      ${renderBoardEventCard(event.card, "board-zone-move-card")}
    </div>
  `;
}

function attackTargetAnchor(event) {
  if (event.targetKind === "player") return boardAnchorForZone(event.targetSide || event.side, "player");
  if (event.targetKind === "force") return boardAnchorForForce(event.targetSide || event.side, event.targetForceId);
  if (event.targetKind === "card") return boardAnchorForCard(event.targetCardIid, event.targetSide || event.side, "field");
  return boardAnchorForZone(event.targetSide || event.side, "field");
}

function effectTargetAnchor(event) {
  const target = event.target || {};
  const targetSide = event.targetSide || target.ownerSide || event.side;
  const targetKind = event.targetKind || target.targetKind;
  if (targetKind === "player") return boardAnchorForZone(targetSide, "player");
  if (targetKind === "force") return boardAnchorForForce(targetSide, event.targetForceId || target.forceId);
  if (targetKind === "card") {
    return boardAnchorForCard(
      event.targetCardIid || target.cardIid,
      targetSide,
      event.targetArea || target.area || "field",
    );
  }
  return boardAnchorForZone(targetSide, "field");
}

function attackSourceAnchorKey(event) {
  return event.attackerIid
    ? boardAnchorKey(event.side, "card", event.attackerIid)
    : boardAnchorKey(event.side, "field");
}

function attackTargetAnchorKey(event) {
  const targetSide = event.targetSide || event.side;
  if (event.targetKind === "player") return boardAnchorKey(targetSide, "player");
  if (event.targetKind === "force" && event.targetForceId) {
    return boardAnchorKey(targetSide, "force", event.targetForceId);
  }
  if (event.targetKind === "card" && event.targetCardIid) {
    return boardAnchorKey(targetSide, "card", event.targetCardIid);
  }
  return boardAnchorKey(targetSide, "field");
}

function boardAttackStyle(from, to) {
  const dx = to.x - from.x;
  const dy = to.y - from.y;
  const length = Math.max(8, Math.sqrt((dx * dx) + (dy * dy)));
  const angle = Math.atan2(dy, dx) * 180 / Math.PI;
  return `${boardAnchorStyle(from, "from")} ${boardAnchorStyle(to, "to")} --attack-length:${esc(length)}%; --attack-angle:${esc(angle)}deg;`;
}

function renderBoardAnchoredAttack(event, { persistent = false } = {}) {
  const from = boardAnchorForCard(event.attackerIid, event.side, "field");
  const to = attackTargetAnchor(event);
  const targetClass = `target-${event.targetKind || "unknown"}`;
  const persistentClass = persistent ? " persistent" : "";
  return `
    <div class="board-attack ${esc(targetClass)}${persistentClass}"
         data-attacker-iid="${esc(event.attackerIid || "")}"
         data-from-anchor="${esc(attackSourceAnchorKey(event))}"
         data-to-anchor="${esc(attackTargetAnchorKey(event))}"
         style="${boardAttackStyle(from, to)}">
      <span class="board-attack-diamonds"></span>
      <span class="board-attack-arrow"></span>
      ${persistent ? "" : renderBoardEventCard(event.attacker, "board-attack-projectile")}
      <span class="board-attack-target-ring"></span>
      ${persistent ? "" : `<span class="board-attack-impact"></span>`}
    </div>
  `;
}

function boardClashStyle(from, to) {
  const mid = {
    side: from.side,
    x: (from.x + to.x) / 2,
    y: (from.y + to.y) / 2,
  };
  return `${boardAttackStyle(from, to)} ${boardAnchorStyle(mid, "mid")}`;
}

function renderBoardAnchoredBlock(event) {
  const from = boardAnchorForCard(event.attackerIid, event.side, "field");
  const to = boardAnchorForCard(event.blockerIid, event.targetSide || event.side, "field");
  return `
    <div class="board-clash" style="${boardClashStyle(from, to)}">
      <span class="board-block-banner">BLOCK TIMING</span>
      <span class="board-block-shield"></span>
      <span class="board-block-cut"></span>
      ${renderBoardEventCard(event.attacker, "board-clash-card attacker")}
      ${renderBoardEventCard(event.blocker, "board-clash-card blocker")}
      <span class="board-clash-burst"></span>
    </div>
  `;
}

function lifeChangeAnchor(event) {
  if (event.targetKind === "force") return boardAnchorForForce(event.side, event.forceId);
  if (event.targetKind === "card") return boardAnchorForZone(event.side, "field");
  return boardAnchorForZone(event.side, "player");
}

function renderBoardAnchoredLifeChange(event) {
  const anchor = lifeChangeAnchor(event);
  const sign = event.type === "heal" ? "+" : "-";
  const targetKind = event.targetKind || "player";
  return `
    <span class="board-hit-burst ${esc(event.type)} ${esc(targetKind)}"
          style="${boardAnchorStyle(anchor)}"></span>
    <div class="board-life-float ${esc(event.type)} ${esc(targetKind)} ${esc(anchor.side)}"
         style="${boardAnchorStyle(anchor)}">
      ${esc(sign)}${esc(event.amount)}
    </div>
  `;
}

function renderBoardAnchoredEffectTarget(event) {
  const anchor = effectTargetAnchor(event);
  const targetKind = event.targetKind || (event.target && event.target.targetKind) || "target";
  const targetClass = `target-${boardAnchorCssName(targetKind)}`;
  return `
    <div class="board-effect-target ${esc(targetClass)} ${esc(anchor.side)}" style="${boardAnchorStyle(anchor)}">
      <span class="board-effect-target-ring"></span>
      <span class="board-effect-target-label">TARGET</span>
    </div>
  `;
}

function renderBoardAnchoredDestroy(event) {
  const card = event.card || {};
  const anchor = boardAnchorForCard(card.iid, event.side || card.ownerSide, event.fromArea || "field");
  return `
    <div class="board-destroy ${esc(anchor.side)}" style="${boardAnchorStyle(anchor)}">
      ${renderBoardEventCard(card, "board-destroy-card")}
      <span class="board-destroy-flash"></span>
      <span class="board-destroy-crack"></span>
      <span class="board-destroy-smoke"></span>
      <span class="board-destroy-label">${esc(t("destroyed"))}</span>
    </div>
  `;
}

function renderBoardPersistentAttackIndicator() {
  if (!state || !state.pendingAttack) return "";
  return renderBoardAnchoredAttack(state.pendingAttack, { persistent: true });
}

function renderBoardAnimationLayer({ replay = false } = {}) {
  const event = activeAnimationEvent;
  const persistentAttack = replay ? "" : renderBoardPersistentAttackIndicator();
  let body = "";
  if (event && animationEventLayerMode(event) === "board") {
    if (event.type === "draw") body = renderBoardAnchoredDraw(event);
    if (event.type === "zone_move") body = renderBoardAnchoredZoneMove(event);
    if (event.type === "attack") body = renderBoardAnchoredAttack(event);
    if (event.type === "block") body = renderBoardAnchoredBlock(event);
    if (event.type === "damage" || event.type === "heal") body = renderBoardAnchoredLifeChange(event);
    if (event.type === "effect_target") body = renderBoardAnchoredEffectTarget(event);
    if (event.type === "destroy") body = renderBoardAnchoredDestroy(event);
  }
  if (!body && !persistentAttack) return "";
  return `<div class="board-animation-layer ${replay ? "replay" : "live"}" aria-hidden="true">${persistentAttack}${body}</div>`;
}

function zoneLabel(area) {
  const labels = {
    hand: "HAND",
    deck: "DECK",
    base: "BASE",
    field: "FIELD",
    trash: "TRASH",
    removed: "REMOVED",
  };
  return labels[area] || String(area || "").toUpperCase();
}

function zoneMoveLabel(event) {
  return `${zoneLabel(event.fromArea)} -> ${zoneLabel(event.toArea)}`;
}

function diceRollSeatLabel(kind) {
  const player = state && state.players ? state.players[kind] : null;
  if (state && state.mode === "multiplayer" && player && player.name) {
    return player.name;
  }
  if (state && state.humanSide) {
    return kind === "human" ? t("player") : t("opponent");
  }
  return player && player.side ? player.side : (kind === "human" ? "P1" : "P2");
}

function diceRollParityRule() {
  return `
    <div class="dice-roll-rule">
      ${esc(t("diceRollParityRule", {
        player: diceRollSeatLabel("human"),
        opponent: diceRollSeatLabel("opponent"),
      }))}
    </div>
  `;
}

function renderDiceRollOverlay(event) {
  const leftFirst = event.firstSeat === "left";
  const humanFirst = state && state.players && state.players.human
    ? state.players.human.isFirstPlayer
    : leftFirst;
  const opponentFirst = state && state.players && state.players.opponent
    ? state.players.opponent.isFirstPlayer
    : !leftFirst;
  const firstArt = uiAssetUrl("turn_first");
  const secondArt = uiAssetUrl("turn_second");
  const seat = (label, first) => `
    <div class="dice-seat ${first ? "first" : "second"}">
      ${first && firstArt
        ? `<img src="${esc(firstArt)}" alt="first">`
        : !first && secondArt
          ? `<img src="${esc(secondArt)}" alt="second">`
          : `<span>${esc(t(first ? "first" : "second"))}</span>`}
      <b>${esc(label)}</b>
    </div>
  `;
  return `
    <div class="visual-overlay dice-roll-overlay" aria-live="polite">
      <div class="visual-overlay-card dice-roll-card">
        <div class="dice-roll-value">D6 ${esc(event.value)}</div>
        ${diceRollParityRule()}
        <div class="dice-seat-row">
          ${seat(diceRollSeatLabel("human"), humanFirst)}
          ${seat(diceRollSeatLabel("opponent"), opponentFirst)}
        </div>
      </div>
    </div>
  `;
}

function renderLifeChangeOverlay(event) {
  const sign = event.type === "heal" ? "+" : "-";
  const target = [
    event.side,
    event.targetKind,
    event.forceId || "",
  ].filter(Boolean).join(" / ");
  return `
    <div class="visual-overlay ${event.type === "heal" ? "heal" : "damage"}" aria-live="polite">
      <div class="visual-overlay-card life-floater">
        <span class="life-floater-target">${esc(target)}</span>
        <strong class="life-floater-amount">${esc(sign)}${esc(event.amount)}</strong>
      </div>
    </div>
  `;
}

function drawOverlaySide(event) {
  return event.side === (state && state.humanSide) ? "bottom" : "top";
}

function drawCardBackUrl(event) {
  const faceDown = ((event && event.cards) || []).find((card) => card && card.assetId === "card_back" && card.assetUrl);
  return (faceDown && faceDown.assetUrl) || "/assets/card_back";
}

function renderDrawOverlay(event) {
  const side = drawOverlaySide(event);
  const count = Math.max(1, Math.min(Number(event.count || 1), 4));
  const back = drawCardBackUrl(event);
  const cardStyle = `--draw-card-back:url(${esc(cssUrl(back))})`;
  return `
    <div class="visual-overlay draw-overlay ${esc(side)}" aria-hidden="true">
      ${Array.from({ length: count }).map((_, index) => {
        const offset = Math.round((index - (count - 1) / 2) * 18);
        return `
          <span class="draw-card-flight"
                style="${cardStyle}; --draw-index:${index}; --draw-delay:${index * 70}ms; --draw-offset:${offset}px">
            <span class="draw-card-face"></span>
          </span>
        `;
      }).join("")}
    </div>
  `;
}

function renderEffectTriggerOverlay(event) {
  const card = event.card || {};
  const art = localizedCardAssetUrl(card) || "";
  const name = cardTitle(card);
  const text = event.effectText || cardEffectText(card) || "Effect";
  return `
    <div class="visual-overlay effect-trigger-overlay" aria-live="polite">
      <div class="visual-overlay-card effect-trigger-card">
        <div class="effect-trigger-art">
          ${art
            ? `<img src="${esc(art)}" alt="${esc(name)}">`
            : `<span>${esc(name.slice(0, 1) || "?")}</span>`}
        </div>
        <div class="effect-trigger-copy">
          <b>${esc(name)}</b>
          <span>${multiline(text)}</span>
        </div>
      </div>
    </div>
  `;
}

function renderDestroyOverlay(event) {
  const card = event.card || {};
  const art = localizedCardAssetUrl(card) || "";
  const name = cardTitle(card);
  return `
    <div class="visual-overlay destroy-overlay" aria-live="polite">
      <div class="visual-overlay-card destroy-card">
        <div class="destroy-stamp">DESTROYED</div>
        <div class="destroy-card-art">
          ${art
            ? `<img src="${esc(art)}" alt="${esc(name)}">`
            : `<span>${esc(name.slice(0, 1) || "?")}</span>`}
        </div>
        <b>${esc(name)}</b>
      </div>
    </div>
  `;
}

function renderZoneMoveOverlay(event) {
  const card = event.card || {};
  const art = localizedCardAssetUrl(card) || "";
  const name = cardTitle(card);
  return `
    <div class="visual-overlay zone-move-overlay" aria-live="polite">
      <div class="visual-overlay-card zone-move-card">
        <div class="zone-move-art">
          ${art
            ? `<img src="${esc(art)}" alt="${esc(name)}">`
            : `<span>${esc(name.slice(0, 1) || "?")}</span>`}
        </div>
        <div class="zone-move-copy">
          <b>${esc(name)}</b>
          <span>${esc(zoneMoveLabel(event))}</span>
        </div>
      </div>
    </div>
  `;
}

function renderGameResultOverlay(event) {
  const assetId = animationEventAssetId(event);
  const art = assetId ? uiAssetUrl(assetId) : null;
  const label = event.winnerSide ? `${t("winner")} ${event.winnerSide}` : t("drawResult");
  return `
    <div class="visual-overlay game-result-overlay" aria-live="polite">
      <div class="visual-overlay-card game-result-card">
        ${art
          ? `<img class="visual-overlay-art game-result-art" src="${esc(art)}" alt="${esc(label)}">`
          : `<span class="visual-overlay-text">${esc(label)}</span>`}
      </div>
    </div>
  `;
}

function renderRockPaperScissorsOverlay(event) {
  const choices = event.choices || {};
  const humanSide = (state && state.humanSide) || "P1";
  const opponentSide = humanSide === "P1" ? "P2" : "P1";
  const humanFirst = state && state.players && state.players.human
    ? state.players.human.isFirstPlayer
    : event.winnerSide === humanSide;
  const opponentFirst = state && state.players && state.players.opponent
    ? state.players.opponent.isFirstPlayer
    : event.winnerSide === opponentSide;
  const firstArt = uiAssetUrl("turn_first");
  const secondArt = uiAssetUrl("turn_second");
  const seat = (label, first, choice) => `
    <div class="dice-seat ${first ? "first" : "second"}">
      ${first && firstArt
        ? `<img src="${esc(firstArt)}" alt="first">`
        : !first && secondArt
          ? `<img src="${esc(secondArt)}" alt="second">`
          : `<span>${esc(t(first ? "first" : "second"))}</span>`}
      <b>${esc(label)}</b>
      <span>${esc(choice ? t(choice) : "-")}</span>
    </div>
  `;
  return `
    <div class="visual-overlay dice-roll-overlay opening-choice-overlay" aria-live="polite">
      <div class="visual-overlay-card dice-roll-card">
        <div class="dice-roll-value">${esc(t("onlineOpeningChoice"))}</div>
        <div class="dice-seat-row">
          ${seat(diceRollSeatLabel("human"), humanFirst, choices[humanSide])}
          ${seat(diceRollSeatLabel("opponent"), opponentFirst, choices[opponentSide])}
        </div>
      </div>
    </div>
  `;
}

function renderAnimationOverlay() {
  const event = activeAnimationEvent;
  if (!event) return "";
  if (animationEventLayerMode(event) !== "overlay") return "";
  if (event.type === "dice_roll") return renderDiceRollOverlay(event);
  if (event.type === "rock_paper_scissors") return renderRockPaperScissorsOverlay(event);
  if (event.type === "effect") return renderEffectTriggerOverlay(event);
  if (event.type === "destroy") return renderDestroyOverlay(event);
  if (event.type === "draw") return renderDrawOverlay(event);
  if (event.type === "game_result") return renderGameResultOverlay(event);
  const assetId = animationEventAssetId(event);
  const art = assetId ? uiAssetUrl(assetId) : null;
  const tone = event.type === "heal" ? " heal" : event.type === "damage" ? " damage" : "";
  return `
    <div class="visual-overlay${tone}" aria-live="polite">
      <div class="visual-overlay-card">
        ${art
          ? `<img class="visual-overlay-art" src="${esc(art)}" alt="${esc(animationEventLabel(event))}">`
          : `<span class="visual-overlay-text">${esc(animationEventLabel(event))}</span>`}
      </div>
    </div>
  `;
}

function promptOptionAssetId(option) {
  if (!option) return null;
  if (option.kind === "end_turn") return "button_turn_end";
  if (option.kind === "flash_pass" || option.kind === "no_block") return "button_pass";
  return null;
}

function promptOptionLabel(option) {
  if (!option) return "";
  if (option.kind === "effect_target_skip") {
    const prompt = activePrompt();
    if (prompt && prompt.choiceKind === "top3_magic") return t("addNoMagicCards");
    if (prompt && (prompt.revealedCards || []).length &&
        !(prompt.options || []).some(isRenderableEffectPromptTarget)) {
      return t("finishInspect");
    }
  }
  if (option.reorderPosition === "top") return t("deckTopChoice");
  if (option.reorderPosition === "bottom") return t("deckBottomChoice");
  if (option.kind === "end_turn") return t("endTurn");
  if (option.kind === "flash_pass" || option.kind === "no_block" || option.kind === "skip_mana") return t("pass");
  if (option.id === "keep") return t("keep");
  if (option.id === "redraw_selected" || option.id === "redraw") return t("redraw");
  return option.label || option.kind || "";
}

function renderPromptButton(option, index = 0) {
  const assetId = promptOptionAssetId(option);
  const art = assetId ? uiAssetUrl(assetId) : null;
  const visualClass = art ? " action-art-button" : "";
  const actionClass = option.kind === "end_turn" ? " end-turn-action" : "";
  const primary = index === 0 ? " primary" : "";
  const label = promptOptionLabel(option);
  return `
    <button class="${primary}${visualClass}${actionClass}" data-option="${esc(option.id)}" title="${esc(label)}" aria-label="${esc(option.label)}">
      ${art ? `<img class="action-art" src="${esc(art)}" alt="${esc(label)}">` : ""}
      <span class="action-label">${esc(label)}</span>
    </button>
  `;
}

function cardZoneCanBeRested(area) {
  return area === "field" || area === "base";
}

function cardCanBeRested(card) {
  return Boolean(card && cardZoneCanBeRested(card.area));
}

function isActiveZoneMoveSourceCard(card) {
  if (card && hiddenZoneMoveSourceKeys.has(zoneMoveSourceKey(card.iid, card.area))) return true;
  if (!card || !activeAnimationEvent || activeAnimationEvent.type !== "zone_move") return false;
  if (activeAnimationEvent.fromArea === "deck") return false;
  const eventCard = activeAnimationEvent.card || {};
  return String(eventCard.iid || "") === String(card.iid || "");
}

function renderCard(card, size = "") {
  const interactive = MultiplayerCardPolicy.isCardInteractive(card, state && state.humanSide, isOnlineDuel());
  const actions = actionOptionsForCard(card);
  const blessSourceActions = blessActionsForMana(card);
  const blessTargetActions = blessActionsForTarget(card);
  const legal = actions.length ? " legal" : "";
  const blessSource = blessSourceActions.length ? " bless-source-ready" : "";
  const blessTarget = blessTargetActions.length ? " bless-target-ready" : "";
  const playable = isPlayableCard(card) ? " playable" : "";
  const rested = cardCanBeRested(card) && card.rested ? " rested" : "";
  const movingSource = isActiveZoneMoveSourceCard(card) ? " zone-moving-source" : "";
  const selected = Number(selectedCardIid) === Number(card.iid) ? " selected-card" : "";
  const mulliganSelectable = canMulliganSelect(card);
  const mulliganSelected = mulliganSelectable && mulliganSelectedIids.has(card.iid);
  const mulliganClass = mulliganSelected ? " mulligan-selected" : "";
  const classes = size ? ` ${size}` : "";
  const art = cardImage(card);
  const label = esc(cardTitle(card));
  const type = card.faceDown ? "hidden" : esc(card.type || "");
  const bp = card.effectiveBp ?? card.bp ?? "-";
  const dp = card.effectiveDp ?? card.dp ?? "-";
  const stats = card.faceDown ? "" : `<div class="card-stats"><span>${esc(bp)}</span><span>${esc(dp)}</span></div>`;
  const overlay = art && !card.faceDown
    ? `<div class="card-overlay"><span>${label}</span>${size ? `<b>${esc(bp)}/${esc(dp)}</b>` : ""}</div>`
    : "";
  const fieldStats = art && !card.faceDown && !size
    ? `<div class="card-field-stats"><span>BP ${esc(bp)}</span><span>DP ${esc(dp)}</span></div>`
    : "";
  const actionBadge = actions.length ? `<div class="card-action-dot"></div>` : "";
  const blessDragAttrs = blessSourceActions.length
    ? `data-bless-source-iid="${esc(card.iid)}"`
    : "";
  const blessTargetAttr = blessTargetActions.length
    ? `data-bless-target-iid="${esc(card.iid)}"`
    : "";
  const mulliganToggle = mulliganSelectable
    ? `<button class="mulligan-toggle" data-mulligan-iid="${esc(card.iid)}" aria-label="${esc(t("selectForMulligan"))}"></button>`
    : "";
  const cardAnchor = boardCardAnchorAttr(card);
  const interactionAttrs = interactive ?
    `role="button" tabindex="0" data-card-iid="${esc(card.iid)}" title="${label}"`
    : `aria-hidden="true"`;
  return `
    <div class="card${classes}${legal}${playable}${blessSource}${blessTarget}${rested}${selected}${mulliganClass}${movingSource}" ${cardAnchor}
         ${interactionAttrs} ${blessDragAttrs} ${blessTargetAttr}>
      ${art}
      ${actionBadge}
      ${mulliganToggle}
      ${overlay}
      ${fieldStats}
      ${art ? "" : `
        <div class="card-fallback">
          <div class="card-type">${type}</div>
          <div class="card-name">${label}</div>
          ${stats}
        </div>
      `}
      ${renderCardHoverActions(card, actions)}
    </div>
  `;
}

function renderForce(force) {
  const option = optionForForce(force);
  const legal = option ? " legal" : "";
  const destroyed = force.destroyed ? " destroyed" : "";
  const rested = force.rested ? " rested" : "";
  const key = forceKey(force);
  const title = forceTitle(force);
  const actionLabel = option && option.kind === "effect_target" ? t("selectAsEffectTarget") : t("attack");
  const forceAssetUrl = localizedForceAssetUrl(force);
  const art = forceAssetUrl
    ? `<img src="${esc(forceAssetUrl)}" alt="${esc(title)}">`
    : `<div class="force-art-fallback">F</div>`;
  const forceAnchor = boardForceAnchorAttr(force);
  return `
    <div class="force${legal}${destroyed}${rested}" role="button" tabindex="0"
         data-force-key="${esc(key)}" data-board-anchor="${esc(boardAnchorKey(force.ownerSide, "force"))}" ${forceAnchor} title="${esc(title)}">
      ${art}
      <div class="force-name">${esc(title)}</div>
      <div class="force-life">${force.destroyed ? "X" : esc(force.life)}</div>
      ${option ? `
        <div class="force-hover-actions">
          <button class="force-hover-action" data-option="${esc(option.id)}">${esc(actionLabel)}</button>
        </div>
      ` : ""}
    </div>
  `;
}

function lifeMax(entity) {
  return entity && entity.maxLife ? entity.maxLife : 10;
}

function movementRightLabel(player) {
  const current = player && player.movementRightCount != null ? player.movementRightCount : 0;
  const total = player && player.movementRightTotal != null ? player.movementRightTotal : current;
  return `${esc(current)}/${esc(total)}`;
}

function colorPips(summary, showEmpty = true) {
  const entries = Object.entries(summary.colors || {});
  if (!entries.length) return showEmpty ? `<span class="pip empty-pip">0</span>` : "";
  return entries.map(([color, count]) => `<span class="pip ${esc(color)}">${esc(count)}</span>`).join("");
}

function renderEmptyZone(label, count = 5, mini = false) {
  const slots = Array.from({ length: count }, () => `<i></i>`).join("");
  return `<div class="zone-empty${mini ? " mini" : ""}">${slots}<span>${esc(label)}</span></div>`;
}

function renderRow(cards, size = "", emptyLabel = "empty", slotCount = 5) {
  if (!cards.length) return renderEmptyZone(emptyLabel, slotCount, size === "mini");
  return cards.map((card) => renderCard(card, size)).join("");
}

function renderZone(title, metaHtml, bodyHtml, className, legal = false, anchorSide = null, anchorZone = null) {
  const anchor = anchorSide && anchorZone ? ` ${boardAnchorAttr(anchorSide, anchorZone)}` : "";
  return `
    <div class="zone-band ${className}${legal ? " legal" : ""}"${anchor}>
      <div class="zone-label">
        ${title ? `<span>${esc(title)}</span>` : ""}
        ${metaHtml ? `<div class="zone-meta">${metaHtml}</div>` : ""}
      </div>
      <div class="zone-cards">
        ${bodyHtml}
      </div>
    </div>
  `;
}

function renderBaseLane(player) {
  const legal = player.base.some((card) => optionForCard(card));
  const activeManaLabel = t("activeMana", { ready: player.baseSummary.ready, total: player.baseSummary.total });
  const activeManaLegacyLabel = `Active ${esc(player.baseSummary.ready)} / ${esc(player.baseSummary.total)}`;
  const meta = `
    <span>${esc(activeManaLabel || activeManaLegacyLabel)}</span>
    <span class="pips">${colorPips(player.baseSummary, false)}</span>
  `;
  return renderZone("", meta, renderRow(player.base, "mini", "", 10), "base-zone base-lane", legal, player.side, "base");
}

function renderBattlefield(player, side) {
  const legal = player.field.some((card) => optionForCard(card));
  const meta = `<span>${esc(player.field.length)}/5</span>`;
  return renderZone(t("battleField"), meta, renderRow(player.field, "", t("noMinions"), 5), `field-zone battlefield ${side}`, legal, player.side, "field");
}

function renderHandFan(player, side) {
  const handCount = player.hand.length;
  const handFanStyle = side === "bottom"
    ? ` style="--hand-count:${Math.max(2, handCount)}"`
    : "";
  const cards = player.hand.length
    ? player.hand.map((card, index) => `
        <div class="hand-slot" style="--i:${index}; --n:${handCount}; --fan-angle:${side === "bottom" ? ((index - (handCount - 1) / 2) * 1.6).toFixed(2) : "0"}deg">
          ${renderCard(card, side === "bottom" ? "hand-card" : "opponent-hand-card")}
        </div>
      `).join("")
    : `<div class="empty">${esc(t("noCards"))}</div>`;
  return `
    <div class="hand-fan ${side}" data-board-anchor="${esc(boardAnchorKey(player.side, "hand"))}">
      <div class="hand-count">${esc(t("zoneHand"))} ${esc(player.handCount)}</div>
      <div class="hand-cards"${handFanStyle}>${cards}</div>
    </div>
  `;
}

function renderTrashPile(player) {
  const cards = player.trash || [];
  const topCard = cards[cards.length - 1] || null;
  const topArt = topCard
    ? cardImage(topCard) || `<div class="trash-stack-fallback">${esc(cardTitle(topCard)).slice(0, 1)}</div>`
    : `<div class="trash-stack-fallback">0</div>`;
  return `
    <div class="trash-zone" data-board-anchor="${esc(boardAnchorKey(player.side, "trash"))}">
      <div class="trash-title">${esc(t("trash"))} ${esc(player.trashCount || 0)}</div>
      <button class="trash-stack ${cards.length ? "has-cards" : ""}"
              data-trash-side="${esc(player.side)}"
              ${cards.length ? "" : "disabled"}
              title="${esc(t("trash"))} ${esc(player.trashCount || 0)}">
        <span class="trash-stack-art">${topArt}</span>
        <span class="trash-stack-count">${esc(player.trashCount || 0)}</span>
      </button>
    </div>
  `;
}

function renderDeckPile(player) {
  const tier = player.deckVisualTier || "empty";
  const assetId = `deck_${tier}`;
  const art = uiAssetUrl(assetId);
  return `
    <div class="deck-pile deck-${esc(tier)}" data-board-anchor="${esc(boardAnchorKey(player.side, "deck"))}" title="${esc(t("zoneDeck"))} ${esc(player.deckCount)}">
      ${art
        ? `<img class="deck-pile-art" src="${esc(art)}" alt="${esc(t("zoneDeck"))} ${esc(player.deckCount)}">`
        : `<span class="deck-pile-fallback">${esc(t("zoneDeck"))}</span>`}
      <span class="deck-pile-count">${esc(player.deckCount)}</span>
    </div>
  `;
}

function localizedPhase(value) {
  const key = {
    start: "phaseStart",
    refresh: "phaseRefresh",
    draw: "phaseDraw",
    mana: "phaseMana",
    main: "phaseMain",
    end: "phaseEnd",
    end_turn: "phaseEnd",
  }[String(value || "").toLowerCase()];
  return key ? t(key) : String(value || "");
}

function localizedMode(value) {
  const key = {
    "human-vs-ai": "modeHumanAi",
    god: "godView",
    "ai-vs-ai": "modeAiVsAi",
    multiplayer: "onlineGame",
  }[String(value || "").toLowerCase()];
  return key ? t(key) : String(value || "");
}

function renderDuelBrand() {
  const logo = uiAssetUrl("logo_zztitle");
  return `
    <div class="brand duel-brand">
      ${logo
        ? `<img class="brand-logo duel-brand-logo" src="${esc(logo)}" alt="ZENONZARD">`
        : `<strong>ZENONZARD</strong>`}
      <div class="meta duel-status-meta">
        <span>${esc(localizedMode(state.mode))}</span>
        <span>${esc(t("turn"))} ${esc(state.turn)}</span>
      </div>
    </div>
  `;
}

function onlineTurnOrderBadge(player) {
  if (!isOnlineDuel() || !player || typeof player.isFirstPlayer !== "boolean") return "";
  return `<em class="turn-order-badge ${player.isFirstPlayer ? "first" : "second"}">${esc(t(player.isFirstPlayer ? "first" : "second"))}</em>`;
}

function renderAvatar(player, top = false) {
  const option = optionForPlayer(player);
  const click = ` role="button" tabindex="0" data-player-side="${esc(player.side)}" data-board-anchor="${esc(boardAnchorKey(player.side, "player"))}"${option ? ` data-option="${esc(option.id)}"` : ""}`;
  const initial = esc(player.name.slice(0, 1) || "P");
  return `
    <div class="avatar ${top ? "top" : "bottom"}"${click}>
      <div class="avatar-ring">
        <span>${initial}</span>
      </div>
      <div class="avatar-info">
        <b>${esc(player.name)}</b>
        ${onlineTurnOrderBadge(player)}
        <span>${esc(t("life"))} ${esc(player.life)}/${esc(lifeMax(player))}</span>
      </div>
    </div>
  `;
}

function renderCodemanHalfbody(codeman, className, fallback = "P") {
  const art = codeman && (codeman.portraitUrl || codeman.assetUrl || codeman.thumbnailUrl);
  if (art) {
    return `<img class="${esc(className)}" src="${esc(art)}" alt="${esc(characterTitle(codeman))}">`;
  }
  return `<span>${esc(fallback)}</span>`;
}

function renderPilotIdentity(player, top = false) {
  const codeman = player.profile && player.profile.codeman;
  if (!codeman) return renderAvatar(player, top);
  const option = optionForPlayer(player);
  const click = ` role="button" tabindex="0" data-player-side="${esc(player.side)}" data-board-anchor="${esc(boardAnchorKey(player.side, "player"))}"${option ? ` data-option="${esc(option.id)}"` : ""}`;
  const initial = player.name.slice(0, 1) || "P";
  const canRequestAdvice = !replayReadonlyMode && !top;
  const adviceButton = canRequestAdvice
    ? `<button class="pilot-advice-button" type="button" data-ai-advice title="${esc(t("aiAdvicePrefix"))}">AI</button>`
    : "";
  return `
    <div class="pilot-codeman-panel ${top ? "top" : "bottom"}"${click}
         data-codeman-id="${esc(codeman.id || "")}"
         style="--pilot-accent:${esc(codeman.color || "#32d5c8")}">
      ${adviceButton}
      <div class="pilot-codeman-stage" data-player-detail="${esc(player.side)}">
        ${renderCodemanHalfbody(codeman, "pilot-codeman-art", initial)}
      </div>
      <div class="pilot-codeman-copy">
        <strong>${esc(characterTitle(codeman))}</strong>
      </div>
      <div class="pilot-status-badge pilot-life-badge">
        ${onlineTurnOrderBadge(player)}
        <span>${esc(t("life"))} ${esc(player.life)}/${esc(lifeMax(player))}</span>
      </div>
    </div>
  `;
}

function renderCockpit(player, side, error = null) {
  const top = side === "top";
  const forces = `<div class="forces">${player.forces.map(renderForce).join("")}</div>`;
  return `
    <section class="cockpit ${top ? "top" : "bottom"}">
      <div class="cockpit-hud ${top ? "opponent-hud" : "human-hud"}">
        <div class="cockpit-deck-dock">${renderDeckPile(player)}</div>
        <div class="cockpit-identity">${renderPilotIdentity(player, top)}</div>
        <div class="cockpit-trash-dock">${renderTrashPile(player)}</div>
        <div class="cockpit-force-row">${forces}</div>
        ${renderHandFan(player, top ? "top" : "bottom")}
        ${top ? "" : `
          <div class="cockpit-command-row command-stack">
            ${renderPrompt(error)}
          </div>
        `}
      </div>
    </section>
  `;
}

function renderAiAdvice() {
  const prompt = activePrompt();
  if (!prompt) return "";
  if (aiAdviceLoading) {
    return `<div class="prompt-advice">${esc(t("aiAdviceThinking"))}</div>`;
  }
  if (aiAdviceError) {
    return `<div class="prompt-advice prompt-advice-error">${esc(aiAdviceError)}</div>`;
  }
  if (!aiAdvice || aiAdvice.promptId !== prompt.id) return "";
  return `<div class="prompt-advice" title="${esc(localizedAdviceReason(aiAdvice))}">${esc(localizedAdviceMessage(aiAdvice, prompt))}</div>`;
}

function adviceUnavailableText(aiAdvice) {
  const code = aiAdvice && aiAdvice.code;
  if (code === "no_prompt") return t("aiAdviceNoPrompt");
  if (code === "unsupported_prompt") return t("aiAdviceUnsupportedPrompt");
  if (code === "no_codeman") return t("aiAdviceNeedsCodeman");
  if (code === "not_user_turn") return t("aiAdviceNotUserTurn");
  if (code === "no_options") return t("aiAdviceNoOptions");
  return t("aiAdviceUnavailable");
}

function localizedAdviceReason(advice) {
  if (!advice || !advice.available) return adviceUnavailableText(advice);
  const ranked = advice.alternatives || [];
  if (ranked.length < 2) return t("aiAdviceBest");
  const gap = Number(ranked[0].score || 0) - Number(ranked[1].score || 0);
  if (gap >= 0.5) return t("aiAdviceStrongLead");
  if (gap >= 0.1) return t("aiAdviceSmallLead");
  return t("aiAdviceCloseScore");
}

function localizedAdviceOptionLabel(advice, prompt = activePrompt()) {
  const option = prompt && (prompt.options || []).find((item) => item.id === advice.optionId);
  if (!option) return advice.label || "";
  const cardIid = option.iid ?? option.cardIid ?? option.attacker_iid;
  const card = cardIid != null ? findCardByIid(cardIid) : null;
  if (card && isCardActionOption(option)) {
    return `${cardActionLabel(option, card)}《${cardTitle(card)}》`;
  }
  if (option.kind === "force_base_choice" || option.kind === "effect_target") {
    return localizedName(option, option.label || option.kind || "");
  }
  if (option.kind === "player") {
    const player = findPlayerBySide(option.side);
    return player ? `${t("selectAttackTarget")}：${player.name}` : promptOptionLabel(option);
  }
  if (option.kind === "force") {
    const force = players()
      .flatMap((player) => player.forces || [])
      .find((item) => item.id === option.forceId && (!option.ownerSide || item.ownerSide === option.ownerSide));
    return force ? `${t("selectAttackTarget")}：${localizedName(force, force.nameJp || option.label)}` : promptOptionLabel(option);
  }
  if (option.kind === "minion" || option.kind === "blocker") {
    const target = option.cardIid != null ? findCardByIid(option.cardIid) : null;
    return target ? `${cardActionLabel(option, target)}《${cardTitle(target)}》` : promptOptionLabel(option);
  }
  return promptOptionLabel(option);
}

function localizedAdviceMessage(advice, prompt = activePrompt()) {
  if (!advice || !advice.available) return adviceUnavailableText(advice);
  return `${t("aiAdvicePrefix")}：${localizedAdviceOptionLabel(advice, prompt)}`;
}

function renderPrompt(error) {
  const prompt = activePrompt();
  if (replayReadonlyMode) {
    return `
      <section class="prompt">
        <div class="prompt-title">${esc(state && state.gameOver ? t("gameOver") : (prompt ? promptTitle(prompt) : t("codemanReplay")))}</div>
        <div class="actions">
          <div class="empty">${esc(t("noGlobalActions"))}</div>
        </div>
      </section>
    `;
  }
  if (state && state.gameOver) {
    if (isOnlineDuel()) {
      return `
        <section class="prompt">
          <div class="prompt-title">${esc(t("gameOver"))}</div>
          <div class="actions">
            <button class="primary" data-online-return-room>${esc(t("onlineGame"))}</button>
          </div>
        </section>
      `;
    }
    return `
      <section class="prompt">
        <div class="prompt-title">${esc(t("gameOver"))}</div>
        <div class="actions">
          <button class="primary" data-new="human-vs-ai">${esc(t("new"))}</button>
          <button data-new="god">${esc(t("god"))}</button>
          <button data-new="ai-vs-ai">${esc(t("aiVsAi"))}</button>
        </div>
      </section>
    `;
  }
  if (!prompt) {
    if (!shouldShowDuelAutoControls()) return "";
    return `
      <section class="prompt">
        <div class="prompt-title">${esc(t("auto"))}</div>
        <div class="actions">
          <button data-auto="toggle" class="${isAutoRunning() ? "active" : ""}">${isAutoRunning() ? esc(t("pause")) : esc(t("run"))}</button>
          <button data-step="1">${esc(t("step"))}</button>
        </div>
      </section>
    `;
  }
  if (prompt.kind === "blessing_base_replacement") return "";
  const mulliganCount = prompt.kind === "mulligan"
    ? `<div class="prompt-note">${esc(mulliganSelectedIids.size)} ${esc(t("selected"))}</div>`
    : "";
  const promptOptions = visiblePromptOptions(prompt);
  const colorlessReplaceHtml = prompt.kind === "main_action" && state && state.step === "mana" && colorlessBaseReplacementOptions().length
    ? `<button data-colorless-base-replace>${esc(t("placeColorlessMana"))}</button>`
    : "";
  const optionsHtml = prompt.kind === "force_base_choice"
    ? renderForceBaseChoiceOptions(promptOptions)
    : prompt.kind === "effect_target"
      ? ""
      : `${colorlessReplaceHtml}${promptOptions.map((option, index) => `
        ${renderPromptButton(option, index)}
      `).join("")}`;
  const hasFloatingActions = promptOptions.some((option) => Boolean(promptOptionAssetId(option)));
  const promptClass = hasFloatingActions ? "prompt has-floating-actions" : "prompt";
  const actionsClass = hasFloatingActions ? "actions prompt-floating-actions" : "actions";
  const hint = prompt.kind === "main_action"
    ? state.step === "mana"
      ? `<div class="prompt-note">${esc(t("manaPhase"))}</div>`
      : ""
    : prompt.kind === "effect_target"
      ? `<div class="prompt-note">${esc(t("effectTargetHint"))}</div>`
    : "";
  return `
    <section class="${promptClass}">
      <div>
        <div class="prompt-title">${esc(promptTitle(prompt))}</div>
        ${mulliganCount}
        ${hint}
        ${error ? `<div class="error">${esc(error.message || error.code)}</div>` : ""}
        ${renderAiAdvice()}
      </div>
      <div class="${actionsClass}">
        ${optionsHtml || `<div class="empty">${esc(t("noGlobalActions"))}</div>`}
      </div>
    </section>
  `;
}

function promptTitle(prompt) {
  if (prompt.kind === "main_action") return t("promptMainAction");
  if (prompt.kind === "mulligan") return t("promptMulligan");
  if (prompt.kind === "force_base_choice") return t("promptForceBaseChoice");
  if (prompt.kind === "effect_target" && prompt.choiceKind === "deck_base_minion") {
    return t("revealFromDeck");
  }
  if (prompt.kind === "effect_target" && prompt.choiceKind === "deck_top_or_bottom") {
    return t("inspectTopCards");
  }
  if (prompt.kind === "effect_target" && prompt.choiceKind === "top3_magic") {
    return t("inspectTopCards");
  }
  if (prompt.kind === "effect_target" && ["top_field_minion", "top2_field_minion", "top3_field_minion", "top4_card", "top2_card"].includes(prompt.choiceKind)) {
    return t("inspectTopCards");
  }
  if (prompt.kind === "effect_target") return t("chooseEffectTarget");
  return t("promptMainAction");
}

function renderForceBaseChoiceOptions(options) {
  return options.map((option, index) => {
    const title = localizedName(option, option.label || "?");
    const artUrl = localizedCardAssetUrl(option);
    const art = artUrl
      ? `<img src="${esc(artUrl)}" alt="${esc(title)}">`
      : `<span class="force-choice-fallback">${esc(title.slice(0, 1) || "?")}</span>`;
    const stats = option.type === "b_minion"
      ? `<span>${esc(option.bp ?? "-")}/${esc(option.dp ?? "-")}</span>`
      : "";
    return `
      <button class="force-choice-card ${index === 0 ? "primary" : ""}" data-option="${esc(option.id)}">
        ${art}
        <span class="force-choice-name">${esc(title)}</span>
        ${stats}
      </button>
    `;
  }).join("");
}

function renderEffectChoiceOptions(options) {
  return options.map((option, index) => {
    const title = localizedName(option, option.label || "?");
    const artUrl = localizedCardAssetUrl(option);
    const art = artUrl
      ? `<img src="${esc(artUrl)}" alt="${esc(title)}">`
      : `<span class="force-choice-fallback">${esc(title.slice(0, 1) || "?")}</span>`;
    const stats = option.type && option.type !== "magic"
      ? `<span>${esc(option.bp ?? "-")}/${esc(option.dp ?? "-")}</span>`
      : "";
    return `
      <button class="effect-choice-card ${index === 0 ? "primary" : ""}" data-option="${esc(option.id)}">
        ${art}
        <span class="force-choice-name">${esc(title)}</span>
        ${stats}
      </button>
    `;
  }).join("");
}

function renderEffectPromptModal() {
  const prompt = activePrompt();
  if (!prompt || prompt.kind !== "effect_target") return "";
  if (prompt.choiceKind === "deck_top_or_bottom") {
    const topOption = (prompt.options || []).find((option) => option.reorderPosition === "top");
    const bottomOption = (prompt.options || []).find((option) => option.reorderPosition === "bottom");
    if (!topOption || !bottomOption) return "";
    const inspectedCard = (prompt.revealedCards || []).find(
      (card) => Number(card.cardIid) === Number(topOption.cardIid)
    ) || topOption;
    const catalogCard = inspectedCard.cardId ? cardById(inspectedCard.cardId) : null;
    const topCard = catalogCard ? { ...catalogCard, ...inspectedCard } : inspectedCard;
    const actionsHtml = `
      <div class="card-detail-actions">
        <button class="card-detail-action primary" data-option="${esc(topOption.id)}">
          ${esc(t("deckTopChoice"))}
        </button>
        <button class="card-detail-action" data-option="${esc(bottomOption.id)}">
          ${esc(t("deckBottomChoice"))}
        </button>
      </div>
    `;
    const contextHtml = `
      <div class="field-replace-head">
        <div>
          <div class="payment-title">${esc(promptTitle(prompt))}</div>
          <div class="payment-note">${esc(t("deckTopOrBottomNote"))}</div>
        </div>
      </div>
    `;
    return renderCardDetail(topCard, {
      modalClass: "effect-prompt-modal",
      closeButton: false,
      contextHtml,
      actionsHtml,
      showCardActions: false,
      showDebugTools: false,
    });
  }
  const minimum = effectPromptMinimumCount(prompt);
  const maximum = effectPromptMaximumCount(prompt);
  const isMulti = maximum > 1;
  const selectedCount = effectTargetSelectionIds.size;
  const selectableByIid = new Map(
    prompt.options
      .filter((option) => option.cardIid)
      .map((option) => [Number(option.cardIid), option])
  );
  const selectableByTarget = new Map(
    prompt.options.map((option) => [effectTargetKey(option), option])
  );
  const sourceCards = (prompt.revealedCards && prompt.revealedCards.length)
    ? prompt.revealedCards
    : prompt.options.filter(isRenderableEffectPromptTarget);
  const skipOption = prompt.options.find((option) => option.kind === "effect_target_skip");
  return `
    <div class="effect-prompt-modal">
      <section class="effect-prompt-panel" role="dialog" aria-modal="true" aria-label="${esc(promptTitle(prompt))}">
        <div class="field-replace-head">
          <div>
            <div class="payment-title">${esc(promptTitle(prompt))}</div>
            <div class="payment-note">${esc(effectPromptNote(prompt))}</div>
          </div>
          <div class="effect-prompt-actions">
            ${skipOption ? `<button data-option="${esc(skipOption.id)}">${esc(promptOptionLabel(skipOption))}</button>` : ""}
            ${isMulti ? `
              <button class="primary" data-effect-target-confirm
                      ${selectedCount >= minimum && selectedCount <= maximum ? "" : "disabled"}>
                ${esc(t("confirm"))} ${esc(selectedCount)}/${esc(maximum)}
              </button>
            ` : ""}
          </div>
        </div>
        <div class="effect-prompt-grid">
          ${sourceCards.map((card, index) => renderEffectPromptCard(
            card,
            card.cardIid ? selectableByIid.get(Number(card.cardIid)) : selectableByTarget.get(effectTargetKey(card)),
            index,
            isMulti,
          )).join("")}
        </div>
      </section>
    </div>
  `;
}

function isRenderableEffectPromptTarget(option) {
  return Boolean(option && (
    option.cardIid ||
    option.forceId ||
    option.targetKind === "player" ||
    option.targetKind === "mana_color"
  ));
}

function effectTargetKey(option) {
  if (!option) return "";
  if (option.cardIid) return `card:${option.cardIid}`;
  if (option.forceId) return `force:${option.ownerSide || ""}:${option.forceId}`;
  if (option.targetKind === "player") return `player:${option.ownerSide || option.id || ""}`;
  if (option.targetKind === "mana_color") return `mana_color:${option.manaColor || option.id || ""}`;
  return option.id || "";
}

function effectPromptNote(prompt) {
  if (prompt.choiceKind === "top3_magic") return t("lookTop3MagicNote");
  if (prompt.allowVariableTargetCount) {
    return t("variableTargetNote", { min: effectPromptMinimumCount(prompt), max: effectPromptMaximumCount(prompt) });
  }
  if (effectPromptMaximumCount(prompt) > 1) {
    return t("multiTargetNote", { selected: effectTargetSelectionIds.size, max: effectPromptMaximumCount(prompt) });
  }
  const topWindowSize = {
    top_field_minion: 4,
    top2_field_minion: 2,
    top3_field_minion: 3,
    top4_card: 4,
    top2_card: 2,
  }[prompt.choiceKind];
  if (topWindowSize) return t("inspectTopCardsNote", { count: topWindowSize });
  if (prompt.choiceKind === "deck_base_minion") return t("deckBaseNote");
  return t("oneTargetNote");
}

function renderEffectPromptCard(card, option, index, isMulti = false) {
  const title = localizedName(card, card.label || card.cardId || "Card");
  const location = card.targetLabel || "";
  const artUrl = localizedCardAssetUrl(card);
  const restable = cardCanBeRested(card);
  const rested = restable && Boolean(card.rested);
  const art = card.type === "mana_color"
    ? `<span class="force-choice-fallback mana-color-choice ${esc(card.manaColor || "")}">${esc(title.slice(0, 1))}</span>`
    : artUrl
    ? `<img src="${esc(artUrl)}" alt="${esc(title)}">`
    : `<span class="force-choice-fallback">${esc(title.slice(0, 1))}</span>`;
  const restStatus = restable && card.type !== "force"
    ? `<span class="effect-choice-status">${esc(card.rested ? t("rested") : t("active"))}</span>`
    : "";
  const stats = card.type === "force"
    ? `<span>${esc(card.rested ? t("rested") : t("active"))} ${esc(card.life ?? "-")}/${esc(lifeMax(card))}</span>`
    : card.type === "mana_color"
    ? `<span>${esc(card.manaColor || card.label || "")}</span>`
    : card.type === "player"
    ? `<span class="player-life">${esc(card.life ?? "-")}/${esc(card.maxLife ?? "-")}</span>`
    : card.type === "mana_token"
    ? `<span>${esc(card.manaColor || card.type)}</span>`
    : card.type && card.type !== "magic"
    ? `<span>${esc(card.effectiveBp ?? card.bp ?? "-")}/${esc(card.effectiveDp ?? card.dp ?? "-")}</span>`
    : `<span>${esc(card.type || card.area || "")}</span>`;
  const selectable = Boolean(option);
  const selected = Boolean(option && effectTargetSelectionIds.has(option.id));
  const targetAttr = selectable
    ? (isMulti ? `data-effect-target-option="${esc(option.id)}"` : `data-option="${esc(option.id)}"`)
    : "disabled";
  return `
    <button class="effect-choice-card ${selectable ? "selectable" : "disabled"} ${selected ? "selected" : ""} ${rested ? "rested" : ""} ${!isMulti && index === 0 && selectable ? "primary" : ""}"
            ${targetAttr}>
      ${art}
      <span class="force-choice-name">${esc(title)}</span>
      ${location ? `<span class="effect-choice-location">${esc(location)}</span>` : ""}
      ${stats}
      ${restStatus}
    </button>
  `;
}

function battleLogRows() {
  if (!state) return [];
  if (Array.isArray(state.logEvents) && state.logEvents.length) {
    return state.logEvents.filter((row) => row != null);
  }
  return [];
}

function logLabel(table, key) {
  const lang = currentLanguage();
  return (table[lang] && table[lang][key]) || (table.zh && table.zh[key]) || key;
}

function logActionLabel(actionKind) {
  return logLabel(LOG_ACTION_LABELS, actionKind);
}

function localizedLogCardName(card) {
  if (!card) return "";
  return localizedName(card, card.nameJp || card.nameEn || card.cardId || "");
}

function localizedLogForceName(force) {
  if (!force) return "";
  return localizedName(force, force.nameJp || force.nameEn || force.id || "");
}

function localizedLogPlayerName(event, prefix = "actor") {
  const side = event && (event[`${prefix}Side`] || event.playerSide);
  const name = event && (event[`${prefix}Name`] || event.playerName);
  if (state && state.mode !== "god" && state.humanSide && side) {
    return side === state.humanSide ? t("player") : t("opponent");
  }
  return name || side || "";
}

function logReplacementText(card) {
  const name = localizedLogCardName(card);
  if (!name) return "";
  const lang = currentLanguage();
  if (lang === "ja") return `（${name}を${logLabel(LOG_EVENT_LABELS, "replace")}）`;
  if (lang === "en") return ` (${logLabel(LOG_EVENT_LABELS, "replace")} ${name})`;
  return `（${logLabel(LOG_EVENT_LABELS, "replace")} ${name}）`;
}

function formatLogAction(event, actor, action, cardName) {
  const replacement = logReplacementText(event.replacementCard);
  const targetSuffix = logTargetSuffix(event);
  if (!cardName) {
    if (event.newColor) return `${actor}: ${action} ${event.newColor}${replacement}${targetSuffix}`;
    return `${actor}: ${action}${replacement}${targetSuffix}`;
  }
  const lang = currentLanguage();
  if (lang === "ja") return `${actor}: ${cardName} ${action}${replacement}${targetSuffix}`;
  if (lang === "en") return `${actor}: ${action} ${cardName}${replacement}${targetSuffix}`;
  return `${actor}：${action}《${cardName}》${replacement}${targetSuffix}`;
}

function localizedLogEffectTarget(target) {
  if (!target) return "";
  const kind = target.targetKind || target.type;
  if (kind === "card" || (target.cardId && !target.forceId)) {
    return localizedLogCardName(target);
  }
  if (kind === "force") {
    return localizedName(target, target.nameJp || target.nameEn || target.forceId || target.id || "");
  }
  if (kind === "player") {
    const side = target.ownerSide || target.playerSide || target.side;
    if (state && state.mode !== "god" && state.humanSide && side) {
      return side === state.humanSide ? t("player") : t("opponent");
    }
    return target.nameJp || target.playerName || target.name || side || "";
  }
  if (kind === "mana_color") {
    return target.manaColor || target.nameJp || target.label || "";
  }
  return target.label || target.targetLabel || target.id || target.type || "";
}

function localizedLogTarget(target) {
  if (!target) return "";
  if (target.targetKind) return localizedLogEffectTarget(target);
  if (target.type === "player") return localizedLogPlayerName(target, "player");
  if (target.type === "force") return localizedLogForceName(target.force);
  if (target.type === "minion") return localizedLogCardName(target.card);
  return target.label || target.id || target.type || "";
}

function logTargetSuffix(event) {
  const targets = Array.isArray(event.targets) ? event.targets : event.target ? [event.target] : [];
  const targetText = targets.map(localizedLogTarget).filter(Boolean).join(" / ");
  if (!targetText) return "";
  const lang = currentLanguage();
  if (lang === "ja") return ` -> 対象：${targetText}`;
  if (lang === "en") return ` -> target: ${targetText}`;
  return ` -> 对象：${targetText}`;
}

function battleLogEventText(event) {
  if (typeof event === "string") return event;
  if (!event || typeof event !== "object") return String(event ?? "");
  const actor = localizedLogPlayerName(event);
  if (event.type === "action") {
    return formatLogAction(event, actor, logActionLabel(event.actionKind), localizedLogCardName(event.card));
  }
  if (event.type === "attack_target") {
    const attacker = localizedLogCardName(event.attacker);
    const target = localizedLogTarget(event.target);
    const action = logActionLabel("attack");
    return attacker ? `${actor}: ${attacker} ${action} ${target}` : `${actor}: ${action} ${target}`;
  }
  if (event.type === "block") {
    const blocker = localizedLogCardName(event.blocker);
    return blocker
      ? `${logLabel(LOG_EVENT_LABELS, "block")}: ${blocker}`
      : logLabel(LOG_EVENT_LABELS, "noBlock");
  }
  if (event.type === "force_base_choice") {
    const force = localizedLogForceName(event.force);
    const card = localizedLogCardName(event.card) || t("noCards");
    return `${actor}: ${force} ${logLabel(LOG_EVENT_LABELS, "forcePlaced")} ${card}`;
  }
  if (event.type === "reveal") {
    const reason = event.reason ? ` (${event.reason})` : "";
    return `${actor}: ${logLabel(LOG_EVENT_LABELS, "reveal")} ${localizedLogCardName(event.card)}${reason}`;
  }
  if (event.type === "effect_target") {
    return `${actor}: ${logLabel(LOG_EVENT_LABELS, "targetSelected")}${logTargetSuffix(event)}`;
  }
  if (event.type === "optional_effect") {
    return `${actor}: ${logLabel(LOG_EVENT_LABELS, event.used ? "usedOptional" : "skippedOptional")}`;
  }
  if (event.type === "game_over") {
    return logLabel(LOG_EVENT_LABELS, "gameOver");
  }
  return t("legacyLogUnavailable");
}

function battleLogText(row) {
  if (row && typeof row === "object" && row.rawText && !row.type) {
    return t("legacyLogUnavailable");
  }
  if (row && typeof row === "object") return battleLogEventText(row);
  if (typeof row === "string") return t("legacyLogUnavailable");
  return String(row ?? "");
}

function renderTopLog() {
  const rows = battleLogRows();
  const latest = rows.length ? battleLogText(rows[rows.length - 1]) : t("noBattleLog");
  return `
    <button class="topbar-log topbar-log-button" type="button" data-log-toggle
            aria-label="${esc(t("openBattleLog"))}" aria-haspopup="dialog"
            aria-expanded="${logModalOpen ? "true" : "false"}">
      <span class="topbar-log-icon" aria-hidden="true"><i></i><i></i><i></i></span>
      <span class="topbar-log-copy">
        <b>${esc(t("battleLog"))}</b>
        <span>${esc(latest)}</span>
      </span>
      <strong>${esc(rows.length)}</strong>
    </button>
  `;
}

function renderBattleLogModal() {
  if (!logModalOpen) return "";
  const rows = battleLogRows().map((row, index) => ({
    index: index + 1,
    text: battleLogText(row),
  })).reverse();
  return `
    <div class="battle-log-modal" data-log-close>
      <article class="battle-log-panel" role="dialog" aria-modal="true" aria-label="${esc(t("battleLog"))}">
        <header class="battle-log-head">
          <div>
            <span>${esc(t("latestLog"))}</span>
            <strong>${esc(t("battleLog"))}</strong>
          </div>
          <button type="button" data-log-close>${esc(t("close"))}</button>
        </header>
        <div class="battle-log-list">
          ${rows.length
            ? rows.map((row) => `
                <div class="battle-log-entry">
                  <span>${esc(row.index)}</span>
                  <p>${esc(row.text)}</p>
                </div>
              `).join("")
            : `<div class="empty">${esc(t("noBattleLog"))}</div>`}
        </div>
      </article>
    </div>
  `;
}

function cssUrl(value) {
  return String(value || "").replace(/["'\\\r\n()]/g, "");
}

function arenaPlaymatStyle(human, opponent) {
  const humanUrl = human && human.profile && human.profile.playmatUrl;
  const opponentUrl = opponent && opponent.profile && opponent.profile.playmatUrl;
  const rules = [];
  if (humanUrl) rules.push(`--human-playmat:url(${cssUrl(humanUrl)})`);
  if (opponentUrl) rules.push(`--opponent-playmat:url(${cssUrl(opponentUrl)})`);
  return rules.join(";");
}

function arenaPlaymatClass(human, opponent) {
  const hasHumanPlaymat = Boolean(human && human.profile && human.profile.playmatUrl);
  const hasOpponentPlaymat = Boolean(opponent && opponent.profile && opponent.profile.playmatUrl);
  return hasHumanPlaymat || hasOpponentPlaymat ? " has-playmat" : "";
}

function renderArena(human, opponent) {
  return `
    <section class="arena${arenaPlaymatClass(human, opponent)}" style="${esc(arenaPlaymatStyle(human, opponent))}">
      ${renderBaseLane(opponent)}
      ${renderBattlefield(opponent, "opponent")}
      ${renderBattlefield(human, "human")}
      ${renderBaseLane(human)}
    </section>
  `;
}

function renderDuelBoardShell(error = null, { readonly = false, replay = false, timelineHtml = "" } = {}) {
  const human = state.players.human;
  const opponent = state.players.opponent;
  if (selectedCardIid && !findCardByIid(selectedCardIid)) {
    selectedCardIid = null;
  }
  if (selectedForceKey && !findForceByKey(selectedForceKey)) {
    selectedForceKey = null;
  }
  if (selectedPlayerSide && !findPlayerBySide(selectedPlayerSide)) {
    selectedPlayerSide = null;
  }
  if (selectedTrashSide && !findPlayerBySide(selectedTrashSide)) {
    selectedTrashSide = null;
  }
  const readonlyBoard = readonly || replay;
  return `
    <div class="duel-board${readonlyBoard ? " replay-duel-board" : ""}">
      ${renderCockpit(opponent, "top")}
      ${renderArena(human, opponent)}
      ${renderCockpit(human, "bottom", error)}
      ${renderBoardAnimationLayer({ replay: readonlyBoard })}
    </div>
    ${timelineHtml || ""}
    ${renderCardDetail()}
    ${renderForceDetail()}
    ${renderPlayerDetail()}
    ${renderTrashDetail()}
    ${readonlyBoard ? "" : renderFieldReplaceEditor()}
    ${readonlyBoard ? "" : renderBaseReplaceEditor()}
    ${readonlyBoard ? "" : renderColorlessBaseReplaceEditor()}
    ${readonlyBoard ? "" : renderPaymentEditor()}
    ${readonlyBoard ? "" : renderEffectPromptModal()}
    ${readonlyBoard ? "" : renderPublicRevealModal()}
    ${readonlyBoard ? "" : renderBattleLogModal()}
    ${readonlyBoard ? "" : renderBattleDebugPanel()}
    ${renderAnimationOverlay()}
  `;
}

function renderDuelView(error = null) {
  const online = isOnlineDuel();
  return `
    <header class="topbar">
      ${renderDuelBrand()}
      ${renderTopLog()}
      <div class="controls">
        ${renderLanguageSwitch()}
        <button data-view="home">${esc(t("home"))}</button>
        ${online ? "" : `<button data-mode="human-vs-ai">${esc(t("human"))}</button>`}
        ${online ? "" : `<button data-mode="god">${esc(t("god"))}</button>`}
        ${online ? "" : `<button data-mode="ai-vs-ai">${esc(t("aiVsAi"))}</button>`}
        <button data-concede>${esc(t("concede"))}</button>
        ${!online && devModeEnabled() ? `<button data-battle-debug-toggle class="${battleDebugOpen ? "active" : ""}">DEBUG</button>` : ""}
        ${shouldShowDuelAutoControls()
          ? `<button data-auto="toggle" class="${isAutoRunning() ? "active" : ""}">${isAutoRunning() ? esc(t("pause")) : esc(t("auto"))}</button>`
          : ""}
        ${renderTopbarBgmControl()}
      </div>
    </header>
    ${online && multiplayerUi.status === "RECONNECTING"
      ? `<div class="online-reconnect-banner" role="status">${esc(t("onlineReconnecting"))}</div>`
      : ""}
    ${renderDuelBoardShell(error)}
  `;
}

function renderBattleDebugCard(card) {
  const titleText = localizedName(card, card.id);
  const title = esc(titleText);
  const artUrl = localizedCardAssetUrl(card);
  const art = artUrl
    ? `<img src="${esc(artUrl)}" alt="${title}">`
    : `<span>${esc((titleText || "?").slice(0, 1))}</span>`;
  const cost = card.officialCost || card.totalCost || "0";
  return `
    <button class="battle-debug-card" data-battle-debug-add="${esc(card.id)}" title="${title}">
      <span class="battle-debug-card-art">${art}</span>
      <span class="battle-debug-card-copy">
        <strong>${title}</strong>
        <small>${esc(localizedCardType(card))} / ${esc(localizedCardAttribute(card))} / ${esc(cost)}</small>
        <small>BP ${esc(card.bp ?? "-")} / DP ${esc(card.dp ?? "-")}</small>
      </span>
    </button>
  `;
}

function renderBattleDebugFilters() {
  const groups = battleDebugFilterGroups();
  if (!groups.length) return "";
  return `
    <div class="battle-debug-filter-grid">
      ${groups.map((group) => `
        <label>
          <span>${esc(localizedCatalogLabel(group, group.id))}</span>
          <select data-battle-debug-filter="${esc(group.id)}">
            <option value="">${esc(t("all"))}</option>
            ${(group.options || []).map((option) => `
              <option value="${esc(option.value)}" ${battleDebugFilters[group.id] === option.value ? "selected" : ""}>
                ${esc(localizedCatalogLabel(option))}
              </option>
            `).join("")}
          </select>
        </label>
      `).join("")}
    </div>
  `;
}

function renderBattleDebugForceTools() {
  const forceOptions = catalog.forces || [];
  const rows = battleDebugSides().map((side) => {
    const player = players().find((item) => item.side === side.id);
    const current = (player && player.forces) || [];
    const selects = [0, 1].map((index) => {
      const currentId = current[index] && current[index].id;
      return `
        <select data-battle-debug-force-select="${esc(side.id)}" data-force-index="${esc(index)}">
          ${forceOptions.map((force) => `
            <option value="${esc(force.id)}" ${force.id === currentId ? "selected" : ""}>
              ${esc(forceTitle(force))}
            </option>
          `).join("")}
        </select>
      `;
    }).join("");
    return `
      <div class="debug-force-row">
        <span>${esc(side.label)}</span>
        ${selects}
        <button data-battle-debug-force-apply="${esc(side.id)}">${esc(t("debugSetForce"))}</button>
      </div>
    `;
  }).join("");
  return `
    <details class="debug-force-tools">
      <summary>${esc(t("debugForceReplace"))}</summary>
      <div class="debug-force-body">
        ${rows}
      </div>
    </details>
  `;
}

function renderBattleDebugPanel() {
  if (!battleDebugOpen || !devModeEnabled()) return "";
  const cards = battleDebugCards();
  const sideOptions = battleDebugSides();
  const addRestedControl = cardZoneCanBeRested(battleDebugZone)
    ? `
        <label class="battle-debug-switch">
          <input type="checkbox" data-battle-debug-add-rested ${battleDebugRested ? "checked" : ""}>
          <span>${esc(t("rested"))}</span>
        </label>
      `
    : "";
  return `
    <aside class="battle-debug-panel" role="dialog" aria-label="Battle debug">
      <div class="battle-debug-head">
        <strong>DEBUG</strong>
        <button data-battle-debug-toggle>${esc(t("close"))}</button>
      </div>
      <button class="primary" data-battle-debug-fixed-board>${esc(t("debugFixedBoard"))}</button>
      <label class="battle-debug-switch">
        <input type="checkbox" data-battle-debug-control-both ${state && state.debugControlBoth ? "checked" : ""}>
        <span>${esc(t("debugGodControl"))}</span>
      </label>
      ${renderBattleDebugForceTools()}
      <div class="battle-debug-tools">
        <label>
          <span>${esc(t("debugSide"))}</span>
          <select data-battle-debug-side>
            ${sideOptions.map((side) => `
              <option value="${esc(side.id)}" ${side.id === battleDebugSide ? "selected" : ""}>${esc(side.label)}</option>
            `).join("")}
          </select>
        </label>
        <label>
          <span>${esc(t("debugZone"))}</span>
          <select data-battle-debug-zone>
            ${BATTLE_DEBUG_ZONES.map((zone) => `
              <option value="${esc(zone.id)}" ${zone.id === battleDebugZone ? "selected" : ""}>${esc(t(zone.labelKey))}</option>
            `).join("")}
          </select>
        </label>
        ${addRestedControl}
      </div>
      <div class="battle-debug-search-row">
        <input data-battle-debug-search value="${esc(battleDebugSearch)}" placeholder="${esc(t("debugSearchPlaceholder"))}">
        <button data-battle-debug-filter-reset>${esc(t("debugReset"))}</button>
        <button data-battle-debug-add="mana_token">${esc(t("debugAddMana"))}</button>
      </div>
      ${renderBattleDebugFilters()}
      <div class="battle-debug-card-list">
        ${cards.length ? cards.map((card) => renderBattleDebugCard(card)).join("") : `<div class="empty">${esc(t("noCards"))}</div>`}
      </div>
    </aside>
  `;
}

function renderBattleDebugCardTools(card) {
  if (replayReadonlyMode || !devModeEnabled() || !card || card.faceDown || !card.iid) return "";
  const nextRested = !card.rested;
  const restButton = cardCanBeRested(card)
    ? `
      <button data-battle-debug-rested="${esc(card.iid)}" data-rested="${esc(nextRested)}">
        ${card.rested ? esc(t("active")) : esc(t("rested"))}
      </button>
    `
    : "";
  return `
    <div class="debug-card-tools">
      <div class="debug-card-tools-title">Debug</div>
      ${restButton}
      ${BATTLE_DEBUG_ZONES.map((zone) => `
        <button data-battle-debug-move="${esc(card.iid)}" data-zone="${esc(zone.id)}">${esc(t(zone.labelKey))}</button>
      `).join("")}
    </div>
  `;
}

function activeEffectKindLabel(kind) {
  const table = ACTIVE_EFFECT_COPY[currentLanguage()] || ACTIVE_EFFECT_COPY.zh;
  return table[kind] || t("activeEffects");
}

function localizedKeywordName(keyword) {
  const table = KEYWORD_COPY[currentLanguage()] || KEYWORD_COPY.zh;
  return table[keyword] || String(keyword || "");
}

function activeEffectScopeLabel(scope) {
  const table = ACTIVE_EFFECT_COPY[currentLanguage()] || ACTIVE_EFFECT_COPY.zh;
  return table[scope] || "";
}

function activeEffectSource(effect) {
  if (effect.sourceCardId) {
    const card = cardById(effect.sourceCardId);
    return card ? localizedName(card, effect.sourceCardId) : effect.sourceCardId;
  }
  if (effect.sourceForceId) {
    const force = forceById(effect.sourceForceId);
    return force ? forceTitle(force) : effect.sourceForceId;
  }
  return "";
}

function activeEffectText(effect) {
  const bits = [];
  if (effect.bpDelta) bits.push(`BP ${effect.bpDelta > 0 ? "+" : ""}${effect.bpDelta}`);
  if (effect.dpDelta) bits.push(`DP ${effect.dpDelta > 0 ? "+" : ""}${effect.dpDelta}`);
  if (effect.amount) bits.push(`${activeEffectKindLabel("damage")} -${effect.amount}`);
  if (effect.keywords && effect.keywords.length) bits.push(effect.keywords.map(localizedKeywordName).join(", "));
  if (effect.scope) {
    const scope = activeEffectScopeLabel(effect.scope);
    if (scope) bits.push(scope);
  }
  const body = [activeEffectKindLabel(effect.kind), ...bits].join(" / ");
  const source = activeEffectSource(effect);
  return source ? `${source}: ${body}` : body;
}

function renderActiveEffects(effects) {
  const rows = (effects || []).filter(Boolean);
  if (!rows.length) return "";
  return `
    <div class="card-detail-active-effects">
      <div class="active-effect-title">${esc(t("activeEffects"))}</div>
      <div class="active-effect-list">
        ${rows.map((effect) => `<div class="active-effect-item">${esc(activeEffectText(effect))}</div>`).join("")}
      </div>
    </div>
  `;
}

function renderBlessingDetails(blessings) {
  const rows = (blessings || []).filter(Boolean);
  if (!rows.length) return "";
  return `
    <div class="card-detail-blessings">
      <div class="active-effect-title">${esc(t("blessingDetails"))}</div>
      <div class="blessing-detail-list">
        ${rows.map((blessing) => {
          const effect = cardEffectText(blessing);
          const bp = Number(blessing.bp || 0);
          const dp = Number(blessing.dp || 0);
          return `
            <div class="blessing-detail-item">
              <div class="blessing-detail-heading">${esc(t("blessingSource", { name: cardTitle(blessing) }))}</div>
              ${effect ? `<div class="blessing-detail-effect">${multiline(effect)}</div>` : ""}
              <div class="blessing-detail-stats">BP ${bp >= 0 ? "+" : ""}${esc(bp)} / DP ${dp >= 0 ? "+" : ""}${esc(dp)}</div>
            </div>
          `;
        }).join("")}
      </div>
    </div>
  `;
}

function renderCardDetailPanel(card, {
  closeButton = true,
  contextHtml = "",
  actionsHtml = null,
  showCardActions = true,
  showDebugTools = true,
} = {}) {
  const title = esc(cardTitle(card));
  const bp = card.effectiveBp ?? card.bp ?? "-";
  const dp = card.effectiveDp ?? card.dp ?? "-";
  const effect = cardEffectText(card);
  const art = cardImage(card) || `<div class="card-detail-fallback">${title}</div>`;
  const actions = actionsHtml !== null
    ? actionsHtml
    : (showCardActions ? renderCardDetailActions(card) : "");
  return `
    <article class="card-detail-panel" role="dialog" aria-modal="true" aria-label="${title}">
      ${closeButton ? `<button class="detail-close" data-close-detail>${esc(t("close"))}</button>` : ""}
      <div class="card-detail-art">${art}</div>
      <div class="card-detail-copy">
        ${contextHtml}
        <div class="card-detail-title">${title}</div>
        <div class="card-detail-meta">
          <span>${esc(card.type || "card")}</span>
          <span>${esc(bp)}/${esc(dp)}</span>
          <span>${esc(card.area || "")}</span>
        </div>
        ${effect ? `<div class="card-detail-effect">${multiline(effect)}</div>` : ""}
        ${renderBlessingDetails(card.blessings)}
        ${renderActiveEffects(card.activeEffects)}
        ${actions}
        ${showDebugTools ? renderBattleDebugCardTools(card) : ""}
      </div>
    </article>
  `;
}

function renderCardDetail(cardOverride = null, options = {}) {
  const card = cardOverride || (selectedCardIid ? findCardByIid(selectedCardIid) : null);
  if (!card) return "";
  const {
    modalClass = "card-detail-modal",
    modalAttributes = "data-close-detail",
    ...panelOptions
  } = options;
  return `
    <div class="${modalClass}"${modalAttributes ? ` ${modalAttributes}` : ""}>
      ${renderCardDetailPanel(card, panelOptions)}
    </div>
  `;
}

function renderForceDetail() {
  if (!selectedForceKey) return "";
  const force = findForceByKey(selectedForceKey);
  if (!force) return "";
  const title = esc(forceTitle(force));
  const effect = forceAbilityText(force);
  const forceAssetUrl = localizedForceAssetUrl(force);
  const art = forceAssetUrl
    ? `<img src="${esc(forceAssetUrl)}" alt="${title}">`
    : `<div class="card-detail-fallback">${title}</div>`;
  return `
    <div class="card-detail-modal force-detail-modal" data-close-detail>
      <article class="card-detail-panel force-detail-panel" role="dialog" aria-modal="true" aria-label="${title}">
        <button class="detail-close" data-close-detail>${esc(t("close"))}</button>
        <div class="card-detail-art force-detail-art">${art}</div>
        <div class="card-detail-copy">
          <div class="card-detail-title">${title}</div>
          <div class="card-detail-meta">
            <span>${esc(t("force"))}</span>
            <span>${esc(force.life)}/${esc(lifeMax(force))}</span>
            <span>${force.destroyed ? esc(t("destroyed")) : force.rested ? esc(t("rested")) : esc(t("active"))}</span>
            <span>${esc(force.ownerSide || "")}</span>
          </div>
          ${effect ? `<div class="card-detail-effect">${multiline(effect)}</div>` : ""}
          ${renderActiveEffects(force.activeEffects)}
        </div>
      </article>
    </div>
  `;
}

function renderPlayerDetail() {
  if (!selectedPlayerSide) return "";
  const player = findPlayerBySide(selectedPlayerSide);
  if (!player) return "";
  const title = esc(player.name || player.side || "Player");
  const codeman = player.profile && player.profile.codeman;
  const artUrl = codeman && (codeman.portraitUrl || codeman.assetUrl || codeman.thumbnailUrl);
  const art = artUrl
    ? `<img src="${esc(artUrl)}" alt="${title}">`
    : `<div class="card-detail-fallback">${title}</div>`;
  const legacyLifeLabel = `Life ${esc(player.life)}/${esc(lifeMax(player))}`;
  return `
    <div class="card-detail-modal player-detail-modal" data-close-detail>
      <article class="card-detail-panel player-detail-panel" role="dialog" aria-modal="true" aria-label="${title}">
        <button class="detail-close" data-close-detail>${esc(t("close"))}</button>
        <div class="card-detail-art player-detail-art">${art}</div>
        <div class="card-detail-copy">
          <div class="card-detail-title">${title}</div>
          <div class="card-detail-meta">
            <span>${esc(player.side || "")}</span>
            <span title="${legacyLifeLabel}">${esc(t("life"))} ${esc(player.life)}/${esc(lifeMax(player))}</span>
            <span>MR ${movementRightLabel(player)}</span>
            <span>${esc(t("trash"))} ${esc(player.trashCount || 0)}</span>
          </div>
          ${renderActiveEffects(player.activeEffects)}
        </div>
      </article>
    </div>
  `;
}

function renderTrashDetail() {
  if (!selectedTrashSide) return "";
  const player = findPlayerBySide(selectedTrashSide);
  if (!player) return "";
  const cards = [...(player.trash || [])].reverse();
  return `
    <div class="trash-detail-modal" data-trash-close>
      <article class="trash-detail-panel" role="dialog" aria-modal="true" aria-label="${esc(t("trash"))}">
        <div class="trash-detail-head">
          <div>
            <div class="payment-title">${esc(player.name)} ${esc(t("trash"))}</div>
            <div class="payment-note">${esc(t("cardsCount", { count: cards.length }))}, ${esc(t("newestFirst"))}</div>
          </div>
          <button data-trash-close>${esc(t("close"))}</button>
        </div>
        <div class="trash-detail-grid">
          ${cards.length ? cards.map((card) => renderCard(card, "trash-view-card")).join("") : `<div class="empty">${esc(t("empty"))}</div>`}
        </div>
      </article>
    </div>
  `;
}

function renderPublicRevealModal() {
  if (!activePublicReveal) return "";
  if (activePublicReveal.batch) {
    const reveal = activePublicReveal;
    const cards = (reveal.cards || []).filter(Boolean);
    if (!cards.length) return "";
    return `
      <div class="public-reveal-modal public-reveal-batch-modal" aria-live="polite">
        <article class="public-reveal-batch-card" role="status" aria-label="${esc(t("revealFromTopCards"))}">
          <div class="public-reveal-batch-head">
            <div class="prompt-title">${esc(t("revealFromTopCards"))}</div>
            <div class="card-detail-meta">
              <span>${esc(reveal.playerName || reveal.playerSide || "")}</span>
              <span>${esc(reveal.reason || "")}</span>
            </div>
          </div>
          <div class="public-reveal-batch-grid">
            ${cards.map((card) => {
              const title = esc(cardTitle(card));
              const artUrl = localizedCardAssetUrl(card);
              const stats = card.type && card.type !== "magic"
                ? `<span>${esc(card.bp ?? "-")}/${esc(card.dp ?? "-")}</span>`
                : "";
              const art = artUrl
                ? `<img src="${esc(artUrl)}" alt="${title}">`
                : `<div class="card-detail-fallback">${title}</div>`;
              return `
                <div class="public-reveal-batch-item">
                  <div class="public-reveal-batch-art">${art}</div>
                  <div class="public-reveal-batch-title">${title}</div>
                  <div class="card-detail-meta">${stats}</div>
                </div>
              `;
            }).join("")}
          </div>
        </article>
      </div>
    `;
  }
  if (!activePublicReveal.card) return "";
  const reveal = activePublicReveal;
  const card = reveal.card;
  const title = esc(cardTitle(card));
  const artUrl = localizedCardAssetUrl(card);
  const art = artUrl
    ? `<img src="${esc(artUrl)}" alt="${title}">`
    : `<div class="card-detail-fallback">${title}</div>`;
  const stats = card.type && card.type !== "magic"
    ? `<span>${esc(card.bp ?? "-")}/${esc(card.dp ?? "-")}</span>`
    : "";
  return `
    <div class="public-reveal-modal">
      <article class="public-reveal-card" role="dialog" aria-modal="true" aria-label="${title}">
        <div class="public-reveal-art">${art}</div>
        <div class="public-reveal-copy">
          <div class="prompt-title">${esc(t("publicReveal"))}</div>
          <div class="card-detail-title">${title}</div>
          <div class="card-detail-meta">
            <span>${esc(reveal.playerName || reveal.playerSide || "")}</span>
            <span>${esc(reveal.reason || "")}</span>
            <span>${esc(card.area || "")}</span>
            ${stats}
          </div>
          ${cardEffectText(card) ? `<div class="card-detail-effect">${multiline(cardEffectText(card))}</div>` : ""}
          <button class="primary" data-public-reveal-close>${esc(t("confirm"))}</button>
        </div>
      </article>
    </div>
  `;
}

function cardActionLabel(option, card) {
  if (option.kind === "play_to_base") {
    const replaced = option.replace_base_iid ? findCardByIid(option.replace_base_iid) : null;
    return replaced ? `${t("playToBase")} / ${t("replaceWith", { name: cardTitle(replaced) })}` : t("playToBase");
  }
  if (option.kind === "play_card") {
    return card.type === "magic" ? t("playMagic") : t("summon");
  }
  if (option.kind === "move_card") {
    const baseLabel = option.direction === "base_to_field" ? t("moveToField") : t("moveToBase");
    const replacedIid = option.direction === "base_to_field" ? option.replace_field_iid : option.replace_base_iid;
    const replaced = replacedIid ? findCardByIid(replacedIid) : null;
    return replaced ? `${baseLabel} / ${t("replaceWith", { name: cardTitle(replaced) })}` : baseLabel;
  }
  if (option.kind === "bless") return t("bless");
  if (option.kind === "attack") return t("attack");
  if (option.kind === "activate_flash_ability") return t("activateEffect");
  if (option.kind === "effect_target") return t("selectAsEffectTarget");
  if (option.kind === "minion") return t("selectAttackTarget");
  if (option.kind === "blocker") return t("block");
  return option.label || option.kind;
}

function renderCardDetailActions(card) {
  const actions = actionOptionsForCard(card);
  if (!actions.length) return "";
  const fieldReplacementActions = actions.filter(isFieldReplacementOption);
  const baseReplacementActions = actions.filter(isBaseReplacementOption);
  const directActions = actions.filter((option) =>
    !isFieldReplacementOption(option) && !isBaseReplacementOption(option) && option.kind !== "bless"
  );
  if (!fieldReplacementActions.length && !baseReplacementActions.length && !directActions.length) return "";
  const fieldReplacementLabel = fieldReplacementActions.some((option) => option.kind === "move_card")
    ? t("moveToField")
    : t("summon");
  const baseReplacementLabel = baseReplacementActions.some((option) => option.kind === "move_card")
    ? t("moveToBase")
    : t("playToBase");
  return `
    <div class="card-detail-actions">
      ${fieldReplacementActions.length ? `
        <button class="card-detail-action primary" data-field-replace-source="${esc(card.iid)}" title="${esc(fieldReplacementLabel)}">
          ${esc(fieldReplacementLabel)}
        </button>
      ` : ""}
      ${baseReplacementActions.length ? `
        <button class="card-detail-action primary" data-base-replace-source="${esc(card.iid)}" title="${esc(baseReplacementLabel)}">
          ${esc(baseReplacementLabel)}
        </button>
      ` : ""}
      ${directActions.map((option, index) => `
        <button class="card-detail-action ${index === 0 ? "primary" : ""}" data-option="${esc(option.id)}" title="${esc(cardActionLabel(option, card))}">
          ${esc(cardActionLabel(option, card))}
        </button>
      `).join("")}
    </div>
  `;
}

function renderCardHoverActions(card, actions) {
  if (!actions.length) return "";
  const fieldReplacementActions = actions.filter(isFieldReplacementOption);
  const baseReplacementActions = actions.filter(isBaseReplacementOption);
  const directActions = actions.filter((option) =>
    !isFieldReplacementOption(option) && !isBaseReplacementOption(option) && option.kind !== "bless"
  );
  if (!fieldReplacementActions.length && !baseReplacementActions.length && !directActions.length) return "";
  const fieldReplacementLabel = fieldReplacementActions.some((option) => option.kind === "move_card")
    ? t("moveToField")
    : t("summon");
  const baseReplacementLabel = baseReplacementActions.some((option) => option.kind === "move_card")
    ? t("moveToBase")
    : t("playToBase");
  return `
    <div class="card-hover-actions" aria-label="${esc(cardTitle(card))} actions">
      ${fieldReplacementActions.length ? `
        <button class="card-hover-action" data-field-replace-source="${esc(card.iid)}" title="${esc(fieldReplacementLabel)}">
          ${esc(fieldReplacementLabel)}
        </button>
      ` : ""}
      ${baseReplacementActions.length ? `
        <button class="card-hover-action" data-base-replace-source="${esc(card.iid)}" title="${esc(baseReplacementLabel)}">
          ${esc(baseReplacementLabel)}
        </button>
      ` : ""}
      ${directActions.map((option) => `
        <button class="card-hover-action" data-option="${esc(option.id)}" title="${esc(cardActionLabel(option, card))}">
          ${esc(cardActionLabel(option, card))}
        </button>
      `).join("")}
    </div>
  `;
}

function paymentCostText(option) {
  const entries = Object.entries(option.paymentCost || {});
  if (!entries.length) return "0";
  return entries.map(([color, amount]) => `${esc(color)} ${esc(amount)}`).join(" / ");
}

function renderPaymentEditor() {
  const option = optionById(pendingPaymentOptionId);
  if (!option) return "";
  const card = findCardByIid(option.iid);
  const valid = paymentSelectionIsValid(option);
  const selected = paymentSelectionValue(option) ?? 0;
  const required = paymentRequiredCount(option);
  const defaultIids = new Set(option.paymentDefaultIids || []);
  return `
    <div class="payment-modal">
      <section class="payment-panel" role="dialog" aria-modal="true" aria-label="${esc(t("manaPayment"))}">
        <div class="payment-head">
          <div>
            <div class="payment-title">${esc(card ? cardTitle(card) : promptOptionLabel(option))}</div>
            <div class="payment-note">${esc(t("paymentCost", { cost: paymentCostText(option), selected, required }))}</div>
          </div>
          <button data-payment-cancel>${esc(t("close"))}</button>
        </div>
        <div class="mana-choices">
          ${(option.paymentCandidates || []).map((candidate) => {
            const selected = paymentSelectionIids.has(candidate.iid);
            const isDefault = defaultIids.has(candidate.iid);
            const paymentCard = candidate.card || findCardByIid(candidate.iid);
            const paymentName = paymentCard
              ? cardTitle(paymentCard)
              : localizedName(candidate, candidate.nameJp || candidate.cardId || candidate.iid);
            const paymentArt = paymentCard ? cardImage(paymentCard) : "";
            const paymentValue = paymentCandidateValue(candidate);
            return `
              <button class="mana-choice ${selected ? "selected" : ""} ${isDefault ? "default" : ""}"
                      data-payment-iid="${esc(candidate.iid)}"
                      title="${esc(paymentName)}">
                <span class="mana-card-thumb">
                  ${paymentArt || `<span class="mana-card-thumb-fallback">${esc(paymentName).slice(0, 1)}</span>`}
                </span>
                <span class="mana-choice-copy">
                  <strong>${esc(paymentName)}</strong>
                  <span class="mana-choice-meta">
                    <span class="mana-color ${esc(candidate.color)}" aria-hidden="true">${esc(candidate.color.slice(0, 1))}</span>
                    <span class="mana-value" aria-label="${esc(`x${paymentValue}`)}">x${esc(paymentValue)}</span>
                  </span>
                </span>
              </button>
            `;
          }).join("")}
        </div>
        <div class="payment-actions">
          <button data-payment-reset>${esc(t("default"))}</button>
          <button class="primary" data-payment-confirm ${valid ? "" : "disabled"}>${esc(t("play"))}</button>
        </div>
      </section>
    </div>
  `;
}

function renderFieldReplaceEditor() {
  if (!pendingFieldReplaceSourceIid) return "";
  const source = findCardByIid(pendingFieldReplaceSourceIid);
  if (!source) return "";
  const options = fieldReplacementOptionsForCard(source);
  if (!options.length) return "";
  const isMove = options.some((option) => option.kind === "move_card");
  return `
    <div class="field-replace-modal">
      <section class="field-replace-panel" role="dialog" aria-modal="true" aria-label="${esc(t("chooseFieldReplacement"))}">
        <div class="field-replace-head">
          <div>
            <div class="payment-title">${esc(cardTitle(source))}</div>
            <div class="payment-note">${esc(t(isMove ? "fieldReplacementNoteMove" : "fieldReplacementNote"))}</div>
          </div>
          <button data-field-replace-cancel>${esc(t("close"))}</button>
        </div>
        <div class="field-replace-grid">
          ${options.map((option) => {
            const replaced = findCardByIid(option.replace_field_iid);
            if (!replaced) return "";
            const art = cardImage(replaced) || `<div class="card-detail-fallback">${esc(cardTitle(replaced))}</div>`;
            const bp = replaced.effectiveBp ?? replaced.bp ?? "-";
            const dp = replaced.effectiveDp ?? replaced.dp ?? "-";
            return `
              <button class="field-replace-card" data-field-replace-option="${esc(option.id)}">
                <span class="field-replace-art">${art}</span>
                <span class="field-replace-name">${esc(cardTitle(replaced))}</span>
                <span class="field-replace-stats">${esc(bp)}/${esc(dp)}</span>
              </button>
            `;
          }).join("")}
        </div>
      </section>
    </div>
  `;
}

function replacementRestState(card) {
  const rested = Boolean(card && card.rested);
  return `<span class="field-replace-status ${rested ? "rested" : "active"}">${rested ? esc(t("rested")) : esc(t("active"))}</span>`;
}

function renderBaseReplaceEditor() {
  const prompt = activePrompt();
  const isBlessingReturn = prompt && prompt.kind === "blessing_base_replacement";
  if (!pendingBaseReplaceSourceIid && !isBlessingReturn) return "";
  const source = isBlessingReturn ? prompt.card : findCardByIid(pendingBaseReplaceSourceIid);
  if (!source) return "";
  const options = baseReplacementOptionsForCard(source);
  if (!options.length) return "";
  const isMove = options.some((option) => option.kind === "move_card");
  const noteKey = isBlessingReturn
    ? "baseReplacementNoteBlessing"
    : (isMove ? "baseReplacementNoteMove" : "baseReplacementNotePlay");
  return `
    <div class="base-replace-modal">
      <section class="base-replace-panel" role="dialog" aria-modal="true" aria-label="${esc(t("chooseBaseReplacement"))}">
        <div class="field-replace-head">
          <div>
            <div class="payment-title">${esc(cardTitle(source))}</div>
            <div class="payment-note">${esc(t(noteKey))}</div>
          </div>
          <button data-base-replace-cancel>${esc(t("close"))}</button>
        </div>
        <div class="base-replace-grid">
          ${options.map((option) => {
            const replaced = findCardByIid(option.replace_base_iid);
            if (!replaced) return "";
            const art = cardImage(replaced) || `<div class="card-detail-fallback">${esc(cardTitle(replaced))}</div>`;
            const bp = replaced.effectiveBp ?? replaced.bp ?? "-";
            const dp = replaced.effectiveDp ?? replaced.dp ?? "-";
            return `
              <button class="base-replace-card" data-base-replace-option="${esc(option.id)}">
                <span class="field-replace-art">${art}</span>
                <span class="field-replace-name">${esc(cardTitle(replaced))}</span>
                <span class="field-replace-stats">${esc(bp)}/${esc(dp)}</span>
                ${replacementRestState(replaced)}
              </button>
            `;
          }).join("")}
        </div>
      </section>
    </div>
  `;
}

function renderColorlessBaseReplaceEditor() {
  if (!pendingColorlessBaseReplace) return "";
  const options = colorlessBaseReplacementOptions();
  if (!options.length) return "";
  return `
    <div class="colorless-base-replace-modal">
      <section class="colorless-base-replace-panel" role="dialog" aria-modal="true" aria-label="${esc(t("placeColorlessMana"))}">
        <div class="field-replace-head">
          <div>
            <div class="payment-title">${esc(t("placeColorlessMana"))}</div>
            <div class="payment-note">${esc(t("colorlessReplacementNote"))}</div>
          </div>
          <button data-colorless-base-replace-cancel>${esc(t("close"))}</button>
        </div>
        <div class="colorless-base-replace-grid">
          ${options.map((option) => {
            const replaced = findCardByIid(option.replace_base_iid);
            if (!replaced) return "";
            const art = cardImage(replaced) || `<div class="card-detail-fallback">${esc(cardTitle(replaced))}</div>`;
            const bp = replaced.effectiveBp ?? replaced.bp ?? "-";
            const dp = replaced.effectiveDp ?? replaced.dp ?? "-";
            return `
              <button class="colorless-base-replace-card" data-colorless-base-replace-option="${esc(option.id)}">
                <span class="field-replace-art">${art}</span>
                <span class="field-replace-name">${esc(cardTitle(replaced))}</span>
                <span class="field-replace-stats">${esc(bp)}/${esc(dp)}</span>
                ${replacementRestState(replaced)}
              </button>
            `;
          }).join("")}
        </div>
      </section>
    </div>
  `;
}

function renderShellHeader(title = "ZENONZARD") {
  const logo = uiAssetUrl("logo_zztitle");
  const navButton = (view, label) => `
    <button class="${appView === view ? "active" : ""}" data-view="${esc(view)}">${esc(label)}</button>
  `;
  return `
    <header class="topbar home-topbar">
      <div class="brand">
        ${logo
          ? `<img class="brand-logo" src="${esc(logo)}" alt="${esc(title)}">`
          : `<strong>${esc(title)}</strong>`}
        <div class="meta"></div>
      </div>
      <div></div>
      <div class="controls">
        ${renderLanguageSwitch()}
        ${navButton("home", t("home"))}
        ${navButton("lobby", t("gameLobby"))}
        ${navButton("settings", t("setting"))}
        ${state ? `<button data-view="duel">${esc(t("continueDuel"))}</button>` : ""}
        ${renderTopbarBgmControl()}
      </div>
    </header>
  `;
}

function renderApplicationUpdateNotice() {
  if (applicationUpdate.status !== "available") return "";
  return `
    <aside class="home-update-notice" role="status">
      <div>
        <strong>${esc(t("updateAvailable", { version: applicationUpdate.latestVersion }))}</strong>
        <span>${esc(t("updateCurrent", { version: applicationUpdate.currentVersion }))}</span>
      </div>
      <button type="button" data-open-release>${esc(t("viewRelease"))} ↗</button>
    </aside>
  `;
}

async function loadApplicationUpdate() {
  const result = await ZZApi.desktop.checkForUpdates();
  applicationUpdate = result && typeof result === "object" ? result : { status: "unavailable" };
  if (applicationUpdate.status === "error") {
    console.warn(`Application update check failed: ${applicationUpdate.error || "unknown error"}`);
  }
  if (appView === "home") render();
  return applicationUpdate;
}

async function openApplicationRelease() {
  const result = await ZZApi.desktop.openReleasePage();
  if (!result || result.ok !== true) console.warn("GitHub release page is unavailable outside the desktop client.");
}

function renderHome(error = null) {
  const homeLogo = uiAssetUrl("logo_zzicon");
  return `
    ${renderShellHeader()}
    <main class="home-menu-screen">
      ${error ? `<div class="error">${esc(error.message || error)}</div>` : ""}
      <section class="home-menu-hero" aria-label="ZENONZARD">
        <div class="home-menu-copy">
          ${homeLogo ? `<img class="home-menu-icon" src="${esc(homeLogo)}" alt="ZENONZARD">` : ""}
          <h1>ZENONZARD</h1>
        </div>
        <div class="home-menu-rail">
          ${renderApplicationUpdateNotice()}
          <div class="home-menu-actions">
          <button class="home-menu-button placeholder" disabled>
            <strong>${esc(t("storyMode"))}</strong>
            <span>${esc(t("comingSoon"))}</span>
          </button>
          <button class="home-menu-button primary" data-view="lobby">
            <strong>${esc(t("gameLobby"))}</strong>
            <span>${esc(t("battle"))}</span>
          </button>
          <button class="home-menu-button" data-view="deckbuilder">
            <strong>${esc(t("deckBuilder"))}</strong>
            <span>${esc(t("deckBuilderShort"))}</span>
          </button>
          <button class="home-menu-button" data-view="ai-training">
            <strong>${esc(t("replayTraining"))}</strong>
            <span>${esc(t("replayTrainingShort"))}</span>
          </button>
          <button class="home-menu-button" data-view="online">
            <strong>${esc(t("onlineGame"))}</strong>
            <span>${esc(multiplayerUi.status)}</span>
          </button>
          <button class="home-menu-button" data-view="settings">
            <strong>${esc(t("setting"))}</strong>
            <span>${esc(t("basicSettings"))}</span>
          </button>
          <button class="home-menu-button exit" data-exit-app>
            <strong>${esc(t("exit"))}</strong>
          </button>
            ${state ? `<button class="home-menu-button" data-view="duel"><strong>${esc(t("continueDuel"))}</strong></button>` : ""}
          </div>
        </div>
      </section>
    </main>
    ${renderHomeThemeOverlay()}
  `;
}

function renderHomeThemeOverlay() {
  if (!homeThemeActive) return "";
  return `
    <div class="home-theme-overlay" data-home-theme>
      <video data-home-theme-video src="/theme/op02.mp4" autoplay playsinline muted></video>
      <button class="home-theme-skip" data-home-theme-skip>Skip</button>
      ${homeThemeVideoError ? `<div class="home-theme-error">${esc(homeThemeVideoError)}</div>` : ""}
    </div>
  `;
}

function renderLaunchModePicker() {
  const selected = currentLaunchMode();
  return `
    <div class="launch-mode-picker">
      <span>${esc(t("launchMode"))}</span>
      <div class="launch-mode-options">
        ${launchModeOptions().map((mode) => `
          <button class="${mode.id === selected ? "active" : ""}" data-launch-mode="${esc(mode.id)}">
            ${esc(mode.label)}
          </button>
        `).join("")}
      </div>
    </div>
  `;
}

function renderSavedDeckManager() {
  return `
    <section class="home-panel saved-decks-panel">
        <div class="home-panel-head">
          <h2>${esc(t("savedDecks"))}</h2>
          <button data-new-deck>${esc(t("newDeck"))}</button>
        </div>
        <div class="deck-launch-grid deck-manager-grid">
          ${savedDecks.length ? savedDecks.map((deck) => `
            <article class="saved-deck-card">
              <div>
                <strong>${esc(deck.name)}</strong>
                <span>${esc(t("cardsCount", { count: deckTotal(deck.recipe) }))}</span>
              </div>
              <div class="saved-deck-forces">${deck.forces.map((id) => `<span>${esc(forceTitle(forceById(id) || { id }))}</span>`).join("")}</div>
              <div class="saved-deck-actions">
                <button data-edit-saved="${esc(deck.id)}">${esc(t("edit"))}</button>
                <button data-delete-deck="${esc(deck.id)}">${esc(t("delete"))}</button>
              </div>
            </article>
          `).join("") : `<div class="empty">${esc(t("empty"))}</div>`}
        </div>
      </section>
  `;
}

function renderGameLobby(error = null) {
  const hasDecks = Boolean(selectedPlayerDeckEntry() && selectedOpponentDeckEntry());
  return `
    ${renderShellHeader("ZENONZARD / LOBBY")}
    <main class="home-screen game-lobby-screen">
      ${error ? `<div class="error">${esc(error.message || error)}</div>` : ""}
      <section class="home-panel lobby-launch-panel">
        <div class="home-panel-head">
          <h1>${esc(t("gameLobby"))}</h1>
          <div class="home-panel-actions">
            <button data-view="home">${esc(t("back"))}</button>
          </div>
        </div>
        <div class="lobby-launch-strip">
          ${renderOpponentDeckPicker() || `<div class="empty">${esc(t("empty"))}</div>`}
          ${renderOpponentAiPicker()}
          ${renderLaunchModePicker()}
          <button class="primary lobby-start" data-start-selected ${hasDecks ? "" : "disabled"}>
            ${esc(t("startGame"))}
          </button>
        </div>
      </section>
      <section class="home-panel lobby-profile-panel">
        <div class="home-panel-head">
          <h2>${esc(t("operator"))}</h2>
        </div>
        ${renderProfileSetup()}
      </section>
      ${renderSavedDeckManager()}
    </main>
  `;
}

function renderOnlineDeckPicker() {
  const entries = launchDeckEntries();
  const selected = selectedPlayerDeckEntry();
  if (!entries.length) return `<div class="empty">${esc(t("empty"))}</div>`;
  return `
    <label class="online-field online-deck-field">
      <span>${esc(t("onlineSelectDeck"))}</span>
      <select data-player-deck>
        ${entries.map((entry) => `
          <option value="${esc(entry.key)}" ${selected && selected.key === entry.key ? "selected" : ""}>
            ${esc(entry.deck.name)} · ${esc(entry.source)}
          </option>
        `).join("")}
      </select>
    </label>
  `;
}

function isOnlineOpeningChoice() {
  return multiplayerUi.status === "MATCH_STARTING"
    || Boolean(multiplayerUi.room && multiplayerUi.room.status === "STARTING");
}

function renderOnlineOpeningDuelView(error = null) {
  const room = multiplayerUi.room || {};
  const player = currentOnlineRoomPlayer();
  const choiceSubmitted = Boolean(player && player.openingChoiceSubmitted);
  const tied = Boolean(room.lastOpeningResult && room.lastOpeningResult.result === "tie");
  const names = (room.players || []).map((item) => item.displayName || item.playerId).filter(Boolean);
  const logo = uiAssetUrl("logo_zztitle");
  return `
    <header class="topbar">
      <div class="brand duel-brand">
        ${logo
          ? `<img class="brand-logo duel-brand-logo" src="${esc(logo)}" alt="ZENONZARD">`
          : `<strong>ZENONZARD</strong>`}
        <div class="meta duel-status-meta">
          <span>${esc(t("onlineGame"))}</span>
          <span>${esc(t("onlineOpeningChoice"))}</span>
        </div>
      </div>
      <div class="controls">
        ${renderLanguageSwitch()}
        <button data-view="home">${esc(t("home"))}</button>
        <button class="danger" data-online-leave>${esc(t("onlineLeaveRoom"))}</button>
      </div>
    </header>
    ${error ? `<div class="online-reconnect-banner" role="alert">${esc(multiplayerErrorText(error))}</div>` : ""}
    <div class="duel-board online-opening-board">
      <div class="visual-overlay dice-roll-overlay opening-choice-overlay interactive" aria-live="polite">
        <div class="visual-overlay-card dice-roll-card opening-choice-card">
          <div class="dice-roll-value">${esc(tied ? t("onlineOpeningTie") : t("onlineOpeningChoice"))}</div>
          <div class="dice-roll-rule">${esc(names.join(" VS "))}</div>
          <div class="online-opening-choice-buttons">
            ${["rock", "paper", "scissors"].map((choice) => `
              <button data-online-opening-choice="${choice}" ${choiceSubmitted ? "disabled" : ""}>${esc(t(choice))}</button>
            `).join("")}
          </div>
          ${choiceSubmitted ? `<small>${esc(t("onlineOpeningWaiting"))}</small>` : ""}
        </div>
      </div>
    </div>
  `;
}

function renderOnlineRoom() {
  const room = multiplayerUi.room;
  if (!room) return "";
  const player = currentOnlineRoomPlayer();
  const canEditLoadout = ["WAITING_FOR_PLAYERS", "READY_CHECK"].includes(room.status);
  return `
    <section class="home-panel online-room-panel">
      <div class="home-panel-head">
        <div>
          <span>${esc(t("onlineRoomCode"))}</span>
          <h2>${esc(room.roomCode || "-")}</h2>
        </div>
        <strong class="online-status-value">${esc(room.status || multiplayerUi.status)}</strong>
      </div>
      <div class="online-player-list" aria-label="${esc(t("onlinePlayers"))}">
        ${(room.players || []).map((item) => `
          <div class="online-player-row ${item.playerId === multiplayerUi.playerId ? "self" : ""}">
            <strong>${esc(item.displayName || item.playerId)}</strong>
            <span>${item.isHost ? "HOST" : "GUEST"}${item.connected === false ? ` · ${esc(t("onlineDisconnected"))}` : ""}</span>
            <span>${item.deckSelected ? esc(t("onlineSelectDeck")) + " ✓" : "-"}</span>
            <span>${item.ready ? esc(t("onlineReady")) + " ✓" : esc(t("onlineWaitingOpponent"))}</span>
          </div>
        `).join("")}
      </div>
      ${canEditLoadout ? `
        <div class="online-room-actions">
          ${renderOnlineDeckPicker()}
          <button data-online-select-deck>${esc(t("onlineSelectDeck"))}</button>
          <button class="primary" data-online-ready ${player && player.deckSelected && room.status === "READY_CHECK" ? "" : "disabled"}>
            ${esc(player && player.ready ? t("onlineCancelReady") : t("onlineReady"))}
          </button>
          <button class="danger" data-online-leave>${esc(t("onlineLeaveRoom"))}</button>
        </div>
      ` : ""}
    </section>
  `;
}

function renderLanControls() {
  if (multiplayerUi.mode !== "lan") return "";
  const lan = multiplayerUi.lan || {};
  const hosting = lan.state === "RUNNING" || lan.state === "STARTING";
  const discovered = Array.isArray(lan.discovered) ? lan.discovered : [];
  return `
    <div class="lan-host-strip">
      <label class="online-field">
        <span>${esc(t("lanServerName"))}</span>
        <input data-lan-server-name value="ZZ LAN Room" maxlength="40" ${hosting ? "disabled" : ""}>
      </label>
      ${hosting
        ? `<button data-lan-stop ${multiplayerUi.room ? "disabled" : ""}>${esc(t("lanStopHost"))}</button>`
        : `<button class="primary" data-lan-host ${multiplayerUi.status === "OFFLINE" ? "" : "disabled"}>${esc(t("lanHost"))}</button>`}
      <button data-lan-discover ${lan.discovering ? "disabled" : ""}>${esc(t("lanDiscover"))}</button>
      <div class="online-status-line">
        <span>${esc(t("lanHosting"))}</span>
        <strong>${esc(lan.state || "STOPPED")}</strong>
      </div>
      ${hosting && (lan.addresses || []).length ? `\n        <div class="online-status-line">\n          <span>${esc(t("lanManualAddress"))}</span>\n          <strong>${esc((lan.addresses || []).join(" / "))}</strong>\n        </div>\n        <small>${esc(t("lanJoinHint"))}</small>\n      ` : ""}
    </div>
    <div class="lan-discovery-list">
      <span class="lan-discovery-title">${esc(t("lanDiscoveredRooms"))}</span>
      ${discovered.length ? discovered.map((room) => `
        <div class="lan-discovery-row">
          <strong>${esc(room.serverName || room.roomCode)}</strong>
          <span>${esc(room.host)}:${esc(room.port)} · ${esc(room.players)}/${esc(room.capacity)}</span>
          <button data-lan-join data-lan-address="${esc(room.host)}" data-lan-port="${esc(room.port)}" data-lan-room-code="${esc(room.roomCode)}" ${multiplayerUi.status === "OFFLINE" ? "" : "disabled"}>
            ${esc(t("onlineJoinRoom"))}
          </button>
        </div>
      `).join("") : `<div class="empty">${esc(t("lanNoRooms"))}</div>`}
    </div>
  `;
}

function renderOnlineGamePage(error = null) {
  const bridgeAvailable = Boolean(multiplayerBridge());
  const connected = !["OFFLINE", "ERROR"].includes(multiplayerUi.status);
  const modeLocked = connected || ["STARTING", "RUNNING"].includes(multiplayerUi.lan && multiplayerUi.lan.state);
  const visibleError = multiplayerErrorText(error || multiplayerUi.lastError);
  return `
    ${renderShellHeader("ZENONZARD / ONLINE")}
    <main class="home-screen online-game-screen">
      ${visibleError ? `<div class="error">${esc(visibleError)}</div>` : ""}
      <section class="home-panel online-connect-panel">
        <div class="home-panel-head">
          <h1>${esc(t("onlineGame"))}</h1>
          <button data-view="home">${esc(t("back"))}</button>
        </div>
        <div class="multiplayer-tabs" role="tablist">
          <button role="tab" class="${multiplayerUi.mode === "online" ? "active" : ""}" data-multiplayer-tab="online" ${modeLocked ? "disabled" : ""}>${esc(t("onlineGame"))}</button>
          <button role="tab" class="${multiplayerUi.mode === "lan" ? "active" : ""}" data-multiplayer-tab="lan" ${modeLocked ? "disabled" : ""}>${esc(t("lanGame"))}</button>
        </div>
        ${bridgeAvailable ? `
          ${renderLanControls()}
          <div class="online-connect-grid">
            <label class="online-field">
              <span>${esc(multiplayerUi.mode === "lan" ? t("lanManualAddress") : t("onlineServerUrl"))}</span>
              <input data-online-url value="${esc(multiplayerUi.url || (multiplayerUi.mode === "lan" ? LAN_SERVER_URL : ONLINE_SERVER_URL))}" ${connected ? "disabled" : ""}>
            </label>
            <label class="online-field">
              <span>${esc(t("onlinePlayerName"))}</span>
              <input data-online-name value="${esc(multiplayerUi.displayName || "Player")}" maxlength="40" ${multiplayerUi.room ? "disabled" : ""}>
            </label>
            <div class="online-status-line">
              <span>${esc(t("onlineConnectionStatus"))}</span>
              <strong>${esc(multiplayerUi.status)}</strong>
              <small class="online-route">${esc(t("onlineNetworkRoute"))}: ${esc(multiplayerUi.networkRoute || "UNSELECTED")}</small>
            </div>
            ${connected
              ? `<button data-online-disconnect>${esc(t("onlineDisconnect"))}</button>`
              : `<button class="primary" data-online-connect>${esc(t("onlineConnect"))}</button>`}
          </div>
          ${connected && !multiplayerUi.room ? `
            <div class="online-room-entry">
              <button class="primary" data-online-create>${esc(t("onlineCreateRoom"))}</button>
              <label class="online-field">
                <span>${esc(t("onlineRoomCode"))}</span>
                <input data-online-room-code maxlength="6" autocomplete="off">
              </label>
              <button data-online-join>${esc(t("onlineJoinRoom"))}</button>
            </div>
          ` : ""}
        ` : `<div class="empty">${esc(t("onlineUnavailable"))}</div>`}
      </section>
      <section class="home-panel online-profile-panel">
        <div class="home-panel-head">
          <h2>${esc(t("profilePlayer"))}</h2>
        </div>
        ${renderOnlinePlayerProfile()}
      </section>
      ${renderOnlineRoom()}
    </main>
  `;
}

function renderOnlinePlayerProfile() {
  const profile = normalizeProfile(settings.playerProfile);
  return `
    <div class="online-connect-grid">
      <label class="online-field">
        <span>${esc(t("playerCodeman"))}</span>
        <select data-profile-codeman="playerProfile">
          <option value="" ${profile.codemanId ? "" : "selected"}>${esc(t("originalAvatar"))}</option>
          ${characters().map((character) => `
            <option value="${esc(character.id)}" ${character.id === profile.codemanId ? "selected" : ""}>${esc(characterTitle(character))}</option>
          `).join("")}
        </select>
      </label>
      <label class="online-field">
        <span>${esc(t("playerPlaymat"))}</span>
        <select data-online-playmat>
          <option value="" ${profile.playmatId ? "" : "selected"}>${esc(t("defaultPlaymat"))}</option>
          ${playmats().map((playmat) => `
            <option value="${esc(playmat.id)}" ${playmat.id === profile.playmatId ? "selected" : ""}>${esc(playmat.file || playmat.id)}</option>
          `).join("")}
        </select>
      </label>
    </div>
  `;
}

function renderAiTrainingPage(error = null) {
  return `
    ${renderShellHeader("ZENONZARD / REPLAY & TRAINING")}
    <main class="home-screen ai-training-screen">
      ${error ? `<div class="error">${esc(error.message || error)}</div>` : ""}
      <section class="home-panel">
        <div class="home-panel-head">
          <h1>${esc(t("replayTraining"))}</h1>
          <button data-view="home">${esc(t("back"))}</button>
        </div>
        ${renderProfileSetup()}
      </section>
      ${renderReplayTrainingMemoryPanel()}
      ${renderAiTrainingPanel()}
    </main>
  `;
}

function renderReplayTrainingMemoryPanel() {
  const selected = selectedPlayerCodeman();
  if (!selected) return "";
  const codemanId = selected.id;
  return `
    <section class="home-panel replay-training-panel">
      <div class="home-panel-head">
        <div>
          <h2>${esc(t("battleReview"))}</h2>
          <span>${esc(characterTitle(selected))}</span>
        </div>
        <button data-codeman-memory="${esc(codemanId)}">${esc(t("codemanMemory"))}</button>
      </div>
    </section>
  `;
}

function renderSettingsPage(error = null) {
  const devEnabled = devModeEnabled();
  return `
    ${renderShellHeader("ZENONZARD / SETTING")}
    <main class="home-screen settings-screen">
      ${error ? `<div class="error">${esc(error.message || error)}</div>` : ""}
      ${settingsNotice ? `<div class="success">${esc(settingsNotice)}</div>` : ""}
      <section class="home-panel settings-panel">
        <div class="home-panel-head">
          <h1>${esc(t("setting"))}</h1>
          <button data-view="home">${esc(t("back"))}</button>
        </div>
        <div class="settings-grid">
          <article class="settings-block">
            <h2>${esc(t("basicSettings"))}</h2>
            ${renderLanguageSwitch()}
            ${renderBgmTrackPicker()}
            <div class="settings-row">
              <span>${esc(t("bgmSetting"))}</span>
              <button class="bgm-toggle ${bgmPlaying ? "active" : ""}" data-bgm-toggle>
                ${bgmPlaying ? "On" : "Off"}
              </button>
            </div>
            <label class="settings-toggle">
              <input type="checkbox" data-reduced-motion ${settings.reducedMotion ? "checked" : ""}>
              <span>${esc(t("reducedMotion"))}</span>
            </label>
          </article>
          <article class="settings-block developer-settings ${devEnabled ? "enabled" : ""}">
            <h2>${esc(t("developerMode"))}</h2>
            <div class="settings-row">
              <span>${esc(t("developerMode"))}</span>
              <strong>${devEnabled ? "ON" : "OFF"}</strong>
            </div>
            ${devEnabled
              ? `<button data-dev-mode-disable>${esc(t("disableDeveloperMode"))}</button>`
              : `
                <label class="settings-password">
                  <span>${esc(t("developerPassword"))}</span>
                  <input type="password" data-dev-mode-password autocomplete="off">
                </label>
                <button class="primary" data-dev-mode-enable>${esc(t("enableDeveloperMode"))}</button>
              `}
          </article>
        </div>
      </section>
    </main>
  `;
}

function renderHomeGuide() {
  const guide = homeGuide();
  if (!guide || !guide.assetUrl) return "";
  return `
    <aside class="home-guide">
      <img src="${esc(guide.assetUrl)}" alt="${esc(characterTitle(guide) || t("homeGuideName"))}">
      <div class="home-guide-copy">
        <span>${esc(t("operator"))}</span>
        <strong>${esc(characterTitle(guide) || t("homeGuideName"))}</strong>
        <p>${esc(t("homeGuideText"))}</p>
        <div class="home-guide-actions">
          <a class="rulebook-link" href="${esc(rulebookUrl())}" target="_blank" rel="noopener" data-open-rulebook>
            ${esc(t("openRulebook"))}
          </a>
        </div>
      </div>
    </aside>
  `;
}

function renderProfileSetup() {
  return `
    <div class="profile-setup">
      ${renderCodemanPicker("playerProfile", t("playerCodeman"))}
      ${renderCodemanPicker("opponentProfile", t("opponentCodeman"))}
    </div>
  `;
}

function renderCodemanPicker(profileKey, label) {
  const profile = normalizeProfile(settings[profileKey]);
  const selected = characterById(profile.codemanId);
  const art = selected && (selected.portraitUrl || selected.assetUrl || selected.thumbnailUrl);
  const fallback = profileKey === "playerProfile" ? "P" : "O";
  return `
    <article class="codeman-picker ${selected ? "selected" : "empty"}"
             style="--pilot-accent:${esc((selected && selected.color) || "#32d5c8")}">
      <div class="codeman-stage">
        ${art
          ? `<img class="codeman-halfbody-art" src="${esc(art)}" alt="${esc(characterTitle(selected))}">`
          : `<div class="codeman-original-avatar"><span>${esc(fallback)}</span></div>`}
      </div>
      <div class="codeman-config">
        <label>
          <span>${esc(label)}</span>
          <select data-profile-codeman="${esc(profileKey)}">
            <option value="" ${selected ? "" : "selected"}>${esc(t("originalAvatar"))}</option>
            ${characters().map((character) => `
              <option value="${esc(character.id)}" ${character.id === profile.codemanId ? "selected" : ""}>
                ${esc(characterTitle(character))}
              </option>
            `).join("")}
          </select>
        </label>
        <div class="codeman-copy">
          <strong>${esc(selected ? characterTitle(selected) : t("originalAvatar"))}</strong>
          <span>${esc(selected ? (characterCatchphrase(selected) || characterTitle(selected)) : (profileKey === "playerProfile" ? t("player") : t("opponent")))}</span>
        </div>
        ${renderPlaymatPicker(profileKey, profileKey === "playerProfile" ? t("playerPlaymat") : t("opponentPlaymat"))}
      </div>
    </article>
  `;
}

function renderAiTrainingPanel() {
  const selected = selectedPlayerCodeman();
  if (!selected) return "";
  const codemanId = selected.id;
  return `
    <section class="home-panel ai-training-panel">
      <div class="home-panel-head">
        <div>
          <h2>${esc(t("aiTraining"))}</h2>
          <span>${esc(characterTitle(selected))}</span>
        </div>
      </div>
      ${renderCodemanTrainingControl(codemanId)}
      <div class="training-env-hint">
        <span>${esc(t("trainingEnvironmentHint"))}</span>
      </div>
    </section>
  `;
}

function renderCodemanTrainingControl(codemanId) {
  const status = codemanTrainingStatus[codemanId];
  const method = normalizeCodemanTrainingMethod(codemanTrainingMethod);
  const progressPercent = codemanTrainingProgressPercent(status);
  return `
    <div class="codeman-training">
      <input class="codeman-training-preset" type="number" min="1" step="1"
             value="${esc(codemanTrainingCircles)}" data-codeman-training-circles
             aria-label="Codeman training circles">
      <select class="codeman-training-preset" data-codeman-training-method
              aria-label="Codeman training method">
        ${CODEMAN_TRAINING_METHODS.map((item) => `
          <option value="${esc(item.id)}" ${item.id === method ? "selected" : ""}>${esc(item.label)}</option>
        `).join("")}
      </select>
      <input class="codeman-training-preset" type="number" min="1" step="1"
             value="${esc(codemanTrainingCheckpointInterval)}" data-codeman-training-checkpoint-interval
             aria-label="Codeman checkpoint interval">
      <button class="codeman-train-button" data-codeman-train="${esc(codemanId)}"
              ${status && status.state === "running" ? "disabled" : ""}>${esc(t("train"))}</button>
      ${status ? `<span class="codeman-train-status ${esc(status.state)}">${esc(status.message)}</span>` : ""}
      ${status && status.state === "running" && progressPercent != null ? `
        <span class="codeman-training-progress" aria-label="Codeman training ${esc(progressPercent)}%">
          <i style="width:${esc(progressPercent)}%"></i>
          <b>${esc(progressPercent)}%</b>
        </span>
      ` : ""}
    </div>
  `;
}

function codemanReplayTitle() {
  const selected = characterById(codemanReplayState.codemanId);
  return selected ? characterTitle(selected) : (codemanReplayState.codemanId || "Codeman");
}

function renderCodemanReplayShell({ replayOnly = false } = {}) {
  return `
    <main class="codeman-replay-page">
      <header class="codeman-replay-head">
        <div>
          <span>${esc(t("codemanMemory"))}</span>
          <strong>${esc(codemanReplayTitle())}</strong>
        </div>
        <div class="codeman-replay-head-actions">
          ${codemanReplayState.matchId ? `<button data-codeman-replay-popout>${esc(t("codemanReplayOpenWindow"))}</button>` : ""}
          <button data-codeman-replay-close>${esc(t("close"))}</button>
        </div>
      </header>
      ${codemanReplayState.error ? `<div class="error">${esc(codemanReplayState.error)}</div>` : ""}
      ${codemanReplayState.loading ? `<div class="empty">${esc(t("loading"))}</div>` : ""}
      <div class="codeman-replay-layout ${replayOnly ? "replay-only" : ""}">
        ${renderCodemanMemoryList()}
        ${renderCodemanReplayPlayer()}
      </div>
    </main>
  `;
}

function renderCodemanMemoryPage() {
  return renderCodemanReplayShell({ replayOnly: false });
}

function renderCodemanReplayPage() {
  return renderCodemanReplayShell({ replayOnly: true });
}

function renderCodemanMemoryList() {
  const rows = codemanReplayState.memory || [];
  return `
    <section class="codeman-memory-list" aria-label="${esc(t("codemanMemory"))}">
      ${rows.length ? rows.map((row) => `
        <button class="codeman-memory-row ${row.matchId === codemanReplayState.matchId ? "selected" : ""}"
                data-codeman-replay-open="${esc(row.matchId)}">
          <span>
            <strong>${esc(row.matchId || "-")}</strong>
            <small>${esc(row.playerSide || "?")} vs ${esc(row.winnerSide || "?")} · ${esc(t("turn"))} ${esc(row.turns ?? "-")}</small>
          </span>
          ${row.aiComeback ? `<b>${esc(t("codemanAiComeback"))}</b>` : ""}
        </button>
      `).join("") : `<div class="empty">${esc(t("codemanNoMemory"))}</div>`}
    </section>
  `;
}

function renderCodemanReplayPlayer() {
  const replay = codemanReplayState.replay;
  if (!replay) return `<section class="codeman-replay-player"><div class="empty">${esc(t("codemanReplay"))}</div></section>`;
  const correctedAvailable = Boolean(replay.correctedReplay);
  const canCorrect = codemanReplayCanCorrect(replay);
  const events = codemanReplayEvents();
  const snapshots = codemanReplaySnapshots();
  const count = Math.max(events.length, snapshots.length);
  const frameMax = Math.max(0, count - 1);
  const index = Math.min(codemanReplayState.index, frameMax);
  const displayIndex = codemanReplayDisplaySnapshotIndex(index);
  const snapshot = codemanReplayCurrentSnapshot(displayIndex);
  return `
    <section class="codeman-replay-player">
      ${renderReplayDivergenceBanner(index)}
      <div class="codeman-replay-toolbar">
        <div class="codeman-replay-modes">
          <button class="${codemanReplayState.mode === "original" ? "active" : ""}"
                  data-codeman-replay-mode="original">${esc(t("codemanReplayOriginal"))}</button>
          <button class="${codemanReplayState.mode === "corrected" ? "active" : ""}"
                  data-codeman-replay-mode="corrected" ${correctedAvailable ? "" : "disabled"}>
            ${esc(t("codemanReplayCorrected"))}
          </button>
          ${canCorrect ? `
            <button data-codeman-replay-correct ${codemanReplayState.correcting ? "disabled" : ""}>
              ${esc(codemanReplayState.correcting ? t("codemanReplayCorrecting") : t("codemanReplayTryCorrection"))}
            </button>
          ` : ""}
        </div>
        <div class="codeman-replay-controls">
          <button data-codeman-replay-step="-1" ${index <= 0 ? "disabled" : ""}>${esc(t("back"))}</button>
          <button data-codeman-replay-play>${esc(codemanReplayState.playing ? t("codemanReplayPause") : t("codemanReplayPlay"))}</button>
          <button data-codeman-replay-step="1" ${index >= frameMax ? "disabled" : ""}>${esc(t("step"))}</button>
        </div>
      </div>
      ${snapshot ? renderCodemanReplaySnapshotView(snapshot, index, events) : renderCodemanReplayFallback(index, events)}
    </section>
  `;
}

function renderCodemanReplaySnapshotView(snapshot, index, events) {
  const snapshotState = snapshot && snapshot.state;
  if (!snapshotState || !snapshotState.players) return renderCodemanReplayFallback(index, events);
  const previousState = state;
  const previousReadonly = replayReadonlyMode;
  state = snapshotState;
  replayReadonlyMode = true;
  try {
    const human = state.players.human;
    const opponent = state.players.opponent;
    if (!human || !opponent) return renderCodemanReplayFallback(index, events);
    return renderDuelBoardShell(null, {
      readonly: true,
      replay: true,
      timelineHtml: renderCodemanReplayTimeline(index, events),
    });
  } catch (error) {
    return renderCodemanReplayFallback(index, events);
  } finally {
    replayReadonlyMode = previousReadonly;
    state = previousState;
  }
}

function renderCodemanReplayTimeline(index, events) {
  const count = Math.max(1, codemanReplayFrameCount());
  const max = Math.max(0, count - 1);
  const visibleEvents = replayVisibleEvents(index, events);
  const currentText = replayFrameText(index, events);
  return `
    <div class="codeman-replay-timeline">
      <div class="codeman-replay-now">
        <strong>${esc(index + 1)} / ${esc(count)}</strong>
        <span>${esc(currentText)}</span>
      </div>
      <input type="range" min="0" max="${esc(max)}" value="${esc(index)}"
             data-codeman-replay-scrub aria-label="${esc(t("codemanReplay"))}">
      <div class="codeman-replay-event-strip">
        ${visibleEvents.map((item) => `
          <button class="codeman-replay-event-chip ${item.frameIndex === index ? "active" : ""} ${hasReplayDivergence(item.index) ? "divergent" : ""}"
                  data-codeman-replay-jump="${esc(item.frameIndex)}">
            <b>${esc(item.index + 1)}</b>
            <span>${esc(replayEventText(item.event))}</span>
          </button>
        `).join("")}
      </div>
    </div>
  `;
}

function replayVisibleEvents(index, events) {
  if (!events.length) return [];
  const start = Math.max(0, Math.min(index - 2, events.length - 5));
  return events.slice(start, start + 5).map((event, offset) => {
    const eventIndex = start + offset;
    return {
      event,
      index: eventIndex,
      frameIndex: codemanReplayEventSnapshotIndex(event, eventIndex),
    };
  });
}

function replayEventForFrame(index, events = codemanReplayEvents()) {
  return events.find((event, eventIndex) => codemanReplayEventSnapshotIndex(event, eventIndex) === index) || null;
}

function replayEventIndexForFrame(index, events = codemanReplayEvents()) {
  const eventIndex = events.findIndex((event, fallbackIndex) => (
    codemanReplayEventSnapshotIndex(event, fallbackIndex) === index
  ));
  return eventIndex >= 0 ? eventIndex : index;
}

function replayFrameText(index, events = codemanReplayEvents()) {
  const event = replayEventForFrame(index, events);
  if (event) return replayEventText(event);
  const snapshot = codemanReplaySnapshotForIndex(index);
  if (snapshot && snapshot.label && snapshot.label !== "initial") return snapshot.label;
  if (index === 0) return t("codemanReplayStart");
  return `${t("codemanReplayFrame")} ${index + 1}`;
}

function renderCodemanReplayFallback(index, events) {
  return `
    <div class="codeman-replay-no-snapshots">
      <div class="empty">${esc(t("codemanReplayNoSnapshots"))}</div>
      <ol class="codeman-replay-events">
        ${events.length ? events.map((event, eventIndex) => `
          <li class="${eventIndex === index ? "active" : ""} ${hasReplayDivergence(eventIndex) ? "divergent" : ""}">
            <button class="codeman-replay-event-row" data-codeman-replay-jump="${esc(eventIndex)}">
              <span>${esc(eventIndex + 1)}</span>
              <span>${esc(replayEventText(event))}</span>
            </button>
          </li>
        `).join("") : `<li class="empty">${esc(t("noBattleLog"))}</li>`}
      </ol>
    </div>
  `;
}

function replayEventText(event) {
  if (!event || !Object.keys(event).length) return "";
  if (typeof battleLogEventText === "function") {
    const label = battleLogEventText(event);
    if (label && label !== "{}") return label;
  }
  return event.label || event.rawText || event.actionKind || event.type || "";
}

function replayDivergences() {
  const replay = codemanReplayState.replay;
  const corrected = replay && replay.correctedReplay;
  return corrected && Array.isArray(corrected.divergences) ? corrected.divergences : [];
}

function hasReplayDivergence(index) {
  return replayDivergences().some((item) => Number(item.eventIndex ?? item.index ?? -1) === index);
}

function replayDivergenceHint(divergence) {
  const playerAction = divergence.playerAction || divergence.playerLabel || divergence.originalActionKind || "-";
  const aiAction = divergence.aiAction || divergence.aiLabel || divergence.actionKind || "-";
  return t("codemanDivergenceHint", {
    player: logActionLabel(playerAction),
    ai: logActionLabel(aiAction),
  });
}

function renderReplayDivergenceBanner(index) {
  if (codemanReplayState.mode !== "corrected") return "";
  const eventIndex = replayEventIndexForFrame(index);
  const divergence = replayDivergences().find((item) => Number(item.eventIndex ?? item.index ?? -1) === eventIndex);
  if (!divergence) return "";
  const hint = replayDivergenceHint(divergence);
  return `
    <div class="codeman-divergence-banner" role="status">
      <strong>${esc(t("codemanDivergence"))}</strong>
      <span>${esc(hint)}</span>
    </div>
  `;
}

function renderPlaymatPicker(profileKey, label) {
  const profile = normalizeProfile(settings[profileKey]);
  const selected = playmatById(profile.playmatId);
  const previewStyle = selected && selected.assetUrl
    ? `style="background-image:url(${esc(cssUrl(selected.assetUrl))})"`
    : "";
  return `
    <div class="playmat-picker">
      <div class="playmat-picker-head">
        <span>${esc(label)}</span>
        <strong>${esc(selected ? (selected.file || selected.id) : t("defaultPlaymat"))}</strong>
      </div>
      <div class="playmat-preview ${selected ? "selected" : "empty"}" ${previewStyle}>
        ${selected ? "" : `<span>${esc(t("default"))}</span>`}
      </div>
      <div class="playmat-picker-actions">
        <button data-open-playmat-db="${esc(profileKey)}">${esc(t("playmats"))}</button>
        <button data-playmat-clear="${esc(profileKey)}" ${selected ? "" : "disabled"}>${esc(t("default"))}</button>
      </div>
    </div>
  `;
}

function renderOpponentAiPicker() {
  const selected = normalizeOpponentAiDifficulty(settings.opponentAiDifficulty);
  const options = [
    ["easy", "Easy"],
    ["normal", "Medium"],
    ["deep", "High"],
  ];
  return `
    <div class="opponent-ai-picker">
      <label>
        <span>${esc(t("opponentAi"))}</span>
        <select data-opponent-ai-difficulty>
          ${options.map(([id, label]) => `
            <option value="${esc(id)}" ${id === selected ? "selected" : ""}>${esc(label)}</option>
          `).join("")}
        </select>
      </label>
    </div>
  `;
}

function renderPlaymatDatabase(error = null) {
  const target = validProfileKey(selectedPlaymatProfileKey);
  const profile = normalizeProfile(settings[target]);
  const selected = playmatById(profile.playmatId);
  const tile = (playmat) => {
    const isSelected = selected && selected.id === playmat.id;
    const style = playmat.assetUrl ? `style="background-image:url(${esc(cssUrl(playmat.assetUrl))})"` : "";
    return `
      <button class="playmat-tile ${isSelected ? "selected" : ""}" data-playmat-select="${esc(playmat.id)}">
        <span class="playmat-tile-image" ${style}></span>
        <span class="playmat-tile-name">${esc(playmat.file || playmat.id)}</span>
      </button>
    `;
  };
  return `
    ${renderShellHeader("ZENONZARD / PLAYMAT")}
    <main class="home-screen playmat-database">
      ${error ? `<div class="error">${esc(error.message || error)}</div>` : ""}
      <section class="home-panel playmat-database-panel">
        <div class="home-panel-head">
          <h1>${esc(t("playmats"))}</h1>
          <button data-view="lobby">${esc(t("back"))}</button>
        </div>
        <div class="playmat-database-toolbar">
          <div class="playmat-target-tabs">
            <button class="${target === "playerProfile" ? "active" : ""}" data-playmat-target="playerProfile">${esc(t("profilePlayer"))}</button>
            <button class="${target === "opponentProfile" ? "active" : ""}" data-playmat-target="opponentProfile">${esc(t("profileOpponent"))}</button>
          </div>
          <button data-playmat-clear="${esc(target)}" ${selected ? "" : "disabled"}>${esc(t("defaultPlaymat"))}</button>
        </div>
        <div class="playmat-selected-line">
          <span>${esc(profileSideLabel(target))}</span>
          <strong>${esc(selected ? (selected.file || selected.id) : t("defaultPlaymat"))}</strong>
        </div>
        <div class="playmat-grid">
          ${playmats().length ? playmats().map(tile).join("") : `<div class="empty">${esc(t("empty"))}</div>`}
        </div>
      </section>
    </main>
  `;
}

function renderOpponentDeckPicker() {
  const entries = launchDeckEntries();
  if (!entries.length) return "";
  const selectedPlayer = selectedPlayerDeckEntry();
  const selectedOpponent = selectedOpponentDeckEntry();
  const playerDeck = selectedPlayer && selectedPlayer.deck;
  const opponentDeck = selectedOpponent && selectedOpponent.deck;
  const selectHtml = (side, selected, dataAttr) => `
    <label>
      <span>${esc(side)}</span>
      <select ${dataAttr}>
        ${entries.map((entry) => `
          <option value="${esc(entry.key)}" ${selected && selected.key === entry.key ? "selected" : ""}>
            ${esc(entry.deck.name)} · ${esc(entry.source)}
          </option>
        `).join("")}
      </select>
    </label>
  `;
  const previewLine = (label, deck) => deck ? `
    <span><b>${esc(label)}</b> ${esc(deck.name)} · ${esc(t("cardsCount", { count: deckTotal(deck.recipe) }))} · ${(deck.forces || []).map((id) => esc(forceTitle(forceById(id) || { id }))).join(" / ")}</span>
  ` : "";
  return `
    <div class="opponent-deck-picker">
      ${selectHtml(t("deckPlayer"), selectedPlayer, "data-player-deck")}
      ${selectHtml(t("deckOpponent"), selectedOpponent, "data-opponent-deck")}
      <div class="opponent-deck-preview">
        ${previewLine(t("profilePlayer"), playerDeck)}
        ${previewLine(t("profileOpponent"), opponentDeck)}
      </div>
    </div>
  `;
}

function renderOfficialFilterControls() {
  const groups = filterGroups();
  if (!groups.length) return "";
  const activeCount = activeOfficialFilters().length;
  return `
    <div class="deck-filter-grid">
      ${groups.map((group) => `
        <label class="deck-filter">
          <span>${esc(localizedCatalogLabel(group, group.id))}</span>
          <select data-deck-filter-group="${esc(group.id)}">
            <option value="">${esc(t("all"))}</option>
            ${(group.options || []).map((option) => `
              <option value="${esc(option.value)}" ${deckEditor.filters[group.id] === option.value ? "selected" : ""}>
                ${esc(localizedCatalogLabel(option))}
              </option>
            `).join("")}
          </select>
        </label>
      `).join("")}
      <button data-deck-filters-reset ${activeCount ? "" : "disabled"}>${esc(t("clearFilters"))}</button>
    </div>
  `;
}

function filteredDeckCatalogCards() {
  const search = deckEditor.search.trim().toLowerCase();
  return catalog.cards.filter((card) => {
    return cardMatchesOfficialFilters(card) && cardMatchesSearch(card, search);
  });
}

function refreshDeckSearchResults() {
  const list = app.querySelector(".card-catalog-list");
  if (!list) throw new Error("Deck search result list is missing.");
  list.innerHTML = filteredDeckCatalogCards().map((card) => renderCatalogCard(card)).join("");
}

function renderDeckBuilder(error = null) {
  const filteredCards = filteredDeckCatalogCards();
  const total = deckTotal();
  const deckReadyText = `${t("deck")} ${total} / 40`;
  const forceReady = deckEditor.selectedForceIds.length === 2;
  const valid = deckIsValid();
  const aiCompleteReady = deckCanAiComplete();
  const deckRows = Object.entries(deckEditor.recipe)
    .sort(([a], [b]) => {
      const ca = cardById(a);
      const cb = cardById(b);
      return `${ca ? ca.totalCost : 99}:${ca ? localizedName(ca, a) : a}`.localeCompare(`${cb ? cb.totalCost : 99}:${cb ? localizedName(cb, b) : b}`);
    });
  return `
    ${renderShellHeader("ZENONZARD / DECK")}
    <main class="deck-builder">
      ${error ? `<div class="error">${esc(error.message || error)}</div>` : ""}
      <section class="deck-editor-toolbar">
        <button data-view="lobby">${esc(t("back"))}</button>
        <input data-deck-name value="${esc(deckEditor.name)}" aria-label="deck name">
        <div class="deck-status ${valid ? "ready" : ""}">
          <span>${esc(deckReadyText)}</span>
          <span>${esc(t("force"))} ${esc(deckEditor.selectedForceIds.length)} / 2</span>
        </div>
        <button class="deck-ai-complete" data-ai-complete-deck ${aiCompleteReady && !deckCompletionLoading ? "" : "disabled"}>
          ${esc(deckCompletionLoading ? t("loading") : t("aiCompleteDeck"))}
        </button>
        <button class="deck-save primary" data-save-deck ${valid ? "" : "disabled"}>${esc(t("save"))}</button>
        <button data-play-editor-deck="god" ${valid ? "" : "disabled"}>${esc(t("playGod"))}</button>
        <button data-play-editor-deck="ai-vs-ai" ${valid ? "" : "disabled"}>${esc(t("aiTest"))}</button>
      </section>
      <section class="deck-builder-grid">
        <div class="card-catalog-panel">
          <div class="deck-panel-head">
            <h2>${esc(t("cards"))}</h2>
            <input data-deck-search value="${esc(deckEditor.search)}" aria-label="${esc(t("search"))}">
          </div>
          ${renderOfficialFilterControls()}
          <div class="card-catalog-list">
            ${filteredCards.map((card) => renderCatalogCard(card)).join("")}
          </div>
        </div>
        <div class="deck-list-panel">
          <div class="deck-panel-head">
            <h2>${esc(t("deck"))}</h2>
            <span>${esc(total)} / 40</span>
          </div>
          <div class="deck-list">
            ${deckRows.length ? deckRows.map(([cardId, count]) => {
              const card = cardById(cardId);
              return `
                <div class="deck-row">
                  <button class="deck-row-art" data-catalog-detail="${esc(cardId)}" aria-label="${esc(card ? localizedName(card, cardId) : cardId)}">
                    ${renderDeckRowArt(card, cardId)}
                  </button>
                  <span class="deck-row-name">${esc(card ? localizedName(card, cardId) : cardId)}</span>
                  <strong>${esc(count)}</strong>
                  <button data-deck-remove="${esc(cardId)}">-</button>
                  <button data-deck-add="${esc(cardId)}" ${canAddDeckCard(cardId) ? "" : "disabled"}>+</button>
                </div>
              `;
            }).join("") : `<div class="empty">${esc(t("empty"))}</div>`}
          </div>
          <div class="force-picker">
            <div class="deck-panel-head">
              <h2>${esc(t("forces"))}</h2>
              <span>${forceReady ? "2 / 2" : `${deckEditor.selectedForceIds.length} / 2`}</span>
            </div>
            <div class="force-picker-grid">
              ${catalog.forces.map((force) => {
                const selected = deckEditor.selectedForceIds.includes(force.id);
                return `
                  <button class="force-pick ${selected ? "selected" : ""}" data-force-toggle="${esc(force.id)}">
                    <span class="force-pick-art">${renderForcePickArt(force)}</span>
                    <span class="force-pick-name">${esc(forceTitle(force))}</span>
                    <b>${esc(force.initialLife)}</b>
                  </button>
                `;
              }).join("")}
            </div>
          </div>
        </div>
      </section>
    </main>
    ${renderCatalogCardDetail()}
  `;
}

function renderForcePickArt(force) {
  const forceAssetUrl = localizedForceAssetUrl(force);
  if (forceAssetUrl) {
    return `<img src="${esc(forceAssetUrl)}" alt="${esc(forceTitle(force))}">`;
  }
  return `<i>${esc((forceTitle(force) || "?").slice(0, 1))}</i>`;
}

function renderDeckRowArt(card, fallbackId = "") {
  const artUrl = localizedCardAssetUrl(card);
  if (artUrl) {
    return `<img src="${esc(artUrl)}" alt="${esc(localizedName(card, fallbackId))}">`;
  }
  const label = (card && localizedName(card, fallbackId)) || fallbackId || "?";
  return `<span>${esc(label.slice(0, 1))}</span>`;
}

function renderCatalogCard(card) {
  const count = deckEditor.recipe[card.id] || 0;
  const title = localizedName(card, card.id);
  const artUrl = localizedCardAssetUrl(card);
  const art = artUrl
    ? `<img src="${esc(artUrl)}" alt="${esc(title)}">`
    : `<span class="force-choice-fallback">${esc((title || card.id).slice(0, 1))}</span>`;
  return `
    <article class="catalog-card ${count ? "in-deck" : ""}">
      <button class="catalog-art" data-deck-add="${esc(card.id)}" ${canAddDeckCard(card.id) ? "" : "disabled"}>${art}</button>
      <div class="catalog-copy">
        <strong>${esc(title)}</strong>
        <span>${esc(localizedCardType(card))} / ${esc(card.officialCost || card.totalCost)}</span>
        <span>${esc(localizedCardAttribute(card))} ${esc(localizedCardSeries(card))}</span>
        <span>${esc(card.bp ?? "-")}/${esc(card.dp ?? "-")}</span>
      </div>
      <div class="catalog-count">
        <button data-catalog-detail="${esc(card.id)}">${esc(t("details"))}</button>
        <button data-deck-remove="${esc(card.id)}" ${count ? "" : "disabled"}>-</button>
        <span>${esc(count)}</span>
        <button data-deck-add="${esc(card.id)}" ${canAddDeckCard(card.id) ? "" : "disabled"}>+</button>
      </div>
    </article>
  `;
}

function renderCatalogCardDetail() {
  if (!selectedCatalogCardId) return "";
  const card = cardById(selectedCatalogCardId);
  if (!card) return "";
  const title = esc(localizedName(card, card.id));
  const artUrl = localizedCardAssetUrl(card);
  const art = artUrl
    ? `<img src="${esc(artUrl)}" alt="${title}">`
    : `<div class="card-detail-fallback">${title}</div>`;
  const races = (card.raceJp || []).map((race) => localizedCardRace(race)).filter(Boolean).join(" / ");
  const effect = localizedAbility(card);
  return `
    <div class="catalog-detail-modal" data-catalog-detail-close>
      <article class="catalog-detail-panel" role="dialog" aria-modal="true" aria-label="${title}">
        <button class="detail-close" data-catalog-detail-close>${esc(t("close"))}</button>
        <div class="card-detail-art">${art}</div>
        <div class="card-detail-copy">
          <div class="card-detail-title">${title}</div>
          <div class="catalog-detail-meta">
            <span>${esc(card.id)}</span>
            <span>${esc(localizedCardType(card))}</span>
            <span>${esc(localizedCardAttribute(card))}</span>
            <span>${esc(t("cost"))} ${esc(card.officialCost || card.totalCost)}</span>
            <span>BP ${esc(card.bp ?? "-")} / DP ${esc(card.dp ?? "-")}</span>
            ${localizedCardSeries(card) ? `<span>${esc(localizedCardSeries(card))}</span>` : ""}
            ${races ? `<span>${esc(races)}</span>` : ""}
            ${localizedCardRarity(card) ? `<span>${esc(localizedCardRarity(card))}</span>` : ""}
          </div>
          ${effect ? `<div class="card-detail-effect">${multiline(effect)}</div>` : ""}
        </div>
      </article>
    </div>
  `;
}

function render(error = null) {
  const appClass = appView === "duel" || appView === CODEMAN_REPLAY_VIEW ? "app duel-app" : "app shell-app";
  app.className = `${appClass}${settings.reducedMotion ? " reduce-motion" : ""}`;
  if (appView === "home") {
    setAppHtml(renderHome(error));
    return;
  }
  if (appView === "lobby") {
    setAppHtml(renderGameLobby(error));
    return;
  }
  if (appView === ONLINE_VIEW) {
    setAppHtml(renderOnlineGamePage(error));
    return;
  }
  if (appView === AI_TRAINING_VIEW) {
    setAppHtml(renderAiTrainingPage(error));
    return;
  }
  if (appView === "settings") {
    setAppHtml(renderSettingsPage(error));
    return;
  }
  if (appView === "playmats") {
    setAppHtml(renderPlaymatDatabase(error));
    return;
  }
  if (appView === "deckbuilder") {
    setAppHtml(renderDeckBuilder(error));
    return;
  }
  if (appView === CODEMAN_MEMORY_VIEW) {
    setAppHtml(renderCodemanMemoryPage(error));
    return;
  }
  if (appView === CODEMAN_REPLAY_VIEW) {
    setAppHtml(renderCodemanReplayPage(error));
    return;
  }
  if (isOnlineOpeningChoice()) {
    setAppHtml(renderOnlineOpeningDuelView(error));
    return;
  }
  if (!state) {
    setAppHtml(`<div class="empty">${esc(t("loading"))}</div>`);
    return;
  }
  if (isOnlineDuel()) {
    setAppHtml(renderDuelView(error));
    return;
  }
  if (!window.ZZDuelRuntime || typeof window.ZZDuelRuntime.render !== "function") {
    setAppHtml(`<div class="empty">${esc(t("openingDuel"))}</div>`);
    enterDuelPage();
    return;
  }
  setAppHtml(window.ZZDuelRuntime.render(error));
}

function ensureBgmAudio() {
  const track = selectedBgmTrack();
  if (bgmAudio && bgmTrackId === track.id) return bgmAudio;
  if (bgmAudio) bgmAudio.pause();
  bgmTrackId = track.id;
  bgmAudio = new Audio(`/audio/${encodeURIComponent(track.id)}`);
  bgmAudio.loop = true;
  bgmAudio.volume = 0.35;
  return bgmAudio;
}

function stopBgm() {
  if (bgmAudio) {
    bgmAudio.pause();
    bgmAudio.currentTime = 0;
  }
  bgmPlaying = false;
}

async function toggleBgm() {
  stopHomeThemeVideo(false);
  const audio = ensureBgmAudio();
  bgmError = null;
  if (bgmPlaying) {
    stopBgm();
    render();
    return;
  }
  try {
    await audio.play();
    bgmPlaying = true;
  } catch (error) {
    bgmPlaying = false;
    bgmError = error && error.message ? error.message : "BGM unavailable";
  }
  renderPreservingActiveViewScroll();
}

async function exitApp() {
  try {
    const result = await ZZApi.desktop.quit();
    if (result && result.ok) return;
  } catch (_) {
    // Browser fallback below.
  }
  window.close();
}

function selectedBattleSfxMap() {
  const selected = window.ZZ_BATTLE_SFX_MAP;
  return {
    ...BATTLE_SFX_MAP,
    ...(selected && typeof selected === "object" ? selected : {}),
  };
}

function zoneMoveCardType(event) {
  return String((event && event.card && event.card.type) || "");
}

function isBaseMinionPlacementEvent(event) {
  const cardType = zoneMoveCardType(event);
  return Boolean(
    event &&
    event.type === "zone_move" &&
    event.toArea === "base" &&
    (cardType === "b_minion" || cardType === "base_minion")
  );
}

function isFieldMinionSummonEvent(event) {
  const cardType = zoneMoveCardType(event);
  return Boolean(
    event &&
    event.type === "zone_move" &&
    event.toArea === "field" &&
    (cardType === "f_minion" || cardType === "field_minion")
  );
}

function battleSfxId(event) {
  if (!event) return null;
  const selected = selectedBattleSfxMap();
  if (event.type === "damage" && event.targetKind) {
    const damage = selected.damage;
    if (damage && typeof damage === "object") return damage[event.targetKind] || null;
    return typeof damage === "string" ? damage : null;
  }
  if (event.type === "zone_move") {
    if (isBaseMinionPlacementEvent(event)) return selected.baseMinionPlace || null;
    if (isFieldMinionSummonEvent(event)) return selected.minionSummon || null;
    return null;
  }
  return selected[event.type] || null;
}

function battleSfxVolume(event, id) {
  if (id && id === selectedBattleSfxMap().baseMinionPlace) return 0.68;
  if (event && event.type === "damage") return 0.58;
  if (event && event.type === "heal") return 0.52;
  if (event && event.type === "phase") return 0.3;
  return 0.46;
}

function battleSfxUrl(id) {
  return id ? `/audio/${encodeURIComponent(id)}` : null;
}

function playSampledBattleSfx(event) {
  const id = battleSfxId(event);
  const url = battleSfxUrl(id);
  if (!url || typeof Audio !== "function") return false;
  try {
    const audio = new Audio(url);
    audio.volume = battleSfxVolume(event, id);
    audio.play().catch(() => {});
    return true;
  } catch (_) {
    return false;
  }
}

function playBattleSfx(event) {
  if (!event) return;
  playSampledBattleSfx(event);
}

function clearDuelUiState() {
  appView = "duel";
  selectedCardIid = null;
  selectedForceKey = null;
  selectedTrashSide = null;
  battleDebugOpen = false;
  logModalOpen = false;
  battleDebugSearch = "";
  battleDebugFilters = {};
  battleDebugSide = "P1";
  battleDebugZone = "hand";
  battleDebugRested = false;
  publicRevealQueue = [];
  clearPublicRevealBatchTimer();
  activePublicReveal = null;
  animationEventQueue = [];
  activeAnimationEvent = null;
  pendingVisualState = null;
  visualStateStaged = false;
  hiddenZoneMoveSourceKeys.clear();
  lastAppliedMultiplayerViewKey = null;
  if (animationOverlayTimer) {
    clearTimeout(animationOverlayTimer);
    animationOverlayTimer = null;
  }
  effectTargetSelectionIds.clear();
  closePaymentEditor(false);
  closeFieldReplaceEditor(false);
  closeBaseReplaceEditor(false);
  closeColorlessBaseReplaceEditor(false);
}

async function leaveCurrentGame() {
  const onlineMatch = isOnlineDuel();
  stopAuto(false);
  if (onlineMatch) {
    try {
      await leaveOnlineRoom({ surrender: multiplayerUi.status === "IN_MATCH" });
    } catch (_) {
      // Renderer state still clears; the main-process connection remains observable.
    }
  }
  clearDuelUiState();
  stopBgm();
  stopHomeThemeVideo(false);
  state = null;
  activeMatchPayload = {};
  aiAdvice = null;
  aiAdviceLoading = false;
  aiAdviceError = null;
  pendingChoicePromptId = null;
  selectedPlayerSide = null;
  mulliganSelectedIids.clear();
  paymentSelectionIids.clear();
  if (window.location.pathname === "/duel" && window.location.protocol !== "file:") {
    window.history.replaceState(null, "", "/");
  }
  if (!onlineMatch) {
    try {
      await ZZApi.request("/api/leave-game", {});
    } catch (_) {
      // The local UI must still be cleared if the browser is closing or the server is gone.
    }
  }
}

async function returnToOnlineRoom() {
  const bridge = multiplayerBridge();
  clearDuelUiState();
  state = null;
  activeMatchPayload = {};
  pendingChoicePromptId = null;
  lastAppliedMultiplayerViewKey = null;
  appView = ONLINE_VIEW;
  if (bridge && typeof bridge.dismissMatchResult === "function") {
    const snapshot = await bridge.dismissMatchResult();
    applyMultiplayerSnapshot(snapshot);
    return;
  }
  render();
  await refreshMultiplayerSnapshot();
}

function enterDuelPage() {
  if (window.location.pathname !== "/duel" && window.location.protocol !== "file:") {
    window.location.assign("/duel");
  }
}

function shouldDeferDuelLaunch() {
  return window.location.protocol !== "file:"
    && window.location.pathname !== "/duel";
}

function deferDuelLaunch(mode, payload) {
  if (!shouldDeferDuelLaunch()) return false;
  try {
    sessionStorage.setItem(PENDING_DUEL_LAUNCH_KEY, JSON.stringify({ mode, payload }));
  } catch (_) {
    return false;
  }
  enterDuelPage();
  return true;
}

function consumePendingDuelLaunch() {
  if (window.location.protocol === "file:") return false;
  let raw = null;
  try {
    raw = sessionStorage.getItem(PENDING_DUEL_LAUNCH_KEY);
    if (!raw) return false;
    sessionStorage.removeItem(PENDING_DUEL_LAUNCH_KEY);
  } catch (_) {
    return false;
  }
  try {
    const launch = JSON.parse(raw);
    if (!launch || !launch.mode) return false;
    startNew(launch.mode, launch.payload || {});
    return true;
  } catch (_) {
    return false;
  }
}

function startNew(mode, launchPayload = null) {
  stopHomeThemeVideo(false);
  clearDuelUiState();
  const payload = cloneLaunchPayload({
    ...profilePayload(),
    ...selectedBattlePayload(),
    ...(launchPayload || {}),
  });
  activeMatchPayload = cloneLaunchPayload(payload);
  if (deferDuelLaunch(mode, payload)) return;
  if (mode !== "ai-vs-ai") stopAuto();
  api("/api/new-game", { mode, ...payload }).then(() => {
    if (mode === "ai-vs-ai") startAuto();
    enterDuelPage();
  });
}

function switchMode(mode) {
  if (!state) {
    startNew(mode);
    return;
  }
  if (mode !== "ai-vs-ai") stopAuto(false);
  effectTargetSelectionIds.clear();
  closePaymentEditor(false);
  closeFieldReplaceEditor(false);
  closeBaseReplaceEditor(false);
  closeColorlessBaseReplaceEditor(false);
  api("/api/mode", { mode }).then(() => {
    if (mode === "ai-vs-ai") startAuto();
    else render();
    enterDuelPage();
  });
}

function restartCurrentMatch() {
  startNew(state.mode, activeMatchPayload);
}

function isAutoRunning() {
  return autoEnabled || autoStepInFlight || Boolean(autoTimer);
}

function shouldShowDuelAutoControls() {
  return Boolean(state && state.mode === "ai-vs-ai");
}

function stateNeedsAiAutoStep() {
  if (!state || state.gameOver || state.prompt) return false;
  if (state.mode === "ai-vs-ai") return autoEnabled;
  if (state.mode === "human-vs-ai") {
    return Boolean(state.humanSide) && state.activeSide !== state.humanSide;
  }
  return false;
}

function hasBlockingAutoVisuals() {
  return Boolean(
    activeAnimationEvent ||
    animationEventQueue.length ||
    (activePublicReveal && !activePublicReveal.batch) ||
    publicRevealQueue.some((reveal) => !reveal.batch) ||
    pendingVisualState
  );
}

function autoModeActive() {
  return stateNeedsAiAutoStep();
}

function scheduleAutoStep(delay = AI_AUTO_STEP_DELAY_MS) {
  if (!autoModeActive() || autoTimer || autoStepInFlight) return;
  autoTimer = setTimeout(runAutoStep, delay);
}

async function runAutoStep() {
  autoTimer = null;
  if (!autoModeActive()) {
    render();
    return;
  }
  if (hasBlockingAutoVisuals()) {
    scheduleAutoStep(AI_AUTO_VISUAL_POLL_MS);
    return;
  }
  autoStepInFlight = true;
  renderPreservingActiveViewScroll();
  try {
    await api("/api/auto-step", { limit: 1 });
  } finally {
    autoStepInFlight = false;
    const blockedByVisuals = hasBlockingAutoVisuals();
    if (autoModeActive() && !blockedByVisuals) {
      scheduleAutoStep(AI_AUTO_STEP_DELAY_MS);
    }
    if (!blockedByVisuals) render();
  }
}

function startAuto() {
  stopAuto(false);
  autoEnabled = true;
  scheduleAutoStep(AI_AUTO_VISUAL_POLL_MS);
  renderPreservingActiveViewScroll();
}

function stopAuto(rerender = true) {
  autoEnabled = false;
  if (autoTimer) {
    clearTimeout(autoTimer);
    autoTimer = null;
  }
  if (rerender) render();
}

function cardFromPointerEvent(event) {
  if (
    event.target.closest("[data-close-detail]") ||
    event.target.closest("[data-payment-iid]") ||
    event.target.closest("[data-payment-confirm]") ||
    event.target.closest("[data-payment-cancel]") ||
    event.target.closest("[data-payment-reset]") ||
    event.target.closest("[data-field-replace-source]") ||
    event.target.closest("[data-field-replace-option]") ||
    event.target.closest("[data-field-replace-cancel]") ||
    event.target.closest("[data-base-replace-source]") ||
    event.target.closest("[data-base-replace-option]") ||
    event.target.closest("[data-base-replace-cancel]") ||
    event.target.closest("[data-colorless-base-replace]") ||
    event.target.closest("[data-colorless-base-replace-option]") ||
    event.target.closest("[data-colorless-base-replace-cancel]") ||
    event.target.closest("[data-trash-side]") ||
    event.target.closest("[data-trash-close]") ||
    event.target.closest("[data-mulligan-iid]") ||
    event.target.closest("[data-ai-advice]") ||
    event.target.closest("[data-log-toggle]") ||
    event.target.closest("[data-log-close]") ||
    event.target.closest("[data-effect-target-option]") ||
    event.target.closest("[data-effect-target-confirm]") ||
    event.target.closest("[data-option]") ||
    event.target.closest("[data-force-key]") ||
    event.target.closest("[data-battle-debug-toggle]") ||
    event.target.closest("[data-battle-debug-add]") ||
    event.target.closest("[data-battle-debug-move]") ||
    event.target.closest("[data-battle-debug-rested]") ||
    event.target.closest("[data-battle-debug-control-both]") ||
    event.target.closest("[data-battle-debug-filter]") ||
    event.target.closest("[data-battle-debug-filter-reset]") ||
    event.target.closest("[data-battle-debug-fixed-board]") ||
    event.target.closest("[data-battle-debug-search]") ||
    event.target.closest("[data-battle-debug-side]") ||
    event.target.closest("[data-battle-debug-zone]") ||
    event.target.closest("[data-battle-debug-add-rested]") ||
    event.target.closest("[data-battle-debug-force-select]") ||
    event.target.closest("[data-battle-debug-force-apply]")
  ) {
    return null;
  }
  return event.target.closest("[data-card-iid]");
}

function forceFromPointerEvent(event) {
  if (
    event.target.closest("[data-close-detail]") ||
    event.target.closest("[data-effect-target-option]") ||
    event.target.closest("[data-effect-target-confirm]") ||
    event.target.closest("[data-option]") ||
    event.target.closest("[data-field-replace-source]") ||
    event.target.closest("[data-field-replace-option]") ||
    event.target.closest("[data-field-replace-cancel]") ||
    event.target.closest("[data-base-replace-source]") ||
    event.target.closest("[data-base-replace-option]") ||
    event.target.closest("[data-base-replace-cancel]") ||
    event.target.closest("[data-colorless-base-replace]") ||
    event.target.closest("[data-colorless-base-replace-option]") ||
    event.target.closest("[data-colorless-base-replace-cancel]") ||
    event.target.closest("[data-trash-side]") ||
    event.target.closest("[data-trash-close]") ||
    event.target.closest("[data-ai-advice]") ||
    event.target.closest("[data-log-toggle]") ||
    event.target.closest("[data-log-close]") ||
    event.target.closest("[data-payment-confirm]") ||
    event.target.closest("[data-payment-cancel]") ||
    event.target.closest("[data-payment-reset]") ||
    event.target.closest("[data-battle-debug-toggle]") ||
    event.target.closest("[data-battle-debug-add]") ||
    event.target.closest("[data-battle-debug-move]") ||
    event.target.closest("[data-battle-debug-rested]") ||
    event.target.closest("[data-battle-debug-control-both]") ||
    event.target.closest("[data-battle-debug-filter]") ||
    event.target.closest("[data-battle-debug-filter-reset]") ||
    event.target.closest("[data-battle-debug-fixed-board]") ||
    event.target.closest("[data-battle-debug-search]") ||
    event.target.closest("[data-battle-debug-side]") ||
    event.target.closest("[data-battle-debug-zone]") ||
    event.target.closest("[data-battle-debug-add-rested]") ||
    event.target.closest("[data-battle-debug-force-select]") ||
    event.target.closest("[data-battle-debug-force-apply]")
  ) {
    return null;
  }
  return event.target.closest("[data-force-key]");
}

function handleOption(optionId) {
  const option = optionById(optionId);
  if (isPaymentConfigurable(option)) {
    openPaymentEditor(optionId);
    return;
  }
  choose(optionId);
}

function clearBlessDragState() {
  draggingBlessSourceIid = null;
  pendingBlessDrag = null;
  app.classList.remove("bless-dragging");
  app.querySelectorAll(".bless-drag-source, .bless-drop-hover").forEach((element) => {
    element.classList.remove("bless-drag-source", "bless-drop-hover");
  });
  blessDragArrow?.remove();
  blessDragArrow = null;
}

function updateBlessDragArrow(clientX, clientY) {
  const drag = pendingBlessDrag;
  if (!drag || !drag.active || !drag.source?.isConnected) return;
  if (!blessDragArrow) {
    blessDragArrow = document.createElement("div");
    blessDragArrow.className = "bless-drag-arrow";
    blessDragArrow.setAttribute("aria-hidden", "true");
    document.body.appendChild(blessDragArrow);
  }
  const rect = drag.source.getBoundingClientRect();
  const startX = rect.left + rect.width / 2;
  const startY = rect.top + rect.height / 2;
  const dx = clientX - startX;
  const dy = clientY - startY;
  const length = Math.max(1, Math.hypot(dx, dy));
  blessDragArrow.style.left = `${startX}px`;
  blessDragArrow.style.top = `${startY}px`;
  blessDragArrow.style.width = `${length}px`;
  blessDragArrow.style.transform = `rotate(${Math.atan2(dy, dx)}rad)`;
  const target = blessTargetElementAt(clientX, clientY);
  blessDragArrow.classList.toggle(
    "bless-drag-arrow-valid",
    Boolean(target && blessOptionForPair(drag.sourceIid, target.dataset.blessTargetIid)),
  );
}

function blessTargetElementAt(clientX, clientY) {
  const element = document.elementFromPoint(clientX, clientY);
  return element ? element.closest("[data-bless-target-iid]") : null;
}

function updateBlessDropHover(clientX, clientY) {
  app.querySelectorAll(".bless-drop-hover").forEach((element) => element.classList.remove("bless-drop-hover"));
  const target = blessTargetElementAt(clientX, clientY);
  if (
    target &&
    draggingBlessSourceIid !== null &&
    blessOptionForPair(draggingBlessSourceIid, target.dataset.blessTargetIid)
  ) {
    target.classList.add("bless-drop-hover");
  }
  updateBlessDragArrow(clientX, clientY);
}

app.addEventListener("pointerdown", (event) => {
  const source = event.target.closest("[data-bless-source-iid]");
  if (!source) return;
  if (event.pointerType === "mouse" && event.button !== 0) return;
  const sourceIid = source.dataset.blessSourceIid;
  if (!blessActionsForMana(findCardByIid(sourceIid)).length) {
    return;
  }
  pendingBlessDrag = {
    pointerId: event.pointerId,
    sourceIid,
    source,
    startX: event.clientX,
    startY: event.clientY,
    active: false,
  };
  source.setPointerCapture?.(event.pointerId);
});

app.addEventListener("pointermove", (event) => {
  const drag = pendingBlessDrag;
  if (!drag || drag.pointerId !== event.pointerId) return;
  if (!drag.active) {
    const distance = Math.hypot(event.clientX - drag.startX, event.clientY - drag.startY);
    if (distance < 8) return;
    drag.active = true;
    draggingBlessSourceIid = drag.sourceIid;
    suppressCardDetailUntil = Date.now() + 300;
    app.classList.add("bless-dragging");
    drag.source.classList.add("bless-drag-source");
    updateBlessDragArrow(event.clientX, event.clientY);
  }
  event.preventDefault();
  updateBlessDropHover(event.clientX, event.clientY);
});

function finishBlessPointerDrag(event) {
  const drag = pendingBlessDrag;
  if (!drag || drag.pointerId !== event.pointerId) return false;
  const wasActive = drag.active;
  const target = wasActive ? blessTargetElementAt(event.clientX, event.clientY) : null;
  const option = target ? blessOptionForPair(drag.sourceIid, target.dataset.blessTargetIid) : null;
  if (drag.source.hasPointerCapture?.(event.pointerId)) {
    drag.source.releasePointerCapture(event.pointerId);
  }
  clearBlessDragState();
  if (!wasActive) return false;
  event.preventDefault();
  suppressCardDetailUntil = Date.now() + 300;
  if (option) handleOption(option.id);
  return true;
}

app.addEventListener("pointercancel", (event) => {
  if (!pendingBlessDrag || pendingBlessDrag.pointerId !== event.pointerId) return;
  if (pendingBlessDrag.active) suppressCardDetailUntil = Date.now() + 300;
  clearBlessDragState();
});

app.addEventListener("pointerup", (event) => {
  if (finishBlessPointerDrag(event)) return;
  if (Date.now() < suppressCardDetailUntil) return;
  const card = cardFromPointerEvent(event);
  if (card) {
    openCardDetail(card.dataset.cardIid);
    return;
  }
  const force = forceFromPointerEvent(event);
  if (force) openForceDetail(force.dataset.forceKey);
});

app.addEventListener("dblclick", (event) => {
  if (event.target.closest("[data-home-theme]")) {
    event.preventDefault();
    stopHomeThemeVideo();
  }
});

app.addEventListener("click", async (event) => {
  if (Date.now() < suppressCardDetailUntil && event.target.closest("[data-card-iid]")) {
    event.preventDefault();
    return;
  }
  if (event.target.closest("[data-home-theme-skip]")) {
    event.preventDefault();
    stopHomeThemeVideo();
    return;
  }
  if (event.target.closest("[data-log-toggle]")) {
    event.preventDefault();
    logModalOpen = true;
    render();
    return;
  }
  const logCloseTarget = event.target.closest("[data-log-close]");
  const insideLogPanel = event.target.closest(".battle-log-panel");
  if (logCloseTarget && (!insideLogPanel || event.target.closest("button[data-log-close]"))) {
    event.preventDefault();
    logModalOpen = false;
    render();
    return;
  }
  if (event.target.closest("[data-public-reveal-close]")) {
    closePublicReveal();
    return;
  }
  if (event.target.closest("[data-ai-advice]")) {
    event.preventDefault();
    requestAiAdvice();
    return;
  }
  const codemanTrain = event.target.closest("[data-codeman-train]");
  if (codemanTrain) {
    event.preventDefault();
    requestCodemanTraining(codemanTrain.dataset.codemanTrain);
    return;
  }
  const codemanMemory = event.target.closest("[data-codeman-memory]");
  if (codemanMemory) {
    event.preventDefault();
    navigateCodemanMemory(codemanMemory.dataset.codemanMemory);
    return;
  }
  const replayOpen = event.target.closest("[data-codeman-replay-open]");
  if (replayOpen) {
    event.preventDefault();
    navigateCodemanReplay(codemanReplayState.codemanId, replayOpen.dataset.codemanReplayOpen);
    return;
  }
  if (event.target.closest("[data-codeman-replay-correct]")) {
    event.preventDefault();
    requestCodemanReplayCorrection(codemanReplayState.codemanId, codemanReplayState.matchId);
    return;
  }
  const replayMode = event.target.closest("[data-codeman-replay-mode]");
  if (replayMode) {
    event.preventDefault();
    setCodemanReplayMode(replayMode.dataset.codemanReplayMode);
    return;
  }
  if (event.target.closest("[data-codeman-replay-play]")) {
    event.preventDefault();
    if (codemanReplayState.playing) {
      stopCodemanReplayAutoplay();
      render();
    } else {
      startCodemanReplayAutoplay();
    }
    return;
  }
  const replayStep = event.target.closest("[data-codeman-replay-step]");
  if (replayStep) {
    event.preventDefault();
    stopCodemanReplayAutoplay();
    advanceCodemanReplay(Number(replayStep.dataset.codemanReplayStep || 1));
    return;
  }
  const replayJump = event.target.closest("[data-codeman-replay-jump]");
  if (replayJump) {
    event.preventDefault();
    setCodemanReplayIndex(Number(replayJump.dataset.codemanReplayJump || 0), { animate: false });
    return;
  }
  if (event.target.closest("[data-codeman-replay-popout]")) {
    event.preventDefault();
    openCodemanReplayWindow();
    return;
  }
  const replayClose = event.target.closest("[data-codeman-replay-close]");
  if (replayClose) {
    event.preventDefault();
    closeCodemanReplayView();
    return;
  }
  if (event.target.closest("[data-battle-debug-toggle]")) {
    battleDebugOpen = !battleDebugOpen;
    render();
    return;
  }
  if (event.target.closest("[data-battle-debug-filter-reset]")) {
    resetBattleDebugFilters();
    return;
  }
  if (event.target.closest("[data-battle-debug-fixed-board]")) {
    setupBattleDebugFixedBoard();
    return;
  }
  const battleDebugForceApply = event.target.closest("[data-battle-debug-force-apply]");
  if (battleDebugForceApply) {
    replaceBattleDebugForces(battleDebugForceApply.dataset.battleDebugForceApply);
    return;
  }
  const battleDebugAdd = event.target.closest("[data-battle-debug-add]");
  if (battleDebugAdd) {
    addBattleDebugCard(battleDebugAdd.dataset.battleDebugAdd);
    return;
  }
  const battleDebugMove = event.target.closest("[data-battle-debug-move]");
  if (battleDebugMove) {
    moveBattleDebugCard(battleDebugMove.dataset.battleDebugMove, battleDebugMove.dataset.zone);
    return;
  }
  const battleDebugRestedTarget = event.target.closest("[data-battle-debug-rested]");
  if (battleDebugRestedTarget) {
    setBattleDebugCardRested(
      battleDebugRestedTarget.dataset.battleDebugRested,
      battleDebugRestedTarget.dataset.rested === "true",
    );
    return;
  }
  const catalogCloseTarget = event.target.closest("[data-catalog-detail-close]");
  const insideCatalogDetail = event.target.closest(".catalog-detail-panel");
  if (catalogCloseTarget && (!insideCatalogDetail || event.target.closest("button[data-catalog-detail-close]"))) {
    closeCatalogCardDetail();
    return;
  }
  if (event.target.closest("[data-exit-app]")) {
    event.preventDefault();
    exitApp();
    return;
  }
  if (event.target.closest("[data-open-release]")) {
    event.preventDefault();
    openApplicationRelease();
    return;
  }
  if (event.target.closest("[data-online-connect]")) {
    event.preventDefault();
    connectOnlineServer();
    return;
  }
  const multiplayerTab = event.target.closest("[data-multiplayer-tab]");
  if (multiplayerTab) {
    event.preventDefault();
    switchMultiplayerMode(multiplayerTab.dataset.multiplayerTab);
    return;
  }
  if (event.target.closest("[data-lan-host]")) {
    event.preventDefault();
    startLanRoom();
    return;
  }
  if (event.target.closest("[data-lan-stop]")) {
    event.preventDefault();
    stopLanHost();
    return;
  }
  if (event.target.closest("[data-lan-discover]")) {
    event.preventDefault();
    discoverLanRooms();
    return;
  }
  const lanJoin = event.target.closest("[data-lan-join]");
  if (lanJoin) {
    event.preventDefault();
    joinDiscoveredLanRoom(lanJoin);
    return;
  }
  if (event.target.closest("[data-online-disconnect]")) {
    event.preventDefault();
    runMultiplayerCommand("disconnect");
    return;
  }
  if (event.target.closest("[data-online-create]")) {
    event.preventDefault();
    createOnlineRoom();
    return;
  }
  if (event.target.closest("[data-online-join]")) {
    event.preventDefault();
    joinOnlineRoom();
    return;
  }
  if (event.target.closest("[data-online-select-deck]")) {
    event.preventDefault();
    submitOnlineDeck();
    return;
  }
  if (event.target.closest("[data-online-ready]")) {
    event.preventDefault();
    toggleOnlineReady();
    return;
  }
  const openingChoice = event.target.closest("[data-online-opening-choice]");
  if (openingChoice) {
    event.preventDefault();
    submitOnlineOpeningChoice(openingChoice.dataset.onlineOpeningChoice);
    return;
  }
  if (event.target.closest("[data-online-leave]")) {
    event.preventDefault();
    leaveOnlineRoom();
    return;
  }
  if (event.target.closest("[data-online-return-room]")) {
    event.preventDefault();
    await returnToOnlineRoom();
    return;
  }
  const viewTarget = event.target.closest("[data-view]");
  if (viewTarget) {
    const view = viewTarget.dataset.view;
    if (appView === "duel" && view !== "duel") {
      await leaveCurrentGame();
    } else {
      stopHomeThemeVideo(false);
    }
    if (view === "home") showHome();
    else if (view === "lobby") showLobby();
    else if (view === ONLINE_VIEW) {
      appView = ONLINE_VIEW;
      render();
      refreshMultiplayerSnapshot();
    }
    else if (view === AI_TRAINING_VIEW) {
      appView = AI_TRAINING_VIEW;
      render();
    }
    else if (view === "settings") {
      appView = "settings";
      settingsNotice = null;
      render();
    }
    else if (view === "deckbuilder") startDeckBuilder();
    else if (view === "playmats") openPlaymatDatabase();
    else if (view === "duel" && state) {
      appView = "duel";
      render();
      enterDuelPage();
    }
    return;
  }
  const openPlaymatTarget = event.target.closest("[data-open-playmat-db]");
  if (openPlaymatTarget) {
    openPlaymatDatabase(openPlaymatTarget.dataset.openPlaymatDb);
    return;
  }
  const playmatTarget = event.target.closest("[data-playmat-target]");
  if (playmatTarget) {
    selectedPlaymatProfileKey = validProfileKey(playmatTarget.dataset.playmatTarget);
    render();
    return;
  }
  const playmatSelect = event.target.closest("[data-playmat-select]");
  if (playmatSelect) {
    updatePlaymatProfile(selectedPlaymatProfileKey, playmatSelect.dataset.playmatSelect);
    return;
  }
  const playmatClear = event.target.closest("[data-playmat-clear]");
  if (playmatClear) {
    updatePlaymatProfile(playmatClear.dataset.playmatClear || selectedPlaymatProfileKey, "");
    return;
  }
  if (event.target.closest("[data-new-deck]")) {
    newDeckInEditor();
    return;
  }
  if (event.target.closest("[data-deck-filters-reset]")) {
    resetDeckFilters();
    return;
  }
  const launchMode = event.target.closest("[data-launch-mode]");
  if (launchMode) {
    setLaunchMode(launchMode.dataset.launchMode);
    return;
  }
  if (event.target.closest("[data-start-selected]")) {
    startNew(currentLaunchMode());
    return;
  }
  if (event.target.closest("[data-dev-mode-enable]")) {
    setDeveloperMode(true);
    return;
  }
  if (event.target.closest("[data-dev-mode-disable]")) {
    setDeveloperMode(false);
    return;
  }
  const startDefault = event.target.closest("[data-start-default]");
  if (startDefault) {
    startNew(startDefault.dataset.startDefault);
    return;
  }
  const startTemplate = event.target.closest("[data-start-template]");
  if (startTemplate) {
    const deck = catalog.defaultDecks.find((item) => item.id === startTemplate.dataset.startTemplate);
    if (deck) startGameWithDeck("god", deck);
    return;
  }
  const startTemplateAi = event.target.closest("[data-start-template-ai]");
  if (startTemplateAi) {
    const deck = catalog.defaultDecks.find((item) => item.id === startTemplateAi.dataset.startTemplateAi);
    if (deck) startGameWithDeck("ai-vs-ai", deck);
    return;
  }
  const editTemplate = event.target.closest("[data-edit-template]");
  if (editTemplate) {
    const deck = catalog.defaultDecks.find((item) => item.id === editTemplate.dataset.editTemplate);
    if (deck) startDeckBuilder({ ...deck, id: null, name: `${deck.name} Copy` });
    return;
  }
  const startSaved = event.target.closest("[data-start-saved]");
  if (startSaved) {
    const deck = savedDecks.find((item) => item.id === startSaved.dataset.startSaved);
    if (deck) startGameWithDeck("god", deck);
    return;
  }
  const startSavedAi = event.target.closest("[data-start-saved-ai]");
  if (startSavedAi) {
    const deck = savedDecks.find((item) => item.id === startSavedAi.dataset.startSavedAi);
    if (deck) startGameWithDeck("ai-vs-ai", deck);
    return;
  }
  const editSaved = event.target.closest("[data-edit-saved]");
  if (editSaved) {
    const deck = savedDecks.find((item) => item.id === editSaved.dataset.editSaved);
    if (deck) startDeckBuilder(deck);
    return;
  }
  const deleteDeck = event.target.closest("[data-delete-deck]");
  if (deleteDeck) {
    deleteSavedDeck(deleteDeck.dataset.deleteDeck);
    return;
  }
  const addDeck = event.target.closest("[data-deck-add]");
  if (addDeck) {
    addDeckCard(addDeck.dataset.deckAdd);
    return;
  }
  const catalogDetail = event.target.closest("[data-catalog-detail]");
  if (catalogDetail) {
    openCatalogCardDetail(catalogDetail.dataset.catalogDetail);
    return;
  }
  const removeDeck = event.target.closest("[data-deck-remove]");
  if (removeDeck) {
    removeDeckCard(removeDeck.dataset.deckRemove);
    return;
  }
  const forceToggle = event.target.closest("[data-force-toggle]");
  if (forceToggle) {
    toggleDeckForce(forceToggle.dataset.forceToggle);
    return;
  }
  if (event.target.closest("[data-ai-complete-deck]")) {
    requestDeckAiCompletion();
    return;
  }
  if (event.target.closest("[data-save-deck]")) {
    saveCurrentDeck();
    return;
  }
  const playEditorDeck = event.target.closest("[data-play-editor-deck]");
  if (playEditorDeck) {
    startEditorDeck(playEditorDeck.dataset.playEditorDeck);
    return;
  }
  const trashCloseTarget = event.target.closest("[data-trash-close]");
  const insideTrashDetail = event.target.closest(".trash-detail-panel");
  if (trashCloseTarget && (!insideTrashDetail || event.target.closest("button[data-trash-close]"))) {
    closeTrashDetail();
    return;
  }
  const closeTarget = event.target.closest("[data-close-detail]");
  const insideDetail = event.target.closest(".card-detail-panel");
  if (closeTarget && (!insideDetail || event.target.closest(".detail-close"))) {
    closeCardDetail();
    return;
  }
  if (event.target.closest("[data-payment-cancel]")) {
    closePaymentEditor();
    return;
  }
  if (event.target.closest("[data-payment-reset]")) {
    resetPaymentSelection();
    return;
  }
  if (event.target.closest("[data-payment-confirm]")) {
    confirmPaymentSelection();
    return;
  }
  if (event.target.closest("[data-field-replace-cancel]")) {
    closeFieldReplaceEditor();
    return;
  }
  if (event.target.closest("[data-base-replace-cancel]")) {
    closeBaseReplaceEditor();
    return;
  }
  if (event.target.closest("[data-colorless-base-replace-cancel]")) {
    closeColorlessBaseReplaceEditor();
    return;
  }
  const fieldReplaceSource = event.target.closest("[data-field-replace-source]");
  if (fieldReplaceSource) {
    openFieldReplaceEditor(fieldReplaceSource.dataset.fieldReplaceSource);
    return;
  }
  const baseReplaceSource = event.target.closest("[data-base-replace-source]");
  if (baseReplaceSource) {
    openBaseReplaceEditor(baseReplaceSource.dataset.baseReplaceSource);
    return;
  }
  if (event.target.closest("[data-colorless-base-replace]")) {
    openColorlessBaseReplaceEditor();
    return;
  }
  const fieldReplaceOption = event.target.closest("[data-field-replace-option]");
  if (fieldReplaceOption) {
    handleOption(fieldReplaceOption.dataset.fieldReplaceOption);
    return;
  }
  const baseReplaceOption = event.target.closest("[data-base-replace-option]");
  if (baseReplaceOption) {
    handleOption(baseReplaceOption.dataset.baseReplaceOption);
    return;
  }
  const colorlessBaseReplaceOption = event.target.closest("[data-colorless-base-replace-option]");
  if (colorlessBaseReplaceOption) {
    handleOption(colorlessBaseReplaceOption.dataset.colorlessBaseReplaceOption);
    return;
  }
  const paymentMana = event.target.closest("[data-payment-iid]");
  if (paymentMana) {
    togglePaymentMana(paymentMana.dataset.paymentIid);
    return;
  }
  const mulliganToggle = event.target.closest("[data-mulligan-iid]");
  if (mulliganToggle) {
    toggleMulliganSelection(mulliganToggle.dataset.mulliganIid);
    return;
  }
  const trash = event.target.closest("[data-trash-side]");
  if (trash) {
    openTrashDetail(trash.dataset.trashSide);
    return;
  }
  const effectTargetOption = event.target.closest("[data-effect-target-option]");
  if (effectTargetOption) {
    toggleEffectTargetSelection(effectTargetOption.dataset.effectTargetOption);
    return;
  }
  if (event.target.closest("[data-effect-target-confirm]")) {
    confirmEffectTargetSelection();
    return;
  }
  const playerDetailTarget = event.target.closest("[data-player-detail]");
  if (playerDetailTarget) {
    const playerTargetOption = playerDetailTarget.closest("[data-option]");
    if (playerTargetOption) {
      handleOption(playerTargetOption.dataset.option);
      return;
    }
    openPlayerDetail(playerDetailTarget.dataset.playerDetail);
    return;
  }
  const option = event.target.closest("[data-option]");
  if (option) {
    handleOption(option.dataset.option);
    return;
  }
  const playerDetail = event.target.closest("[data-player-side]");
  if (playerDetail) {
    openPlayerDetail(playerDetail.dataset.playerSide);
    return;
  }
  const card = event.target.closest("[data-card-iid]");
  if (card) {
    openCardDetail(card.dataset.cardIid);
    return;
  }
  const force = event.target.closest("[data-force-key]");
  if (force) {
    openForceDetail(force.dataset.forceKey);
    return;
  }
  const step = event.target.closest("[data-step]");
  if (step) {
    if (!shouldShowDuelAutoControls()) return;
    if (autoStepInFlight || hasBlockingAutoVisuals()) {
      return;
    }
    autoStepInFlight = true;
    try {
      await api("/api/auto-step", { limit: Number(step.dataset.step || 1) });
    } finally {
      autoStepInFlight = false;
    }
    return;
  }
  const modeSwitch = event.target.closest("[data-mode]");
  if (modeSwitch) {
    switchMode(modeSwitch.dataset.mode);
    return;
  }
  const newGame = event.target.closest("[data-new]");
  if (newGame) {
    startNew(newGame.dataset.new, activeMatchPayload);
    return;
  }
  const concede = event.target.closest("[data-concede]");
  if (concede) {
    stopAuto(false);
    if (isOnlineDuel()) runMultiplayerCommand("surrender");
    else restartCurrentMatch();
    return;
  }
  const auto = event.target.closest("[data-auto]");
  if (auto) {
    if (!shouldShowDuelAutoControls()) return;
    if (isAutoRunning()) stopAuto();
    else startAuto();
    return;
  }
  const bgm = event.target.closest("[data-bgm-toggle]");
  if (bgm) {
    toggleBgm();
  }
});

app.addEventListener("input", (event) => {
  const onlineName = event.target.closest("[data-online-name]");
  if (onlineName) {
    persistOnlineDisplayName(onlineName.value);
    return;
  }
  const replayScrub = event.target.closest("[data-codeman-replay-scrub]");
  if (replayScrub) {
    setCodemanReplayIndex(Number(event.target.value || 0), { animate: false });
    return;
  }
  const battleDebugSearchInput = event.target.closest("[data-battle-debug-search]");
  if (battleDebugSearchInput) {
    battleDebugSearch = battleDebugSearchInput.value;
    refreshBattleDebugSearchResults();
    return;
  }
  const deckName = event.target.closest("[data-deck-name]");
  if (deckName) {
    updateDeckName(deckName.value);
    return;
  }
  const deckSearch = event.target.closest("[data-deck-search]");
  if (deckSearch) {
    deckEditor.search = deckSearch.value;
    refreshDeckSearchResults();
  }
});

app.addEventListener("change", (event) => {
  const uiLanguage = event.target.closest("[data-ui-language]");
  if (uiLanguage) {
    setUiLanguage(uiLanguage.value);
    return;
  }
  const bgmTrack = event.target.closest("[data-bgm-track]");
  if (bgmTrack) {
    updateBgmTrack(bgmTrack.value);
    return;
  }
  const battleDebugFilter = event.target.closest("[data-battle-debug-filter]");
  if (battleDebugFilter) {
    setBattleDebugFilter(battleDebugFilter.dataset.battleDebugFilter, battleDebugFilter.value);
    return;
  }
  const battleDebugSideInput = event.target.closest("[data-battle-debug-side]");
  if (battleDebugSideInput) {
    battleDebugSide = battleDebugSideInput.value || "P1";
    renderPreservingBattleDebugScroll();
    return;
  }
  const battleDebugZoneInput = event.target.closest("[data-battle-debug-zone]");
  if (battleDebugZoneInput) {
    battleDebugZone = battleDebugZoneInput.value || "hand";
    renderPreservingBattleDebugScroll();
    return;
  }
  const battleDebugRestedInput = event.target.closest("[data-battle-debug-add-rested]");
  if (battleDebugRestedInput) {
    battleDebugRested = Boolean(battleDebugRestedInput.checked);
    renderPreservingBattleDebugScroll();
    return;
  }
  const battleDebugControlBoth = event.target.closest("[data-battle-debug-control-both]");
  if (battleDebugControlBoth) {
    toggleBattleDebugControlBoth(battleDebugControlBoth.checked);
    return;
  }
  const profileCodeman = event.target.closest("[data-profile-codeman]");
  if (profileCodeman) {
    updateCodemanProfile(profileCodeman.dataset.profileCodeman, profileCodeman.value);
    return;
  }
  const profilePlaymat = event.target.closest("[data-profile-playmat]");
  if (profilePlaymat) {
    updatePlaymatProfile(profilePlaymat.dataset.profilePlaymat, profilePlaymat.value);
    return;
  }
  const onlinePlaymat = event.target.closest("[data-online-playmat]");
  if (onlinePlaymat) {
    updatePlaymatProfile("playerProfile", onlinePlaymat.value);
    return;
  }
  const opponentAiDifficulty = event.target.closest("[data-opponent-ai-difficulty]");
  if (opponentAiDifficulty) {
    updateOpponentAiDifficulty(opponentAiDifficulty.value);
    return;
  }
  const reducedMotion = event.target.closest("[data-reduced-motion]");
  if (reducedMotion) {
    updateReducedMotion(reducedMotion.checked);
    return;
  }
  const codemanCircles = event.target.closest("[data-codeman-training-circles]");
  if (codemanCircles) {
    codemanTrainingCircles = normalizePositiveInt(codemanCircles.value, 10);
    render();
    return;
  }
  const codemanMethod = event.target.closest("[data-codeman-training-method]");
  if (codemanMethod) {
    codemanTrainingMethod = normalizeCodemanTrainingMethod(codemanMethod.value);
    render();
    return;
  }
  const codemanCheckpointInterval = event.target.closest("[data-codeman-training-checkpoint-interval]");
  if (codemanCheckpointInterval) {
    codemanTrainingCheckpointInterval = normalizePositiveInt(codemanCheckpointInterval.value, 5);
    render();
    return;
  }
  const opponentDeck = event.target.closest("[data-opponent-deck]");
  if (opponentDeck) {
    setOpponentDeckKey(opponentDeck.value);
    return;
  }
  const playerDeck = event.target.closest("[data-player-deck]");
  if (playerDeck) {
    setPlayerDeckKey(playerDeck.value);
    return;
  }
  const deckFilter = event.target.closest("[data-deck-filter-group]");
  if (deckFilter) {
    setDeckFilter(deckFilter.dataset.deckFilterGroup, deckFilter.value);
  }
});

app.addEventListener("keydown", (event) => {
  if (
    (event.key === "Escape" || event.key === "Enter" || event.key === " ") &&
    activePublicReveal &&
    !activePublicReveal.batch
  ) {
    event.preventDefault();
    closePublicReveal();
    return;
  }
  if (event.key === "Escape" && selectedCatalogCardId) {
    event.preventDefault();
    closeCatalogCardDetail();
    return;
  }
  if (event.key === "Escape" && pendingPaymentOptionId) {
    event.preventDefault();
    closePaymentEditor();
    return;
  }
  if (event.key === "Escape" && pendingFieldReplaceSourceIid) {
    event.preventDefault();
    closeFieldReplaceEditor();
    return;
  }
  if (event.key === "Escape" && pendingBaseReplaceSourceIid) {
    event.preventDefault();
    closeBaseReplaceEditor();
    return;
  }
  if (event.key === "Escape" && pendingColorlessBaseReplace) {
    event.preventDefault();
    closeColorlessBaseReplaceEditor();
    return;
  }
  if (event.key === "Escape" && selectedTrashSide) {
    event.preventDefault();
    closeTrashDetail();
    return;
  }
  if (event.key === "Escape" && logModalOpen) {
    event.preventDefault();
    logModalOpen = false;
    render();
    return;
  }
  if (event.key === "Escape" && (appView === CODEMAN_MEMORY_VIEW || appView === CODEMAN_REPLAY_VIEW)) {
    event.preventDefault();
    closeCodemanReplayView();
    return;
  }
  if (event.key === "Escape" && battleDebugOpen) {
    event.preventDefault();
    battleDebugOpen = false;
    render();
    return;
  }
  if (event.key === "Escape" && ["playmats", "deckbuilder"].includes(appView)) {
    event.preventDefault();
    showLobby();
    return;
  }
  if (event.key === "Escape" && ["lobby", ONLINE_VIEW, "settings", AI_TRAINING_VIEW].includes(appView)) {
    event.preventDefault();
    showHome();
    return;
  }
  if (event.key === "Escape" && (selectedCardIid || selectedForceKey || selectedPlayerSide)) {
    event.preventDefault();
    closeCardDetail();
    return;
  }
  if (event.key !== "Enter" && event.key !== " ") return;
  const effectTargetOption = event.target.closest("[data-effect-target-option]");
  if (effectTargetOption) {
    event.preventDefault();
    toggleEffectTargetSelection(effectTargetOption.dataset.effectTargetOption);
    return;
  }
  if (event.target.closest("[data-effect-target-confirm]")) {
    event.preventDefault();
    confirmEffectTargetSelection();
    return;
  }
  const mulliganToggle = event.target.closest("[data-mulligan-iid]");
  if (mulliganToggle) {
    event.preventDefault();
    toggleMulliganSelection(mulliganToggle.dataset.mulliganIid);
    return;
  }
  const trash = event.target.closest("[data-trash-side]");
  if (trash) {
    event.preventDefault();
    openTrashDetail(trash.dataset.trashSide);
    return;
  }
  const playerDetailTarget = event.target.closest("[data-player-detail]");
  if (playerDetailTarget) {
    event.preventDefault();
    const playerTargetOption = playerDetailTarget.closest("[data-option]");
    if (playerTargetOption) {
      handleOption(playerTargetOption.dataset.option);
      return;
    }
    openPlayerDetail(playerDetailTarget.dataset.playerDetail);
    return;
  }
  const option = event.target.closest("[data-option]");
  if (option) {
    event.preventDefault();
    handleOption(option.dataset.option);
    return;
  }
  const playerDetail = event.target.closest("[data-player-side]");
  if (playerDetail) {
    event.preventDefault();
    openPlayerDetail(playerDetail.dataset.playerSide);
    return;
  }
  const fieldReplaceSource = event.target.closest("[data-field-replace-source]");
  if (fieldReplaceSource) {
    event.preventDefault();
    openFieldReplaceEditor(fieldReplaceSource.dataset.fieldReplaceSource);
    return;
  }
  const baseReplaceSource = event.target.closest("[data-base-replace-source]");
  if (baseReplaceSource) {
    event.preventDefault();
    openBaseReplaceEditor(baseReplaceSource.dataset.baseReplaceSource);
    return;
  }
  if (event.target.closest("[data-colorless-base-replace]")) {
    event.preventDefault();
    openColorlessBaseReplaceEditor();
    return;
  }
  const fieldReplaceOption = event.target.closest("[data-field-replace-option]");
  if (fieldReplaceOption) {
    event.preventDefault();
    handleOption(fieldReplaceOption.dataset.fieldReplaceOption);
    return;
  }
  const baseReplaceOption = event.target.closest("[data-base-replace-option]");
  if (baseReplaceOption) {
    event.preventDefault();
    handleOption(baseReplaceOption.dataset.baseReplaceOption);
    return;
  }
  const colorlessBaseReplaceOption = event.target.closest("[data-colorless-base-replace-option]");
  if (colorlessBaseReplaceOption) {
    event.preventDefault();
    handleOption(colorlessBaseReplaceOption.dataset.colorlessBaseReplaceOption);
    return;
  }
  const card = event.target.closest("[data-card-iid]");
  if (card) {
    event.preventDefault();
    openCardDetail(card.dataset.cardIid);
    return;
  }
  const force = event.target.closest("[data-force-key]");
  if (force) {
    event.preventDefault();
    openForceDetail(force.dataset.forceKey);
  }
});

["pointermove", "keydown", "wheel", "touchstart"].forEach((eventName) => {
  window.addEventListener(eventName, recordHomeActivity, { passive: true });
});

window.addEventListener("pagehide", () => {
  if (isOnlineDuel()) return;
  if (appView !== "duel" || !state || !navigator.sendBeacon) return;
  navigator.sendBeacon("/api/leave-game", new Blob(["{}"], { type: "application/json" }));
});

function bootApp(initialView = "home") {
  multiplayerUi.displayName = rememberedOnlineDisplayName();
  appView = initialView;
  if (!handleCodemanReplayRoute()) render();
  return Promise.all([
    loadSavedDecks(),
    loadSettings(),
    loadCatalog(),
    initMultiplayerBridge(),
    loadApplicationUpdate(),
  ]).then((result) => {
    if (!parseCodemanReplayHash()) render();
    return result;
  });
}

function loadState() {
  return api("/api/state").then((payload) => {
    if (state && state.mode === "ai-vs-ai" && !state.gameOver) startAuto();
    return payload;
  });
}

window.ZZApp = {
  bootApp,
  consumePendingDuelLaunch,
  loadState,
  renderDuelView,
  renderDuelBoardShell,
};

if (!window.ZZ_DEFER_BOOT) {
  bootApp("home");
}

window.addEventListener("hashchange", handleCodemanReplayRoute);
