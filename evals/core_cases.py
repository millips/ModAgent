from __future__ import annotations

from dataclasses import dataclass

from modagent.orchestration.models import AgentMode


@dataclass(frozen=True)
class GoldenCase:
    case_id: str
    category: str
    user_input: str
    expected_intent: AgentMode
    selection_action: str = ""
    has_selection: bool = False
    regenerate: bool = False
    must_not_use: tuple[str, ...] = ()
    mutation_allowed: bool = False
    severity: str = "P1"


_MUTATIONS = (
    "mod_download", "batch_download", "download_from_url", "mod_install",
    "mod_install_batch", "mod_install_custom", "mod_uninstall", "mod_update",
    "mod_disable", "snapshot_restore", "snapshot_delete", "workshop_install",
)
_SEARCH = (
    "mod_recommend", "nexus_search", "workshop_search", "thunderstore_search",
    "github_search", "gamebanana_search",
)


def _make(
    prefix: str,
    category: str,
    intent: AgentMode,
    messages: list[str],
    **kwargs,
) -> list[GoldenCase]:
    return [
        GoldenCase(
            case_id=f"{prefix}-{index:03d}", category=category,
            user_input=message, expected_intent=intent, **kwargs,
        )
        for index, message in enumerate(messages, 1)
    ]


CORE_CASES: list[GoldenCase] = []

# 12: ordinary explanation and clarification
CORE_CASES += _make("chat", "chat_explain", AgentMode.CHAT_EXPLAIN, [
    "Mod 是什么？",
    "给新手解释一下加载器和普通 Mod 的区别。",
    "Nexus 和 Thunderstore 有什么区别？",
    "什么叫替换同一个服装槽位？",
    "CNS 叠加层大概是怎么工作的？",
    "安装计划里的前置是什么意思？",
    "快照功能能保护哪些东西？",
    "帮我解释一下版本 unknown 代表什么。",
    "Steam 创意工坊订阅和本地安装有什么区别？",
    "Can you explain what a mod loader is?",
    "What does source verification mean?",
    "用一句话介绍 ModAgent。",
], must_not_use=_MUTATIONS + _SEARCH)

# 18: focused name/function searches
CORE_CASES += _make("search", "search_exact", AgentMode.SEARCH_EXACT, [
    "有没有数值修改器，新手一点钱都没有，怎么办？",
    "帮我找 Demonologist 能改钱的 Mod。",
    "找一下只修改玩家金币的工具。",
    "有没有让新手开局多一点资源的 Mod？",
    "搜索 AD ASTRA Teleporter。",
    "帮我找 FF7 Tifa 的 EVE 换皮。",
    "有没有雷电芽衣的角色替换？",
    "找一下能跳过启动 Logo 的 Mod。",
    "哪里有 BetterMapFix？",
    "搜一下适配当前游戏的中文补丁。",
    "有没有只增加背包容量的 Mod？",
    "帮我找支持当前版本的第一人称 Mod。",
    "Search for a money editor for this game.",
    "Find the exact mod named MenuLib.",
    "Is there a Tifa character replacement mod?",
    "Search Nexus for Synthetic Authority.",
    "帮我找这个角色的眼睛颜色替换。",
    "有没有解决卡墙问题的传送工具？",
], must_not_use=_MUTATIONS)

# 12: broad discovery
CORE_CASES += _make("recommend", "recommend_broad", AgentMode.RECOMMEND_BROAD, [
    "推荐几个适合新手的 Mod。",
    "有什么热门 Mod 值得装？",
    "找几个好玩的玩法 Mod。",
    "推荐一些提升体验但不过度作弊的 Mod。",
    "最近有什么必装 Mod？",
    "推荐几个画质类 Mod。",
    "有哪些人气比较高的服装 Mod？",
    "帮我挑一些稳定的基础 Mod。",
    "best mods for beginners",
    "Recommend a few quality-of-life mods.",
    "What popular mods are worth trying?",
    "推荐几个我还没装的 Mod。",
], must_not_use=_MUTATIONS)

# 10: source/detail resolution
CORE_CASES += _make("resolve", "resolve_source", AgentMode.RESOLVE_SOURCE, [
    "补齐这个条目的来源详情。",
    "检查一下它的真实来源。",
    "我想手动添加网址然后重新对齐。",
    "重新对齐刚才选中的 Mod。",
    "补齐前置依赖信息。",
    "核验这个 Nexus 页面是不是同一个 Mod。",
    "把当前候选的来源信息补完整。",
    "resolve the selected source",
    "realign this installed mod",
    "检查来源，不要重新推荐。",
], selection_action="resolve", has_selection=True, must_not_use=_MUTATIONS + _SEARCH)

