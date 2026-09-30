from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from typing import Any, Callable

from .models import AgentMode


@dataclass(frozen=True)
class RouteDecision:
    intent: AgentMode
    confidence: float
    reason: str
    targets: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    read_only: bool = True
    install_authorized: bool = False
    destructive_authorized: bool = False
    search_goal: str = ""


_UPDATE = re.compile(
    r"检查更新|检测更新|可用更新|有没有更新|更新(?:已有|已装|模组|mod)|"
    r"更新.*(?:最新版|已装|mod|模组)|升级(?:模组|mod)|同步.*最新|批量更新|"
    r"全部更新|check\s*(?:for\s*)?updates?|update\s*(?:my\s*)?(?:installed\s*)?mods?|"
    r"upgrade\s+(?:all\s+)?(?:existing\s+)?mods?",
    re.I,
)
_STATUS = re.compile(
    r"装了吗|安装了吗|有没有装|是否安装|已经安装|已安装|当前状态|"
    r"为什么还推荐|already\s*installed|is\s+it\s+installed",
    re.I,
)
_DIAGNOSE = re.compile(
    r"为什么|怎么回事|什么原因|诊断|排查|报错|异常|崩溃|黑屏|打不开|"
    r"进不去|不生效|没生效|没反应|不起作用|缺少依赖|依赖缺失|"
    r"missing\s*dependency|not\s*working|\bdiagnose\b",
    re.I,
)
_SHARE = re.compile(
    r"\bma-[a-z0-9-]{4,}\b|导入(?:社区|官方|玩家)?合集|分享码|"
    r"玩家分享.*json|github\s*raw|\bgist\b|share\s*(?:code|import)|"
    r"official\s+collection\s+catalog",
    re.I,
)
_SNAPSHOT = re.compile(
    r"快照|回滚|恢复(?:到|快照)|还原|删除快照|snapshot|rollback|restore",
    re.I,
)
_PLAN = re.compile(
    r"安装计划|依赖计划|冲突检查|选择变体|生成计划|build\s*(?:an?\s*)?install\s*plan",
    re.I,
)
_EXECUTE = re.compile(
    r"确认(?:下载并)?安装|按计划安装|执行安装|开始安装|继续安装|"
    r"install\s*(?:the\s*)?(?:selected|plan)|confirm\s*install",
    re.I,
)
_RESOLVE = re.compile(
    r"补齐(?:详情|信息|来源|前置)|手动添加网址|重新对齐|检查来源|来源核验|"
    r"resolve\s*source|realign",
    re.I,
)
_BROAD = re.compile(
    r"推荐(?:几个|一些|好用|热门|必装)?|热门mod|好玩的(?:玩法)?mod|找几个好玩的|"
    r"有哪些人气|帮我挑一些|最火|最热门|值得装|必装|best\s+mods?|"
    r"popular\s+mods?|recommend|最适合我的?\s*mod|适合新手的?\s*mod",
    re.I,
)
_SEARCH = re.compile(
    r"有没有|帮我找|找一下|找找|搜索|搜一下|搜搜|帮我搜|哪里有|"
    r"search|\bfind\b|\blook\s+up\b|\bis\s+there\b",
    re.I,
)
_EXPLICIT_CHANGE = re.compile(
    r"帮我|给我|直接|确认|开始|执行|install|update|disable|uninstall|restore",
    re.I,
)
_EXPLAIN = re.compile(
    r"是什么|是什么意思|什么意思|什么叫|有什么区别|有何区别|解释|给新手解释|"
    r"怎么工作|能保护哪些|一句话介绍|刚才.*(?:做了|干了|干嘛)|"
    r"what\s+(?:is|does|did\s+you)|explain|difference",
    re.I,
)

_STOP_SEARCH = re.compile(
    r"(?:不(?:要|用|需要)|先别|别|停止|暂停|取消|暂不)(?:再|继续|帮我|给我|进行|\s)*"
    r"(?:搜索|搜|找|推荐)|不搜了|算了|今天先到这里|先这样|"
    r"(?:don't|do not|stop|cancel|pause)\s+(?:(?:keep|continue|any|further)\s+)*(?:search|look|recommend)", re.I)
