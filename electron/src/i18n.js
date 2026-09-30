export const LANGUAGES = [
  { value: 'zh-CN', label: '简体中文' },
  { value: 'en', label: 'English' },
]

const strings = {
  'zh-CN': {
    chat: '对话', mods: 'Mod 管理', snapshots: '快照', settings: '设置', pshare: 'P Share', reviewer: '审核台',
    connected: '已连接', starting: '正在启动…', disconnected: '连接中断', refresh: '刷新界面',
    startingApp: 'ModAgent 正在启动', startingDetail: '正在连接本地服务并读取游戏数据…',
    language: '显示语言', languageHelp: '界面与 AI 回复会使用此语言；Mod 原名、路径和链接会保留原文。',
    setupTitle: 'ModAgent 首次配置',
    setupIntro: '只需要配置一个大模型 API。DeepSeek 是默认推荐；Nexus 和 Tavily 均可跳过并稍后补充，已填写的 Key 会保存在本机 Windows 加密存储中。',
    provider: '大模型服务商', optional: '可选', getKey: '获取 Key', next: '下一步', model: '模型', customModel: '自定义模型名', endpoint: '接口地址', previous: '上一步', saveAndEnter: '保存并进入', saving: '保存中…',
    setupDetail: '完成后 ModAgent 会自动扫描 Steam 游戏。进入主界面后选择游戏，即可开始聊天、搜索和安装 Mod。',
    llmExplanation: 'LLM 用于中文对话、推荐和安装计划；Nexus 用于读取和下载 Nexus Mods；Tavily 用于增强跨网站搜索。当前支持 OpenAI-compatible 接口，原生 Claude/Gemini 等专用协议会放到后续版本。',
    settingsTitle: '设置', apiKeys: 'API 密钥', llmSettings: 'LLM 设置', languageSaved: '语言已保存；新的对话和 AI 输出将使用所选语言。',
    searchMods: '搜索 Mod 名称…', all: '全部', updates: '可更新', disabled: '已禁用', reconcile: '对账',
    checkUpdates: '检查更新', align: '对齐', enrichSummary: 'AI 补全简介', generatingSummary: '生成简介中',
    downloadNewMod: '下载新 Mod', refreshMods: '刷新', dropFolder: '投放文件夹', modFolder: 'Mod 文件夹', toolsFolder: '工具目录',
    selectAll: '全选', clearSelection: '取消全选', snapshotHistory: '快照历史', actualStorage: '实际占用约',
    createSnapshot: '创建快照', reconcileSnapshots: '对账', newChat: '新对话',
    messagePlaceholder: '输入消息 · Enter 发送 · Shift+Enter 换行', send: '发送', stop: '停止',
  },
  en: {
    chat: 'Chat', mods: 'Mod Manager', snapshots: 'Snapshots', settings: 'Settings', pshare: 'P Share', reviewer: 'Review Console',
    connected: 'Connected', starting: 'Starting…', disconnected: 'Disconnected', refresh: 'Refresh UI',
    startingApp: 'Starting ModAgent', startingDetail: 'Connecting to the local service and reading game data…',
    language: 'Display language', languageHelp: 'The UI and AI replies use this language. Mod names, paths and links stay unchanged.',
    setupTitle: 'Set up ModAgent',
    setupIntro: 'Only one LLM API is required. DeepSeek is the default recommendation; Nexus and Tavily can be added later. Entered keys are stored in Windows secure storage on this device.',
    provider: 'LLM provider', optional: 'Optional', getKey: 'Get key', next: 'Next', model: 'Model', customModel: 'Custom model name', endpoint: 'Endpoint', previous: 'Back', saveAndEnter: 'Save and enter', saving: 'Saving…',
    setupDetail: 'After setup, ModAgent scans installed Steam games. Choose a game on the main screen to chat, search and install Mods.',
    llmExplanation: 'The LLM powers chat, recommendations and install plans. Nexus reads and downloads Nexus Mods; Tavily improves cross-site search. OpenAI-compatible endpoints are supported now; native Claude/Gemini protocols are planned for a later release.',
    settingsTitle: 'Settings', apiKeys: 'API keys', llmSettings: 'LLM settings', languageSaved: 'Language saved. New chats and AI responses will use the selected language.',
    searchMods: 'Search mods…', all: 'All', updates: 'Updates', disabled: 'Disabled', reconcile: 'Reconcile',
    checkUpdates: 'Check updates', align: 'Align', enrichSummary: 'AI summaries', generatingSummary: 'Generating summaries',
    downloadNewMod: 'Download mod', refreshMods: 'Refresh', dropFolder: 'Drop folder', modFolder: 'Mod folder', toolsFolder: 'Tools folder',
    selectAll: 'Select all', clearSelection: 'Clear selection', snapshotHistory: 'Snapshot history', actualStorage: 'Actual storage',
    createSnapshot: 'Create snapshot', reconcileSnapshots: 'Reconcile', newChat: 'New chat',
    messagePlaceholder: 'Type a message · Enter to send · Shift+Enter for a new line', send: 'Send', stop: 'Stop',
  },
}

export function tr(language, key) {
  return (strings[language] || strings['zh-CN'])[key] || strings['zh-CN'][key] || key
}