# 16: plan/dependency/variant/conflict
CORE_CASES += _make("plan", "build_plan", AgentMode.BUILD_PLAN, [
    "为已勾选的 Mod 生成安装计划。",
    "生成计划并列出全部前置。",
    "先检查冲突，再给安装顺序。",
    "把变体选择放进安装计划。",
    "看看这些 Mod 会不会覆盖同一槽位。",
    "只为我选中的两项制定计划。",
    "给这批 Mod 排一下依赖顺序。",
    "计划里标清哪些已经安装。",
    "生成一个不写盘的预检报告。",
    "先核验加载器版本再出计划。",
    "build an install plan for my selection",
    "check variants and conflicts before installing",
    "show dependencies for the selected mods",
    "prepare the plan but do not install",
    "安装之前先给我推荐的变体选择。",
    "为合集目标生成可确认安装计划。",
], selection_action="plan", has_selection=True, must_not_use=_MUTATIONS)

# 16: confirmed execution
CORE_CASES += _make("execute", "execute_plan", AgentMode.EXECUTE_PLAN, [
    "确认下载并安装已勾选项。",
    "按刚才的计划安装。",
    "执行安装计划。",
    "开始安装我选择的两个 Mod。",
    "继续安装剩余项目。",
    "确认安装这个变体。",
    "现在执行已核验的清单。",
    "安装确认卡已经选好了，继续。",
    "只安装勾选项，不要加别的。",
    "继续执行刚才暂停的安装。",
    "install the selected items",
    "confirm and install this plan",
    "continue the verified installation",
    "execute the selected variant",
    "install only what I selected",
    "start the approved install plan",
], selection_action="confirm", has_selection=True, mutation_allowed=True)

# 10: installed-mod update work
CORE_CASES += _make("update", "update_installed", AgentMode.UPDATE_INSTALLED, [
    "检查更新。",
    "看看已安装 Mod 有没有更新。",
    "帮我更新已有 Mod。",
    "把所有已装 Mod 更新到最新版。",
    "同步这些模组的最新版本。",
    "检测可用更新。",
    "只检查本机清单的更新，不要推荐新 Mod。",
    "check for updates",
    "update my installed mods",
    "upgrade all existing mods",
], must_not_use=_SEARCH)

# 10: diagnosis and snapshot/rollback
CORE_CASES += _make("diagnose", "diagnose", AgentMode.DIAGNOSE, [
    "为什么这个 Mod 不生效？",
    "游戏启动后黑屏，先帮我诊断原因。",
    "安装后没有反应，怎么回事？",
    "检查一下是不是缺少依赖。",
    "Why is this mod not working?",
    "diagnose the crash without changing files",
], must_not_use=_MUTATIONS + _SEARCH)
CORE_CASES += _make("snapshot", "snapshot_rollback", AgentMode.SNAPSHOT_ROLLBACK, [
    "预览恢复这个快照会影响什么。",
    "我想回滚到安装前。",
    "列出并检查快照。",
    "preview snapshot restore",
], must_not_use=_SEARCH)

# 8: official/player shares
CORE_CASES += _make("share", "share_import", AgentMode.IMPORT_SHARE, [
    "导入官方合集 ma-repo-000002。",
    "读取这个 ma-xxxxxx 分享码。",
    "导入社区合集并核验。",
    "我粘贴了一份玩家分享 JSON。",
    "从 GitHub Raw 导入这个合集。",
    "检查这个 Gist 分享，不要直接安装。",
    "import this ModAgent share code",
    "open the official collection catalog",
], must_not_use=_SEARCH + _MUTATIONS)

# 8: regeneration/lifecycle boundaries
CORE_CASES += _make("regen", "lifecycle", AgentMode.CHAT_EXPLAIN, [
    "重新生成刚才的说明。",
    "换一种说法解释上一条结果。",
    "Regenerate the answer only.",
    "Rewrite the summary in English.",
], regenerate=True, must_not_use=_MUTATIONS + _SEARCH, severity="P0")
CORE_CASES += _make("lifecycle", "lifecycle", AgentMode.CHAT_EXPLAIN, [
    "停止当前任务。",
    "先回答我现在这个问题，不要继续旧任务。",
    "What happened to the previous task?",
    "只说明刚才完成了什么。",
], must_not_use=_MUTATIONS + _SEARCH, severity="P0")


EXPECTED_CATEGORY_COUNTS = {
    "chat_explain": 12,
    "search_exact": 18,
    "recommend_broad": 12,
    "resolve_source": 10,
    "build_plan": 16,
    "execute_plan": 16,
    "update_installed": 10,
    "diagnose": 6,
    "snapshot_rollback": 4,
    "share_import": 8,
    "lifecycle": 8,
}