_REFINEMENT = re.compile(
    r"辅助|学习|界面|优化|新手|难度|画面|服装|角色|换皮|单人|联机|离线|免费|"
    r"不要.*(?:妆|衣|皮肤)|只要|想要|都要|这两|前者|后者|第一|第二|"
    r"\b(?:ui|hud|learning|beginner|training|offline|single.?player|multiplayer|cosmetic|free|both)\b", re.I)

_CONTINUE_SEARCH = re.compile(
    r"^(?:继续(?:搜索|搜搜|搜|找找|找)|再(?:搜索|搜搜|搜|找找|找)|"
    r"search again|keep searching|find more)(?:一下|看看|吧|please|[\s。.!！?？])*$", re.I)

# A continuation plus a qualifier is still the old goal, not a new search.
# Only the residual qualifier may extend it; explicit new recommendations win.
_CONTINUE_FRAGMENT = re.compile(r'继续(?:搜索|搜|找)|再(?:搜索|搜|找)|search again|keep searching|find more', re.I)

def _compound_refinement(text: str) -> bool:
    residual = _CONTINUE_FRAGMENT.sub(' ', text)
    return residual != text and bool(_REFINEMENT.search(residual)) and not (
        _BROAD.search(residual) or _SEARCH.search(residual))


def _search_context(message: str, history: list[dict] | None) -> str:
    """Only recent USER requests can establish a read-only search refinement.

    Assistant prose, tool results and quoted README text cannot authorize it.
    A question/cancellation or topic switch breaks the chain.
    """
    if not history or not (_REFINEMENT.search(message) or _CONTINUE_SEARCH.fullmatch(message)) or len(message) > 600:
        return ""
    parts = [message]
    users = [str(m.get("content") or "") for m in history[-12:] if m.get("role") == "user"]
    for previous in reversed(users[-3:]):
        if previous.startswith("[上下文数据") or _STOP_SEARCH.search(previous):
            break
        from .status_report import is_process_question
        if _EXPLAIN.search(previous) or _DIAGNOSE.search(previous) or _EXECUTE.search(previous) or is_process_question(previous):
            break
        if _CONTINUE_SEARCH.fullmatch(previous) or _compound_refinement(previous):
            parts.append(previous)
            continue
        if _BROAD.search(previous) or _SEARCH.search(previous):
            return "\n".join([previous, *reversed(parts)])[:1800]
        if _REFINEMENT.search(previous) and len(previous) <= 600:
            parts.append(previous)
        else:
            break
    return ""

_NEGATED_CHANGE = re.compile(
    r"(?:不要|别|不许|禁止|不需要|先不|暂不|无需).{0,12}"
    r"(?:安装|下载|更新|删除|卸载|禁用|恢复|回滚|写入)|"
    r"(?:do\s+not|don't|without|never)\s+(?:\w+\s+){0,3}"
    r"(?:install\w*|download\w*|updat\w*|delet\w*|uninstall\w*|restor\w*)",
    re.I,
)


def negates_changes(message: str) -> bool:
    """Conservative hold: mixed/quoted instructions need a fresh plan decision."""
    return bool(_NEGATED_CHANGE.search(str(message or "")))


def route_message(
    message: str,
    *,
    selection_action: str = "",
    regenerate: bool = False,
    has_selection: bool = False,
    execution_granted: bool = False,
    classifier: Callable[[str], RouteDecision | None] | None = None,
    history: list[dict] | None = None,
) -> RouteDecision:
    """Return one bounded task mode without letting prose change permissions."""
    text = re.sub(r"\s+", " ", str(message or "")).strip()
    action = str(selection_action or "").strip().lower()

    if regenerate:
        return RouteDecision(AgentMode.CHAT_EXPLAIN, 1.0, "regenerate_is_read_only")
    from .status_report import is_process_question
    if not action and is_process_question(text):
        # A short clarification of an ordinary conversation must stay a
        # conversation. Earlier operations must not hijack the current topic.
        previous = next((str(item.get('content') or '') for item in reversed(history or [])
                         if item.get('role') == 'user' and not is_process_question(str(item.get('content') or ''))), '')
        if previous and _EXPLAIN.search(previous) and not re.search(r'刚才|上一|本轮|任务|确认卡|what just|what did you', text, re.I):
            return RouteDecision(AgentMode.CHAT_EXPLAIN, .99, 'conversation_clarification')
        return RouteDecision(AgentMode.CHAT_EXPLAIN, 1.0, "recorded_process_status")
    if action == "resolve":
        return RouteDecision(AgentMode.RESOLVE_SOURCE, 1.0, "structured_selection_resolve")
    if action == "plan":
        return RouteDecision(AgentMode.BUILD_PLAN, 1.0, "structured_selection_plan")
    if action == "confirm":
        return RouteDecision(
            AgentMode.EXECUTE_PLAN, 1.0, "structured_selection_confirm",
            read_only=not bool(has_selection and execution_granted),
            install_authorized=bool(has_selection and execution_granted),
        )
    if (_STOP_SEARCH.search(text) and not _UPDATE.search(text)) or re.fullmatch(r"[?？!！.。\s]+", text):
        return RouteDecision(AgentMode.CHAT_EXPLAIN, .99, "search_stopped_or_status_followup")
    if re.search(r"有没有.*(?:方法|办法|建议|技巧)", text) and not re.search(r"mod|模组|搜索|帮我搜|帮我找", text, re.I):
        return RouteDecision(AgentMode.CHAT_EXPLAIN, .93, "general_help_question")
    # Questions about an action are not that action. Classification never
    # authorizes natural-language writes, even if a selection is still visible.
    if _EXPLAIN.search(text):
        return RouteDecision(AgentMode.CHAT_EXPLAIN, .95, "explanation_question")
    if _DIAGNOSE.search(text) and _UPDATE.search(text):
        return RouteDecision(AgentMode.DIAGNOSE, .94, "diagnostic_question")
    if _SHARE.search(text):
        return RouteDecision(AgentMode.IMPORT_SHARE, .99, "share_identity")
    if _UPDATE.search(text):
        return RouteDecision(
            AgentMode.UPDATE_INSTALLED, .98, "installed_update",
        )
    if _STATUS.search(text) and not _EXECUTE.search(text):
        return RouteDecision(AgentMode.STATUS_CHECK, .98, "installed_status_question")
    if _DIAGNOSE.search(text):
        return RouteDecision(AgentMode.DIAGNOSE, .94, "diagnostic_question")
    if _EXPLAIN.search(text):
        return RouteDecision(AgentMode.CHAT_EXPLAIN, .95, "explanation_question")
    if _SNAPSHOT.search(text):
        destructive = bool(_EXPLICIT_CHANGE.search(text))
        return RouteDecision(
            AgentMode.SNAPSHOT_ROLLBACK, .98, "snapshot_or_rollback",
            read_only=not destructive, destructive_authorized=False,
        )
    if _RESOLVE.search(text):
        return RouteDecision(AgentMode.RESOLVE_SOURCE, .96, "source_resolution")
    if _PLAN.search(text):
        return RouteDecision(AgentMode.BUILD_PLAN, .97, "plan_request")
    if _EXECUTE.search(text):
        return RouteDecision(
            AgentMode.EXECUTE_PLAN, .94, "explicit_execution_request",
        )
    if _CONTINUE_SEARCH.fullmatch(text):
        search_goal = _search_context(text, history)
        if search_goal:
            return RouteDecision(AgentMode.SEARCH_EXACT, .96, "explicit_search_continuation", search_goal=search_goal)
        return RouteDecision(AgentMode.CHAT_EXPLAIN, .75, "search_goal_needs_clarification")
    if _compound_refinement(text):
        search_goal = _search_context(text, history)
        if search_goal:
            return RouteDecision(AgentMode.SEARCH_EXACT, .92, "search_refinement", search_goal=search_goal)
        return RouteDecision(AgentMode.CHAT_EXPLAIN, .75, "search_goal_needs_clarification")
    if _BROAD.search(text):
        return RouteDecision(AgentMode.RECOMMEND_BROAD, .91, "broad_recommendation", search_goal=text)
    if _SEARCH.search(text):
        return RouteDecision(AgentMode.SEARCH_EXACT, .90, "focused_search", search_goal=text)

    search_goal = _search_context(text, history)
    if search_goal:
        return RouteDecision(AgentMode.SEARCH_EXACT, .92, "search_refinement", search_goal=search_goal)

    if classifier is not None:
        try:
            classified = classifier(text)
        except Exception:
            classified = None
        if isinstance(classified, RouteDecision):
            return replace(classified, read_only=True, install_authorized=False,
                           destructive_authorized=False)
    return RouteDecision(AgentMode.CHAT_EXPLAIN, .60, "safe_fallback")
