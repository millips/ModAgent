import json
import logging
import os
import re
import time
import threading
from concurrent.futures import ThreadPoolExecutor, TimeoutError as _ToolTimeout
from .config import Config, Tier
from .prompts import build_prompt
from .tools import build_tools_definitions, execute, refresh_local_inventory
from . import db
from . import task_control
from .orchestration.models import AgentMode, TaskSpec
from .orchestration.policies import MUTATING_TOOLS, filter_tool_definitions
from .orchestration.router import negates_changes, route_message
from .orchestration.outcomes import ToolOutcome
from .orchestration.prompting import (
    build_v2_prompt, build_mode_prompt, data_message, measure_request,
)
from .orchestration.runtime import AgentCoreRuntime
from .recommendation_ui import (
    apply_chinese_descriptions,
    has_exact_target_candidate,
    merge_recommendation_resolution,
    needs_chinese_name,
    needs_chinese_localization,
    promote_verified_recommendation,
    recommendation_analysis_text,
    recommendations_from_tool_evidence,
)

# 工具看门狗:任何工具超过此秒数未返回,视为卡死,返回错误让对话继续
# (被卡住的线程无法强杀,会残留在后台,但 SSE 流不再被拖死)
TOOL_TIMEOUT_S = 300
# Discovery must be bounded separately from the global tool-loop safeguard.
# The global round cap protects every kind of tool call; it is not a sensible
# search policy and used to let a model fan out into dozens of vague aliases.
MAX_SEARCH_DISCOVERY_CALLS_PER_TURN = 8
MAX_SEARCH_CALLS_PER_SOURCE = 4
MAX_SEARCH_QUERY_ALIASES = 3
SEARCH_DISCOVERY_TOOLS = {
    "mod_recommend", "nexus_search", "workshop_search",
    "thunderstore_search", "github_search", "gamebanana_search",
}
_TOOL_POOL = ThreadPoolExecutor(max_workers=4, thread_name_prefix="tool")
RECOMMENDATION_TARGET_TOOLS = {
    "nexus_get_detail", "mod_download", "mod_install",
    "batch_download", "mod_install_batch", "mod_install_custom",
    "download_from_url",
}
DOWNLOAD_EXECUTION_TOOLS = {
    "mod_download", "download_from_url", "batch_download",
}

# "补齐当前需要" is a verification-only state.  Tool schemas are filtered
# below for normal model turns, but that alone is not a security boundary:
# stale renderers, retries and a malformed tool call can still reach _exec.
# Keep a deliberately small read-only allow-list here as the authoritative
# guard.  A resolve turn may inspect the already selected source and the local
# game state; it may never search broadly, download, install or mutate state.
RESOLUTION_READONLY_TOOLS = {
    "browser_pages", "browser_doctor", "browser_observe", "browser_wait",
    "browser_open", "nexus_get_detail", "game_file_check",
}

# P2.4:汇报事实校验(把 report_validator.py 放到 modagent/ 下)
try:
    from .report_validator import validate_report, build_correction_message
    from .report_validator import check_unsourced_state, build_state_correction_message
    from .report_validator import (
        validate_search_report, build_search_correction_message,
        build_search_fallback, check_unfulfilled_action_promise,
        build_action_promise_correction_message,
    )
    _HAS_VALIDATOR = True
except Exception:
    _HAS_VALIDATOR = False

# 开发者模式 trace(把 debug_trace.py 放到 modagent/ 下)
try:
    from . import debug_trace
    _HAS_TRACE = True
except Exception:
    _HAS_TRACE = False

# 开关:出问题可快速回退
ENABLE_REPORT_VALIDATION = True      # P2.4
ENABLE_STATE_CHECK = True            # v1:状态类回答必须有工具来源,否则拦下重跑
# 工具调用前的模型草稿不直接展示（避免把“准备下载”误写成“已经下载”），
# 但 chat_stream 会另外发送可信的 progress 事件，不能因此让界面静默。
BUFFER_PRETOOL_TEXT = True
MAX_ROUNDS = 20
MAX_EMPTY_RETRIES = 1                # P2.2:连续空响应最多纠偏一次


def collapse_repeated_response(value: str) -> str:
    """Remove an accidental exact second copy of a long final response."""
    text = str(value or "").strip()
    if len(text) < 80:
        return text
    marker = text[: min(72, len(text) // 3)]
    start = text.find(marker, max(40, len(text) // 3))
    while start >= 0:
        left = text[:start].strip()
        right = text[start:].strip()
        if left == right:
            return left
        start = text.find(marker, start + 1)
    return text


def structured_plan_footer(value: str) -> str:
    """Keep a structured plan inside the decision card, never a text y/n detour.

    An LLM may still inherit the generic installation-plan wording from an old
    conversation.  The UI already owns the selected files and final confirm
    button, so leaving a manual ``A/B/y/n`` instruction in the prose creates a
    second, conflicting interaction path.
    """
    text = str(value or "").strip()
    # Only remove standalone closing prompts.  Do not touch useful technical
    # evidence elsewhere in the report.
    text = re.sub(
        r"(?im)^.*(?:请逐项回复|请回复.*(?:y\s*/\s*n|A、B)|确认按此计划|确认后我.*(?:下载|安装)|回复.*(?:y\s*/\s*n)).*$",
        "",
        text,
    ).strip()
    footer = (
        "请通过结果卡的“查看待确认清单”返回安装确认卡，核对目标和变体。"
        "只有看到可用的“确认下载并安装”按钮时才能继续；如果入口未就绪，请重新核验计划。"
        "无需手动输入 A/B/C 或 y/n，也不要用聊天指令绕过确认。"
    )
    return (text + "\n\n" + footer).strip()


def user_visible_progress(tool_name: str, ordinal: int) -> dict:
    """Map a low-level tool call to a truthful, non-chain-of-thought stage."""
    name = str(tool_name or "")
    if name == 'mod_recommend':
        return {'stage': 'search', 'label': '正在按需求搜索并核验候选', 'label_en': 'Searching and verifying candidates for your request'}
    if name in {"nexus_search", "thunderstore_search", "gamebanana_search", "github_search", "workshop_search"}:
        return {"stage": "search", "label": f"正在搜索相关来源（第 {ordinal} 轮）"}
    if name in {"nexus_get_detail", "read_readme", "browser_observe", "game_file_check", "get_installed", "conflict_check"}:
        return {"stage": "verify", "label": f"正在核验文件、依赖与冲突（第 {ordinal} 项）"}
    if name in {"mod_download", "batch_download", "download_from_url", "workshop_install"}:
        return {"stage": "download", "label": "正在准备并下载已确认的 Mod"}
    if name in {"mod_install", "mod_install_batch", "mod_install_custom"}:
        return {"stage": "install", "label": "正在执行已确认的安装计划"}
    return {"stage": "process", "label": "正在整理核验结果"}


def sanitize_tool_history(history: list[dict]) -> list[dict]:
    """Repair interrupted tool-call turns before sending them back to an LLM."""
    repaired: list[dict] = []
    index = 0
    while index < len(history):
        message = history[index]
        role = message.get("role")
        calls = message.get("tool_calls") if role == "assistant" else None
        if calls:
            valid_calls = [
                call for call in calls
                if isinstance(call, dict) and str(call.get("id") or "").strip()
            ]
            index += 1
            following = []
            while index < len(history) and history[index].get("role") == "tool":
                following.append(history[index])
                index += 1
            if not valid_calls:
                if str(message.get("content") or "").strip():
                    repaired.append({"role": "assistant", "content": message["content"]})
                continue
            assistant = dict(message)
            assistant["tool_calls"] = valid_calls
            repaired.append(assistant)
            available = {}
            for tool_message in following:
                tool_id = str(tool_message.get("tool_call_id") or "")
                if tool_id and tool_id not in available:
                    available[tool_id] = tool_message
            for call in valid_calls:
                call_id = str(call["id"])
                repaired.append(available.get(call_id, {
                    "role": "tool",
                    "tool_call_id": call_id,
                    "content": json.dumps({
                        "error": "tool_result_missing",
                        "message": "该历史工具调用未完整保存，已安全跳过；如仍需要请重新调用。",
                    }, ensure_ascii=False),
                }))
            continue
        if role != "tool":
            repaired.append(message)
        index += 1
    return repaired


def compact_history_for_v2(history: list[dict], budget: int = 4000) -> list[dict]:
    """Keep recent conversational context without replaying large tool payloads."""
    selected: list[dict] = []
    used = 0
    for message in reversed(history or []):
        role = str(message.get("role") or "")
        if role not in {"user", "assistant"}:
            continue
        content = str(message.get("content") or "").strip()
        if not content:
            continue
        content = content[:1000]
        cost = len(content) + 24
        if selected and used + cost > max(1000, int(budget)):
            break
        selected.append({"role": role, "content": content})
        used += cost
    selected.reverse()
    return selected

# 重新生成只能重写回答，不能重放已经生效的操作。这里同时移除会写磁盘、
# 改订阅、发起下载或继续网页操作的工具；_exec 里还有第二道防线，避免模型
# 或调用方绕过工具定义直接触发。
REGENERATE_BLOCKED_TOOLS = {
    "browser_click", "browser_input", "browser_open",
    "import_existing_mods",
    "download_from_url", "workshop_install", "workshop_uninstall",
    "mod_download", "batch_download",
    "mod_install_batch", "mod_install", "mod_install_custom", "tool_extract",
    "mod_uninstall",
    "snapshot_create", "snapshot_restore", "snapshot_delete",
    "mod_patch", "game_config_write", "mod_update", "mod_disable", "mod_enable",
    "mod_dependency_set", "mod_source_align", "mod_source_bind",
}

# A question about current state is not authorization to change that state.
# Keep this separate from regeneration: it applies to ordinary user turns too.
STATUS_QUESTION_BLOCKED_TOOLS = REGENERATE_BLOCKED_TOOLS | {
    "mod_update_check",
}

# A diagnostic question authorizes inspection, not a configuration change.
# Discovery is excluded too: missing local evidence must be reported instead
# of silently turning diagnosis into a new-Mod recommendation flow.
DIAGNOSTIC_SCOPE_BLOCKED_TOOLS = SEARCH_DISCOVERY_TOOLS | {
    "browser_click", "browser_input",
    "import_existing_mods",
    "download_from_url", "workshop_install", "workshop_uninstall",
    "mod_download", "batch_download",
    "mod_install_batch", "mod_install", "mod_install_custom", "tool_extract",
    "mod_uninstall",
    "snapshot_create", "snapshot_restore", "snapshot_delete",
    "mod_patch", "game_config_write", "mod_update", "mod_disable", "mod_enable",
    "mod_dependency_set", "mod_source_align", "mod_source_bind",
}


def is_diagnostic_read_only_request(value: str) -> bool:
    """Detect diagnosis/why questions that do not authorize a state change."""
    text = str(value or "").strip().casefold().replace(" ", "")
    if not text:
        return False
    diagnostic_terms = (
        "为什么", "怎么回事", "什么原因", "诊断", "排查", "检查一下",
        "不生效", "没生效", "没有生效", "报错", "异常", "崩溃", "黑屏",
        "打不开", "进不去", "没有怪", "没怪", "怪不见", "怪都没有",
        "一个怪都没有", "缺少依赖",
        "没有依赖", "依赖缺失", "没有反应", "没反应", "没有效果",
        "没效果", "不起作用", "不显示", "没显示", "没有显示",
        "missingdependency", "notworking",
    )
    explicit_changes = (
        "帮我禁用", "直接禁用", "确认禁用", "帮我卸载", "直接卸载",
        "帮我删除", "直接删除", "帮我安装", "直接安装", "帮我更新",
        "直接更新", "帮我修复", "直接修复", "帮我启用", "直接启用",
        "帮我回滚", "直接回滚",
        "disableit", "uninstallit", "removeit", "installit", "fixit",
    )
    symptom_after_action = (
        any(term in text for term in ("按了之后", "启动后", "进游戏后", "安装后"))
        and any(term in text for term in ("没有", "没", "只有", "仅有", "无"))
    )
    return (
        (any(term in text for term in diagnostic_terms) or symptom_after_action)
        and not any(term in text for term in explicit_changes)
    )


def is_status_only_question(value: str) -> bool:
    text = str(value or "").strip().casefold().replace(" ", "")
    if not text:
        return False
    status_terms = (
        "已安装", "已经安装", "安装了吗", "装了吗", "装过", "已经有", "已有",
        "有没有装", "是否安装", "是不是有", "哪些安装", "当前状态",
        "installed", "alreadyinstalled",
    )
    question_terms = ("吗", "么", "是否", "是不是", "有没有", "哪些", "?", "？")
    explicit_actions = (
        "帮我安装", "给我安装", "直接安装", "开始安装", "继续安装",
        "帮我装", "给我装", "直接装", "开始装",
        "帮我下载", "给我下载", "直接下载", "开始下载",
        "帮我更新", "给我更新", "直接更新", "开始更新",
        "没装就装", "没有就装", "未安装就安装",
        "installit", "downloadit", "updateit",
    )
    return (
        any(term in text for term in status_terms)
        and any(term in text for term in question_terms)
        and not any(term in text for term in explicit_actions)
    )


def is_update_request(value: str) -> bool:
    """Identify installed-Mod update work without confusing it with new recommendations."""
    text = str(value or "").strip().casefold().replace(" ", "")
    if not text:
        return False
    update_terms = (
        "检查更新", "检测更新", "看看更新", "有没有更新", "可用更新",
        "更新已有", "更新已装", "更新模组", "更新mod", "升级模组", "升级mod",
        "帮我更新", "给我更新", "直接更新", "开始更新", "继续更新",
        "同步最新版", "同步最新版本", "批量更新", "全部更新", "都更新",
        "一键更新", "更新吧",
        "checkupdates", "checkforupdates", "updatemods", "updatemymods",
    )
    if any(term in text for term in update_terms):
        return True
    recommendation_terms = ("推荐", "搜索", "搜一下", "找几个", "最火", "热门")
    installed_scope = ("mod", "模组", "已安装", "现有", "这些", "它们", "所有")
    update_action = ("更新", "升级", "同步")
    return (
        any(term in text for term in installed_scope)
        and any(term in text for term in update_action)
        and not any(term in text for term in recommendation_terms)
    )


def is_broad_recommendation_request(value: str) -> bool:
    """Use the source-ledger aggregator for broad discovery requests."""
    text = str(value or "").strip().casefold().replace(" ", "")
    if not text:
        return False
    discovery = (
        "推荐", "搜索", "搜一下", "找一下", "找找", "找几个", "有没有mod",
        "有没有模组", "扩展mod", "扩展模组", "热门mod", "好玩的mod",
        "最热门", "热门的", "最火", "最好", "最色", "人气", "火爆",
        "值得装", "必装",
    )
    explicit_source = (
        "nexus", "thunderstore", "github", "gamebanana",
        "创意工坊", "steamworkshop",
    )
    return (
        any(term in text for term in discovery)
        and not any(term in text for term in explicit_source)
        and not explicit_install_target(value)
    )


_ENTITY_ALIASES = {
    "benplex": "BepInEx",
    "beniplex": "BepInEx",
    "bepin ex": "BepInEx",
    "bepinex": "BepInEx",
}


def normalize_contextual_install_target(
    target: dict[str, str], prior_reply: str = "",
) -> tuple[dict[str, str], str]:
    """Resolve common loader misspellings before any multi-source search."""
    if not target:
        return {}, ""
    raw_name = str(target.get("name") or "").strip()
    folded = re.sub(r"\s+", " ", raw_name.casefold())
    canonical = _ENTITY_ALIASES.get(folded)
    prior = str(prior_reply or "").casefold()
    if canonical and (
        canonical.casefold() in prior
        or folded in _ENTITY_ALIASES
    ):
        normalized = dict(target)
        normalized["name"] = canonical
        return normalized, raw_name
    return target, ""


def is_short_install_confirmation(value: str, prior_reply: str = "") -> bool:
    text = str(value or "").strip().casefold().replace(" ", "")
    # Newer UI actions use Chinese verbs such as "continue" after a staged
    # collection plan.  Keep this gated by an actual prior confirmation
    # prompt so an unrelated conversational "continue" cannot install.
    chinese_confirmations = {
        "\u786e\u8ba4", "\u786e\u8ba4\u5b89\u88c5", "\u5b89\u88c5\u5427",
        "\u7ee7\u7eed", "\u7ee7\u7eed\u5b89\u88c5", "\u7ee7\u7eed\u6267\u884c",
        "\u4e0b\u4e00\u6b65", "\u4e0b\u4e00\u9636\u6bb5",
    }
    prior = str(prior_reply or "")
    if text in chinese_confirmations and any(
        marker in prior for marker in (
            "\u5b89\u88c5\u8ba1\u5212", "\u786e\u8ba4\u5b89\u88c5",
            "\u786e\u8ba4\uff1f", "\u786e\u8ba4?",
        )
    ):
        return True
    confirmations = {
        "y", "yes", "ok", "okay", "确认", "确认安装", "安装吧", "继续安装",
    }
    return text in confirmations and any(
        marker in prior for marker in ("安装计划", "确认安装", "确认？", "确认?")
    )


def explicit_install_target(value: str) -> dict[str, str]:
    """Extract one named/versioned Mod from a direct installation request."""
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if not text:
        return {}
    # “我没装的 / 尚未装的” describes a discovery filter, not permission to
    # install a Mod literally named “的”.  Keep any separate positive install
    # verb intact (for example “安装一个我没装的 X”).
    text = re.sub(r"(?:还)?(?:没|未|没有|尚未)装(?:过)?", "", text)
    deictic = re.search(
        r"(.+?)(?:请|麻烦)?(?:帮我|给我)?(?:下载并安装|下载安装|安装|装上|装)"
        r"\s*(?:一下)?\s*(?:这个|它)(?:\s*(?:mod|模组))?",
        text,
        flags=re.I,
    )
    raw_target = ""
    if deictic:
        candidates = re.findall(
            r"[A-Za-z0-9][A-Za-z0-9_.-]{4,}", deictic.group(1),
        )
        if candidates:
            raw_target = candidates[-1]
    match = re.search(
        r"(?:请|麻烦)?(?:帮我|给我)?(?:下载并安装|下载安装|安装|装上|装)"
        r"\s*(?:一下|一个)?\s*[“\"']?(.+?)[”\"']?\s*(?:吧|试试|看看)?[。！!？?]?$",
        text,
        flags=re.I,
    )
    if not raw_target and not match:
        return {}
    if not raw_target:
        raw_target = match.group(1).strip(" ：:，,。.!！?？\"'“”")
    if not raw_target or raw_target.casefold() in {
        "mod", "mods", "模组", "一个mod", "一个模组", "几个mod", "几个模组",
        "这个", "它", "这个mod", "这个模组",
    }:
        return {}
    raw_target = re.sub(
        r"^(?:custom_)?(?:ts_)?", "", raw_target, flags=re.I,
    )
    version_match = re.search(
        r"(?:^|[_\-\s])v?(\d+(?:\.\d+){1,4})$",
        raw_target,
        flags=re.I,
    )
    version = version_match.group(1) if version_match else ""
    name = re.sub(
        r"(?:[_\-\s])v?\d+(?:\.\d+){1,4}$", "", raw_target, flags=re.I,
    ).strip(" _-")
    return {"name": name or raw_target, "version": version}


class Agent:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.history: list[dict] = []
        self._client_obj = None
        self._turn_id = None          # 当前轮次的 trace id(显式传给 debug_trace,避免 contextvar 跨线程丢失)
        self._regenerating = False
        self._network_route = None
        self._current_user_msg = ""
        self._prior_assistant_text = ""
        self._turn_result_cache: dict[str, str] = {}
        self._turn_terminal_download_failures: dict[str, str] = {}
        self._turn_explicit_download_failure = ""
        self._destructive_preview_turns: dict[str, str | None] = {}
        self._status_only_turn = False
        self._diagnostic_read_only_turn = False
        self._turn_started_monotonic = time.monotonic()
        self._turn_search_calls = 0
        self._turn_search_calls_by_tool: dict[str, int] = {}
        self._turn_search_cache: dict[str, str] = {}
        self._turn_unique_search_queries: set[str] = set()
        self._update_intent = False
        self._update_completed_this_turn = False
        self._selection_action = ""
        self._selection_allowed_nexus_ids: set[str] = set()
        self._selection_nexus_alias_ids: dict[str, str] = {}
        self._selection_allowed_source_urls: set[str] = set()
        self._selection_download_paths: set[str] = set()
        self._selection_confirm_rows: list[dict] = []
        self._selection_strict_nexus = False
        self._selection_batch_download_attempted = False
        self._selection_batch_download_result = ""
        self._selection_batch_download_success: list[dict] = []
        self._selection_batch_download_complete = False
        self._selection_batch_install_result = ""
        self._install_completed_this_turn = False
        self._install_attempted_this_turn = False
        self._explicit_install_target: dict[str, str] = {}
        self._explicit_target_found = False
        self._manual_resume_turn = False
        self._manual_resume_targets: list[dict] = []
        self._core_spec: TaskSpec | None = None
        self._core_runtime: AgentCoreRuntime | None = None
        self._core_mode = "off"

    @property
    def client(self):
        if self._client_obj is None:
            from openai import OpenAI
            from .networking import build_http_client, validate_api_key
            api_key = validate_api_key(self.cfg.llm_api_key, "llm_api_key")
            http_client, self._network_route = build_http_client(
                self.cfg.llm_endpoint, timeout=120
            )
            self._client_obj = OpenAI(
                base_url=self.cfg.llm_endpoint,
                api_key=api_key,
                timeout=120,
                http_client=http_client,
            )
        return self._client_obj

    def reset(self):
        self.history = []

    def _current_mod_loader(self) -> str:
        configured = str(getattr(self.cfg, "mod_loader", "") or "").strip()
        if configured:
            return configured
        root = str(getattr(self.cfg, "game_root", "") or "")
        from .runtime_detection import active_loaders
        detected = active_loaders(root)
        return detected[0] if detected else ""

    @staticmethod
    def _selection_alias(value: object) -> str:
        """Normalize an exact selected-row label without enabling fuzzy matching."""
        return re.sub(r"\s+", " ", str(value or "").strip()).casefold()

    def _canonicalize_selected_nexus_args(self, name: str, args: dict) -> dict:
        """Map an exact selected row label back to its verified Nexus ID."""
        if self._selection_action != "confirm":
            return args

        def canonical(value: object) -> object:
            raw = str(value or "").strip()
            if not raw or raw in self._selection_allowed_nexus_ids:
                return value
            return self._selection_nexus_alias_ids.get(
                self._selection_alias(raw), value
            )

        normalized = dict(args)
        if name in {"nexus_get_detail", "mod_download", "mod_install"}:
            normalized["mod_id"] = canonical(normalized.get("mod_id"))
        elif name == "mod_install_batch":
            normalized["mod_ids"] = [
                canonical(item) for item in (normalized.get("mod_ids") or [])
            ]
            normalized["items"] = [
                {**item, "mod_id": canonical(item.get("mod_id"))}
                if isinstance(item, dict) else item
                for item in (normalized.get("items") or [])
            ]
        elif name == "batch_download":
            normalized["mods"] = [
                {**item, "mod_id": canonical(item.get("mod_id"))}
                if isinstance(item, dict) else item
                for item in (normalized.get("mods") or [])
            ]
        return normalized

    @staticmethod
    def _normalize_selection_rows(
        recommendation_selection: list[dict] | None,
    ) -> list[dict]:
        """Keep only the stable fields that identify the user's exact choice."""
        rows: list[dict] = []
        seen: set[tuple[str, str, str, str]] = set()
        for raw in recommendation_selection or []:
            if not isinstance(raw, dict):
                continue
            source = str(raw.get("source") or "").strip().casefold()
            mod_id = str(raw.get("mod_id") or raw.get("source_id") or "").strip()
            if not source or not mod_id:
                continue
            row = {
                "source": source,
                "mod_id": mod_id,
                "mod_name": str(
                    raw.get("mod_name")
                    or raw.get("localized_name")
                    or raw.get("name")
                    or ""
                ).strip(),
                "selection_key": str(raw.get("selection_key") or "").strip(),
                "file_id": str(raw.get("file_id") or "").strip(),
                "variant_id": str(
                    raw.get("selected_variant_id")
                    or raw.get("variant_id")
                    or ""
                ).strip(),
                "variant_name": str(raw.get("variant_name") or "").strip(),
                "file_name": str(raw.get("file_name") or "").strip(),
                "target_slot": str(raw.get("target_slot") or "").strip(),
                "version": str(raw.get("version") or "").strip(),
                "url": str(raw.get("url") or raw.get("source_url") or "").strip(),
            }
            identity = (
                source,
                mod_id,
                row["file_id"],
                row["variant_id"],
            )
            if identity in seen:
                continue
            seen.add(identity)
            rows.append(row)
        return rows

    @staticmethod
    def _selection_row_identity(row: dict) -> tuple[str, str, str]:
        return (
            str(row.get("mod_id") or ""),
            str(row.get("file_id") or ""),
            str(row.get("variant_id") or ""),
        )

    def _strict_selection_result(self, name: str, args: dict) -> str | None:
        """Enforce one exact download -> one exact install for Nexus selections."""
        if not (
            self._selection_action == "confirm"
            and self._selection_strict_nexus
            and self._selection_confirm_rows
        ):
            return None
        if name in {
            "mod_download",
            "download_from_url",
            "mod_install",
            "mod_install_custom",
        }:
            return json.dumps({
                "error": "selection_execution_mode_blocked",
                "status": "exact_batch_required",
                "tool": name,
                "install_blocked": True,
                "message": (
                    "本次确认包含结构化精确文件，必须一次性使用 batch_download "
                    "下载全部选中项；全部完成后再使用 mod_install_batch。"
                    "禁止单项重下、换源或绕过未完成项。"
                ),
            }, ensure_ascii=False)
        if name == "batch_download":
            if self._selection_batch_download_attempted:
                try:
                    prior = json.loads(self._selection_batch_download_result)
                except (ValueError, TypeError, json.JSONDecodeError):
                    prior = {"status": "failed"}
                prior["reused_result"] = True
                prior["message"] = (
                    "本轮精确批量下载已经执行过，直接复用结果，未重复下载。"
                )
                return json.dumps(prior, ensure_ascii=False)
            args.clear()
            args.update({
                "mods": [dict(row) for row in self._selection_confirm_rows],
                "require_verified_preflight": True,
            })
            return None
        if name == "mod_install_batch":
            if self._selection_batch_install_result:
                try:
                    prior = json.loads(self._selection_batch_install_result)
                except (ValueError, TypeError, json.JSONDecodeError):
                    prior = {"status": "failed"}
                prior["reused_result"] = True
                prior["message"] = "本轮精确安装已经执行过，未重复写入游戏目录。"
                return json.dumps(prior, ensure_ascii=False)
            if not self._selection_batch_download_complete:
                return json.dumps({
                    "status": "download_incomplete",
                    "install_blocked": True,
                    "total_selected": len(self._selection_confirm_rows),
                    "ready": len(self._selection_batch_download_success),
                    "message": (
                        "所选文件尚未全部完成下载或仍在等待人工验证；"
                        "安装未开始，未创建快照，也未写入游戏目录。"
                    ),
                }, ensure_ascii=False)
            # All selected rows may already be installed. No write is needed,
            # but the confirmation can truthfully finish.
            if not self._selection_batch_download_success:
                synthetic = {
                    "status": "completed",
                    "total": 0,
                    "succeeded": 0,
                    "failed": 0,
                    "all_selected_installed": True,
                    "already_installed": len(self._selection_confirm_rows),
                    "results": [],
                    "message": "所选 Mod 均已安装，未重复下载或覆盖。",
                }
                self._selection_batch_install_result = json.dumps(
                    synthetic, ensure_ascii=False
                )
                self._install_attempted_this_turn = True
                self._install_completed_this_turn = True
                return self._selection_batch_install_result
            args.clear()
            args.update({
                "items": [
                    dict(item)
                    for item in self._selection_batch_download_success
                ],
                "mod_ids": [],
                "require_verified_preflight": True,
            })
        return None

    def _batch_toggle_preflight(self, calls: list[dict]) -> str | None:
        """Preflight a multi-Mod enable/disable request before changing files.

        Steam Workshop entries use Steam's own local checkbox and cannot share
        the ordinary file-move transaction.  If one mixed batch contains such
        an entry, block every toggle in that batch so the user never gets the
        old half-success/half-failure result.
        """
        parsed = []
        for call in calls or []:
            function = call.get("function") or {}
            name = str(function.get("name") or "")
            if name not in {"mod_disable", "mod_enable"}:
                continue
            try:
                args = json.loads(function.get("arguments") or "{}")
            except (TypeError, ValueError, json.JSONDecodeError):
                args = {}
            parsed.append((name, args))
        if len(parsed) < 2:
            return None

        slug = str(getattr(self.cfg, "game_slug", "") or "")
        external = []
        local = []
        for name, args in parsed:
            mod_id = str(args.get("mod_id") or "").strip()
            mod = db.get_mod(mod_id, slug) if mod_id else None
            row = {
                "mod_id": mod_id,
                "name": str(getattr(mod, "name", "") or mod_id),
                "action": name,
            }
            if mod and (
                str(getattr(mod, "installed_by", "") or "") == "steam_workshop"
                or str(getattr(mod, "id", "") or "").startswith("ws_")
            ):
                external.append(row)
            else:
                local.append(row)
        if not external:
            return None
        return json.dumps({
            "blocked": True,
            "error": "mixed_toggle_batch_requires_split",
            "no_changes_made": True,
            "steam_workshop_targets": external,
            "local_file_targets": local,
            "message": (
                "批量预检发现 Steam 创意工坊项目。为避免先修改本地 Mod、随后才在工坊项失败，"
                "本批次没有改动任何文件。请先在 Steam → 游戏属性 → 创意工坊中调整工坊项目的"
                "本地启用复选框；其余本地文件型 Mod 可作为独立批次再次操作。"
            ),
        }, ensure_ascii=False)

    def _record_strict_selection_result(self, name: str, result: str) -> None:
        if not self._selection_strict_nexus:
            return
        try:
            parsed = json.loads(result)
        except (ValueError, TypeError, json.JSONDecodeError):
            parsed = {}
        if name == "batch_download":
            self._selection_batch_download_attempted = True
            self._selection_batch_download_result = result
            success = [
                dict(item) for item in (parsed.get("success") or [])
                if isinstance(item, dict)
            ]
            skipped = [
                dict(item) for item in (parsed.get("skipped_installed") or [])
                if isinstance(item, dict)
            ]
            expected = {
                self._selection_row_identity(row)
                for row in self._selection_confirm_rows
            }
            completed: set[tuple[str, str, str]] = set()
            for item in success:
                identity = self._selection_row_identity(item)
                if identity in expected:
                    completed.add(identity)
                    continue
                # Some download providers echo the stable Nexus file_id but
                # not the UI-only variant_id. Preserve the selected variant.
                for row in self._selection_confirm_rows:
                    if (
                        str(row.get("mod_id") or "")
                        == str(item.get("mod_id") or "")
                        and (
                            not row.get("file_id")
                            or str(row.get("file_id"))
                            == str(item.get("file_id") or "")
                        )
                    ):
                        item.update({
                            "variant_id": row.get("variant_id"),
                            "variant_name": row.get("variant_name"),
                            "file_name": row.get("file_name"),
                            "target_slot": row.get("target_slot"),
                        })
                        completed.add(self._selection_row_identity(row))
                        break
            for item in skipped:
                mid = str(item.get("mod_id") or "")
                completed.update(
                    identity for identity in expected if identity[0] == mid
                )
            self._selection_batch_download_success = success
            self._selection_batch_download_complete = bool(
                parsed.get("status") == "completed"
                and not parsed.get("failed")
                and not parsed.get("pending_verification")
                and not parsed.get("blocked_dependencies")
                and completed == expected
            )
        elif name == "mod_install_batch":
            self._selection_batch_install_result = result
            self._install_completed_this_turn = bool(
                parsed.get("status") == "completed"
                and parsed.get("all_selected_installed") is True
                and int(parsed.get("failed") or 0) == 0
            )

    def _exec(self, name: str, args: dict) -> str:
        # Shared by non-stream, stream and debug replay. A question is never
        # a continuation grant, regardless of old selected rows or dev mode.
        current_message = str(getattr(self, "_current_user_msg", "") or "")
        if current_message and name in MUTATING_TOOLS | {"mod_source_align"}:
            decision = route_message(current_message)
            inquiry = decision.intent in {AgentMode.STATUS_CHECK, AgentMode.DIAGNOSE} or (
                decision.intent == AgentMode.CHAT_EXPLAIN and (
                    decision.confidence >= .9 or re.fullmatch(r"[?？!！.。\s]+", current_message)
                )
            )
            unconfirmed_update = name == "mod_update" and self._selection_action != "confirm"
            if inquiry or unconfirmed_update or negates_changes(current_message):
                reason = "本轮提问不构成执行授权；请先核验计划，再通过确认操作执行。"
                if self._core_runtime:
                    self._core_runtime.tool_blocked(name, reason)
                return json.dumps({"error": "execution_confirmation_required",
                                   "status": "blocked", "message": reason}, ensure_ascii=False)
        if self._core_runtime and self._core_runtime.enforcing:
            if not self._core_runtime.tool_allowed(name):
                reason = (
                    f"工具 {name} 不属于当前 {self._core_spec.intent.value if self._core_spec else 'UNKNOWN'} "
                    "任务的权限范围。"
                )
                self._core_runtime.tool_blocked(name, reason)
                return json.dumps({
                    "error": "agent_core_scope_blocked",
                    "tool": name,
                    "intent": self._core_spec.intent.value if self._core_spec else "",
                    "message": reason,
                }, ensure_ascii=False)
        if self._is_cancelled():
            return self._cancelled_tool_result(name)
        args = self._canonicalize_selected_nexus_args(name, args)
        # A discovery request is read-only, but it still consumes network time
        # and model context.  Treat an identical query as one observation and
        # place an explicit, small ceiling on exploratory aliases.  Without
        # this guard an LLM can keep enumerating fictional character names
        # until the unrelated global MAX_ROUNDS guard aborts the whole turn.
        if name in SEARCH_DISCOVERY_TOOLS:
            raw_query = str(args.get("query") or "")
            normalized_query = re.sub(r"\s+", " ", raw_query).strip()
            if normalized_query:
                args = {**args, "query": normalized_query}
            search_signature = name + ":" + normalized_query.casefold()
            if search_signature in self._turn_search_cache:
                try:
                    prior = json.loads(self._turn_search_cache[search_signature])
                except (TypeError, ValueError, json.JSONDecodeError):
                    prior = {"result": self._turn_search_cache[search_signature]}
                prior["reused_result"] = True
                prior["searched"] = False
                prior["message"] = (
                    "本轮已执行过相同的来源搜索，已复用结果；请基于已有候选整理回复，"
                    "不要再次搜索相同关键词。"
                )
                return json.dumps(prior, ensure_ascii=False)
            query_identity = normalized_query.casefold()
            if name == 'mod_recommend':
                from .recommendation_fit import enough_alternatives
                for cached_name, cached_value in self._turn_search_cache.items():
                    if not cached_name.startswith('mod_recommend:'):
                        continue
                    try:
                        cached = json.loads(cached_value)
                    except (ValueError, TypeError):
                        continue
                    if isinstance(cached, dict) and enough_alternatives(cached, getattr(self, '_recommendation_goal', '') or self._current_user_msg):
                        return json.dumps({**cached, 'reused_result': True, 'searched': False,
                            'message': '已有至少两个详情已核验且符合原始信息展示需求的替代方案；停止扩展查询，比较并汇总现有证据。'}, ensure_ascii=False)
            if (
                self._core_runtime is not None
                and self._core_runtime.enforcing
                and query_identity
                and query_identity not in self._turn_unique_search_queries
                and len(self._turn_unique_search_queries) >= MAX_SEARCH_QUERY_ALIASES
            ):
                self._core_runtime.tool_blocked(name, '搜索查询次数已达本轮上限，已保留现有结果。')
                return json.dumps({
                    "status": "search_query_alias_budget_exhausted",
                    "searched": False,
                    "message": (
                        "搜索查询次数已达本轮上限，已停止新增查询并保留现有结果。"
                    ),
                }, ensure_ascii=False)
            source_calls = self._turn_search_calls_by_tool.get(name, 0)
            if source_calls >= MAX_SEARCH_CALLS_PER_SOURCE:
                return json.dumps({
                    "status": "search_source_budget_exhausted",
                    "searched": False,
                    "source": name,
                    "message": (
                        f"本轮 {name} 已完成 {source_calls} 次不同关键词搜索，"
                        "请停止扩展别名，直接汇总已有结果；若仍不够，只能向用户说明未找到。"
                    ),
                }, ensure_ascii=False)
            if self._turn_search_calls >= MAX_SEARCH_DISCOVERY_CALLS_PER_TURN:
                return json.dumps({
                    "status": "search_turn_budget_exhausted",
                    "searched": False,
                    "message": (
                        "本轮搜索预算已用完。请立即返回已搜到的候选、未找到项和下一步，"
                        "不得继续发起新的搜索。"
                    ),
                }, ensure_ascii=False)
            self._turn_search_calls += 1
            self._turn_search_calls_by_tool[name] = source_calls + 1
            if query_identity:
                self._turn_unique_search_queries.add(query_identity)
        if self._selection_action == "resolve":
            if name not in RESOLUTION_READONLY_TOOLS:
                return json.dumps({
                    "error": "resolution_scope_blocked",
                    "tool": name,
                    "message": (
                        "当前操作是“补齐当前需要”，只能核验用户已选目标、其明确依赖和本机环境；"
                        "禁止重新搜索、下载、安装、创建快照或修改任何游戏/Mod 状态。"
                    ),
                }, ensure_ascii=False)
            if name == "browser_open":
                requested_url = str(args.get("url") or "").strip()
                if requested_url not in self._selection_allowed_source_urls:
                    return json.dumps({
                        "error": "resolution_source_scope_blocked",
                        "tool": name,
                        "requested_url": requested_url,
                        "allowed_urls": sorted(self._selection_allowed_source_urls),
                        "message": "补齐阶段只能打开用户刚才选中的来源页，不能跳转到新的候选或搜索页。",
                    }, ensure_ascii=False)
        strict_result = self._strict_selection_result(name, args)
        if strict_result is not None:
            return strict_result
        if self._selection_action == "confirm" and name == "download_from_url":
            selected = [row for row in self._selection_confirm_rows
                        if row.get("url") == str(args.get("url") or "").strip()
                        and row.get("source") in {"github", "thunderstore"}]
            versions = {row["version"] for row in selected if row.get("version") not in {None, "", "unknown"}}
            if len(versions) > 1:
                return json.dumps({"error": "ambiguous_selected_version", "status": "blocked",
                    "message": "同一来源选择了不同版本，需重新核验具体文件，不能自动挑选。"}, ensure_ascii=False)
            if versions:
                args = {**args, "expected_version": next(iter(versions))}
        if self._manual_resume_turn:
            if name in SEARCH_DISCOVERY_TOOLS or name in {
                "download_from_url", "batch_download"
            }:
                return json.dumps({
                    "error": "manual_resume_scope_blocked",
                    "tool": name,
                    "message": (
                        "本轮只允许恢复刚才被 Nexus 人机验证暂停的原文件。"
                        "不得重新搜索、换源或改用通用下载器。"
                    ),
                }, ensure_ascii=False)
            if name == "mod_download" and self._manual_resume_targets:
                requested = str(args.get("mod_id") or "").strip()
                allowed = {
                    str(item.get("mod_id") or "").strip()
                    for item in self._manual_resume_targets
                }
                if len(self._manual_resume_targets) == 1:
                    target = self._manual_resume_targets[0]
                    args = {
                        **args,
                        "mod_id": target.get("mod_id"),
                        "file_id": target.get("file_id"),
                    }
                elif requested not in allowed:
                    return json.dumps({
                        "error": "manual_resume_identity_mismatch",
                        "tool": name,
                        "requested_mod_id": requested,
                        "allowed_mod_ids": sorted(allowed),
                        "message": "恢复目标与刚才暂停的 Nexus 文件不一致，已拒绝执行。",
                    }, ensure_ascii=False)
        if (
            self._diagnostic_read_only_turn
            and name in DIAGNOSTIC_SCOPE_BLOCKED_TOOLS
        ):
            return json.dumps({
                "error": "diagnostic_scope_change_blocked",
                "tool": name,
                "message": (
                    "本轮用户只要求诊断原因，未授权修改游戏或 Mod 状态。"
                    "请仅汇报本轮日志证据、已证实/未证实结论与建议；"
                    "如需禁用、安装、更新或其他变更，必须另行征得明确同意。"
                ),
            }, ensure_ascii=False)
        if self._update_intent and name in SEARCH_DISCOVERY_TOOLS:
            return json.dumps({
                "error": "update_search_scope_blocked",
                "tool": name,
                "message": (
                    "本轮目标是检查或更新本机已安装 Mod；不得转入新 Mod 推荐。"
                    "请使用 mod_update_check 的已安装清单继续，并在更新后直接汇报。"
                ),
            }, ensure_ascii=False)
        if self._install_completed_this_turn and name in SEARCH_DISCOVERY_TOOLS:
            return json.dumps({
                "error": "post_install_search_blocked",
                "tool": name,
                "message": (
                    "本轮确认的安装已经完成；禁止自动回到历史搜索任务。"
                    "请先向用户汇报本次安装结果，其他搜索必须等待新的明确请求。"
                ),
            }, ensure_ascii=False)
        if (
            name in SEARCH_DISCOVERY_TOOLS
            and self._explicit_install_target
            and self._explicit_target_found
        ):
            return json.dumps({
                "status": "exact_target_already_found",
                "searched": False,
                "target": self._explicit_install_target,
                "message": (
                    "本轮明确指定的 Mod 已找到精确来源；已停止继续扩展其他来源"
                    "和无关候选，请直接整理该目标的详情、依赖与安装计划。"
                ),
            }, ensure_ascii=False)
        if self._selection_action in {"plan", "confirm"}:
            if self._selection_action == "confirm" and name == "snapshot_create":
                return json.dumps({
                    "status": "snapshot_deferred_to_verified_install",
                    "tool": name,
                    "snapshot_created": False,
                    "message": (
                        "推荐确认阶段不得先单独创建快照。请直接调用安装工具；"
                        "它会先完成详情、加载器和依赖门禁，通过后才自动创建快照。"
                    ),
                }, ensure_ascii=False)
            if name in SEARCH_DISCOVERY_TOOLS:
                return json.dumps({
                    "error": "selection_search_scope_blocked",
                    "tool": name,
                    "message": (
                        "推荐表已经提供稳定候选 ID；计划/确认阶段不得重新搜索或换目标。"
                        "请只核验并处理结构化选择中的条目。"
                    ),
                }, ensure_ascii=False)
            if name in RECOMMENDATION_TARGET_TOOLS:
                requested_ids = set()
                if name in {"nexus_get_detail", "mod_download", "mod_install"}:
                    target = str(args.get("mod_id") or "")
                    if target:
                        requested_ids.add(target)
                elif name == "mod_install_batch":
                    requested_ids.update(str(item) for item in (args.get("mod_ids") or []))
                    requested_ids.update(
                        str(item.get("mod_id") or "")
                        for item in (args.get("items") or [])
                        if isinstance(item, dict) and item.get("mod_id") not in (None, "")
                    )
                elif name == "batch_download":
                    requested_ids.update(
                        str(item.get("mod_id") or "")
                        for item in (args.get("mods") or [])
                        if isinstance(item, dict) and item.get("mod_id") not in (None, "")
                    )
                mismatched_ids = requested_ids - self._selection_allowed_nexus_ids
                requested_url = str(args.get("url") or "").strip()
                mismatched_url = bool(
                    name == "download_from_url"
                    and requested_url
                    and requested_url not in self._selection_allowed_source_urls
                )
                requested_path = str(args.get("local_path") or "").strip()
                normalized_path = (
                    os.path.normcase(os.path.abspath(requested_path))
                    if requested_path else ""
                )
                mismatched_path = bool(
                    self._selection_action == "confirm"
                    and name in {"mod_install", "mod_install_custom"}
                    and not requested_ids
                    and (
                        not normalized_path
                        or normalized_path not in self._selection_download_paths
                    )
                )
                if mismatched_ids or mismatched_url or mismatched_path:
                    return json.dumps({
                        "error": "selection_identity_mismatch",
                        "tool": name,
                        "requested_mod_ids": sorted(requested_ids),
                        "requested_url": requested_url,
                        "requested_path": requested_path,
                        "allowed_mod_ids": sorted(self._selection_allowed_nexus_ids),
                        "allowed_urls": sorted(self._selection_allowed_source_urls),
                        "message": (
                            "工具目标不在用户最终勾选的稳定来源 ID 中，已拒绝执行。"
                            "不得用相似名称或新搜索结果替换勾选项。"
                        ),
                    }, ensure_ascii=False)
        if (
            name in {"mod_install", "mod_install_custom", "mod_install_batch"}
            and (
                self._selection_action == "confirm"
                or is_short_install_confirmation(
                    self._current_user_msg, self._prior_assistant_text
                )
            )
        ):
            args = {**args, "require_verified_preflight": True}
            # The user has already approved the complete, visible plan for
            # this turn. Carry that approval into the batch executor so its
            # member archives do not each reopen a hidden confirmation gate.
            if name == "mod_install_batch":
                args["_batch_preflight_approved"] = True
        if (
            self._selection_action == "confirm"
            and name in {"mod_download", "batch_download"}
        ):
            # Re-read source requirements before caching selected targets.
            # This also protects confirmation state saved by older builds.
            args = {**args, "require_verified_preflight": True}
        if (
            name in {"mod_install", "mod_install_custom"}
            and self._explicit_install_target
        ):
            args = {**args, "require_verified_preflight": True}
        if self._status_only_turn and name in STATUS_QUESTION_BLOCKED_TOOLS:
            return json.dumps({
                "error": "status_question_side_effect_blocked",
                "tool": name,
                "message": "用户本轮是在询问当前状态，并未授权下载、安装、更新或来源绑定。请只用只读工具核实后直接回答。",
            }, ensure_ascii=False)
        if self._regenerating and name in REGENERATE_BLOCKED_TOOLS:
            return json.dumps({
                "error": "regenerate_side_effect_blocked",
                "tool": name,
                "message": "重新生成只允许重写回答；上一轮已生效的下载、安装、快照或文件操作不会重放。",
            }, ensure_ascii=False)
        if name in {"snapshot_restore", "snapshot_delete", "mod_disable"} and args.get("confirmed"):
            target = args.get("mod_id", "") if name == "mod_disable" else args.get("snapshot_id", "")
            key = f"{name}:{target}"
            if self._destructive_preview_turns.get(key, object()) == self._turn_id:
                return json.dumps({
                    "error": "confirmation_requires_new_user_turn",
                    "message": "破坏性操作预览刚在本轮生成。必须先把影响展示给用户并结束本轮，等待用户明确确认后再执行。",
                }, ensure_ascii=False)
        if args.get("confirmed") and name in {"mod_uninstall", "snapshot_restore", "snapshot_delete", "mod_disable"}:
            words = {
                "mod_uninstall": ("卸载", "删除mod", "移除mod", "remove", "uninstall"),
                "snapshot_restore": ("回滚", "恢复快照", "还原", "rollback", "restore"),
                "snapshot_delete": ("删除快照", "移除快照", "delete snapshot"),
                "mod_disable": ("禁用", "停用", "安全模式", "disable", "safe mode"),
            }[name]
            context = (self._current_user_msg + "\n" + self._prior_assistant_text).lower().replace(" ", "")
            if not any(word.replace(" ", "") in context for word in words):
                return json.dumps({
                    "error": "confirmation_intent_mismatch",
                    "tool": name,
                    "message": "当前用户确认的不是这项破坏性操作，已拒绝执行。请明确说明要卸载/回滚/删除快照后再确认。",
                }, ensure_ascii=False)
        signature = name + ":" + json.dumps(args, ensure_ascii=False, sort_keys=True)
        if (
            name in DOWNLOAD_EXECUTION_TOOLS
            and self._explicit_install_target
            and self._turn_explicit_download_failure
        ):
            return json.dumps({
                "error": "explicit_target_download_already_failed",
                "status": "download_failed_terminal",
                "tool": name,
                "message": (
                    "当前明确目标的下载已经在本轮终止；未换用其他来源、Mod ID "
                    "或下载方式继续尝试。请先向用户报告失败并等待新的重试指令。"
                ),
                "automatic_retry_allowed": False,
                "stop_further_downloads": True,
                "continue_other_items": False,
                "previous_failure": self._turn_explicit_download_failure,
            }, ensure_ascii=False)
        if (
            name in DOWNLOAD_EXECUTION_TOOLS
            and signature in self._turn_terminal_download_failures
        ):
            prior = json.loads(self._turn_terminal_download_failures[signature])
            prior["reused_result"] = True
            prior["message"] = (
                "同一下载已在本轮终止，未再次联网重试。"
                + str(prior.get("message") or "")
            )
            return json.dumps(prior, ensure_ascii=False)
        if name in {"mod_download", "download_from_url"} and signature in self._turn_result_cache:
            prior = json.loads(self._turn_result_cache[signature])
            prior["reused_result"] = True
            prior["message"] = "同一下载本轮已完成，直接复用先前结果，未再次联网下载。"
            return json.dumps(prior, ensure_ascii=False)
        t0 = time.time()
        if self._core_runtime:
            prior_step = self._core_runtime.completed_step(name, args)
            if prior_step:
                try:
                    replay = json.loads(prior_step.get("result") or "{}")
                except (TypeError, ValueError, json.JSONDecodeError):
                    replay = {"result": str(prior_step.get("result") or "")}
                if not isinstance(replay, dict):
                    replay = {"result": replay}
                replay["reused_checkpoint"] = True
                replay["message"] = replay.get("message") or "该核验步骤已完成，已从检查点恢复。"
                return json.dumps(replay, ensure_ascii=False)
            prior_effect = self._core_runtime.completed_effect(name, args)
            if prior_effect:
                try:
                    replay = json.loads(prior_effect.get("result_json") or "{}")
                except (TypeError, ValueError, json.JSONDecodeError):
                    replay = {"status": "already_completed"}
                replay["reused_effect"] = True
                replay["message"] = replay.get("message") or "该操作已完成，已复用结果，未重复执行。"
                return json.dumps(replay, ensure_ascii=False)
            self._core_runtime.tool_started(name, args)
        stop_tool = threading.Event()
        owner_cancel = getattr(self, "_cancel_check", None)
        def tool_cancelled():
            return stop_tool.is_set() or (callable(owner_cancel) and owner_cancel())
        try:
            def run_tool():
                with task_control.bind(tool_cancelled):
                    task_control.raise_if_cancelled()
                    return execute(name, args, self.cfg)

            fut = _TOOL_POOL.submit(task_control.scoped_worker(run_tool))
            timeout_seconds = None if name in SEARCH_DISCOVERY_TOOLS else TOOL_TIMEOUT_S
            if timeout_seconds is None:
                while True:
                    if self._is_cancelled():
                        stop_tool.set()
                        fut.cancel()
                        return self._cancelled_tool_result(name)
                    try:
                        result = fut.result(timeout=.2)
                        break
                    except _ToolTimeout:
                        continue
            else:
                deadline = time.monotonic() + timeout_seconds
                while True:
                    if self._is_cancelled():
                        stop_tool.set()
                        fut.cancel()
                        return self._cancelled_tool_result(name)
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise _ToolTimeout()
                    try:
                        result = fut.result(timeout=min(.2, remaining))
                        break
                    except _ToolTimeout:
                        if time.monotonic() >= deadline:
                            raise
            ok = ToolOutcome.from_legacy(result, legacy_ok=not self._is_error(result)).succeeded
        except _ToolTimeout:
            stop_tool.set()
            fut.cancel()
            timeout_seconds = TOOL_TIMEOUT_S
            result = json.dumps({
                "error": f"{name} 执行超时(>{timeout_seconds}s)，已请求停止后续工作。",
                "status": "interrupted",
                "outcome_unknown": name in MUTATING_TOOLS,
                "hint": "后台步骤可能仍在安全结束或回滚；超时不等于没有写入。请核实结果，不要盲目重复执行。",
            }, ensure_ascii=False)
            ok = False
        except Exception as e:
            result = json.dumps({"error": f"{name} 执行异常: {e}"}, ensure_ascii=False)
            ok = False
        if ok and name in SEARCH_DISCOVERY_TOOLS:
            normalized_query = re.sub(r"\s+", " ", str(args.get("query") or "")).strip()
            self._turn_search_cache[name + ":" + normalized_query.casefold()] = result
        elif name in SEARCH_DISCOVERY_TOOLS:
            # A missing per-source capability (for example an absent Nexus
            # game id/API key) is not a query problem.  Do not let the model
            # burn the whole round repeatedly asking that same unavailable
            # source with aliases.  Other configured sources remain usable.
            try:
                failure = json.loads(result)
            except (TypeError, ValueError, json.JSONDecodeError):
                failure = {}
            if isinstance(failure, dict):
                status = str(failure.get("status") or failure.get("error") or "")
                if status or failure.get("error"):
                    self._turn_search_calls_by_tool[name] = MAX_SEARCH_CALLS_PER_SOURCE
        if (
            ok
            and name in SEARCH_DISCOVERY_TOOLS
            and self._explicit_install_target
            and has_exact_target_candidate(
                name,
                result,
                self._explicit_install_target.get("name", ""),
                self._explicit_install_target.get("version", ""),
            )
        ):
            self._explicit_target_found = True
        if name in {"snapshot_restore", "snapshot_delete", "mod_disable"} and not args.get("confirmed"):
            try:
                preview = json.loads(result)
                if preview.get("requires_confirmation"):
                    target = args.get("mod_id", "") if name == "mod_disable" else args.get("snapshot_id", "")
                    key = f"{name}:{target}"
                    self._destructive_preview_turns[key] = self._turn_id
            except (ValueError, TypeError):
                pass
        if ok and name in {"mod_download", "download_from_url"}:
            try:
                parsed = json.loads(result)
                if parsed.get("local_path") or parsed.get("already_installed"):
                    self._turn_result_cache[signature] = result
                if parsed.get("local_path"):
                    self._selection_download_paths.add(
                        os.path.normcase(os.path.abspath(parsed["local_path"]))
                    )
            except (ValueError, TypeError):
                pass
        elif not ok and name in DOWNLOAD_EXECUTION_TOOLS:
            try:
                parsed = json.loads(result)
            except (ValueError, TypeError, json.JSONDecodeError):
                parsed = {}
            if (
                parsed.get("stop_further_downloads")
                or parsed.get("terminal")
                or parsed.get("status") in {
                    "download_failed_terminal",
                    "download_retry_exhausted",
                }
            ):
                self._turn_terminal_download_failures[signature] = result
                if self._explicit_install_target:
                    self._turn_explicit_download_failure = str(
                        parsed.get("message") or parsed.get("error") or "下载失败"
                    )
        if name in {"batch_download", "mod_install_batch"}:
            self._record_strict_selection_result(name, result)
        if name in {"mod_install", "mod_install_custom", "mod_install_batch", "workshop_install"}:
            self._install_attempted_this_turn = True
        if ok and name in {"mod_install", "mod_install_custom", "mod_install_batch", "workshop_install"}:
            try:
                parsed = json.loads(result)
            except (ValueError, TypeError, json.JSONDecodeError):
                parsed = {}
            batch_completed = bool(
                name == "mod_install_batch"
                and parsed.get("status") == "completed"
                and parsed.get("all_selected_installed") is True
                and int(parsed.get("failed") or 0) == 0
            )
            if (
                (name not in {"mod_install_batch", "workshop_install"} and (
                    parsed.get("files_installed")
                    or parsed.get("already_installed")
                ))
                or (
                    name == "workshop_install"
                    and parsed.get("downloaded") is True
                )
                or batch_completed
            ):
                self._install_completed_this_turn = True
        if ok and name == "mod_update":
            try:
                parsed = json.loads(result)
            except (ValueError, TypeError, json.JSONDecodeError):
                parsed = {}
            if parsed.get("updated"):
                self._update_completed_this_turn = True
        if _HAS_TRACE and getattr(self.cfg, "dev_mode", False):
            try:
                debug_trace.record_tool(name, args, result, (time.time() - t0) * 1000.0, ok,
                                        turn_id=self._turn_id)
            except Exception:
                pass
        if self._core_runtime:
            self._core_runtime.tool_finished(name, args, result, ok)
        return result

    def _is_cancelled(self) -> bool:
        check = getattr(self, "_cancel_check", None)
        if not callable(check):
            return False
        try:
            return bool(check())
        except Exception:
            return False

    @staticmethod
    def _cancelled_tool_result(name: str) -> str:
        return json.dumps({
            "error": "task_cancelled",
            "status": "cancelled",
            "tool": name,
            "message": "用户已停止本轮任务；旧轮次不会继续执行或写回结果。",
            "stop_further_downloads": True,
            "automatic_retry_allowed": False,
        }, ensure_ascii=False)

    def _emit(self, obj: dict) -> str:
        """统一出口:发 SSE 事件的同时(dev 模式下)记进 trace。"""
        if _HAS_TRACE and getattr(self.cfg, "dev_mode", False):
            try:
                kind = next((k for k in ("chunk", "tool", "tool_result", "error", "done") if k in obj), "other")
                debug_trace.record_event(kind, obj.get(kind), turn_id=self._turn_id)
            except Exception:
                pass
        return json.dumps(obj)

    def _is_error(self, result: str) -> bool:
        try:
            data = json.loads(result)
            if (
                isinstance(data, dict)
                and data.get("status") in {
                    "manual_action_required",
                    "partial_manual_action_required",
                }
            ):
                return False
            return isinstance(data, dict) and (
                "error" in data
                or bool(data.get("install_blocked"))
                or data.get("status") in {
                    "dependency_blocked",
                    "detail_verification_required",
                    "missing_dependencies",
                    "incompatible_loader",
                    "compatibility_confirmation_required",
                    "preinstall_confirmation_required",
                    "nexus_game_id_missing",
                    "nexus_api_key_missing",
                    "download_failed_terminal",
                    "download_retry_exhausted",
                    "download_incomplete",
                    "partial_failure",
                    "failed",
                    "cancelled",
                    "exact_batch_required",
                    "variant_selection_required",
                    "invalid_request",
                }
            )
        except (json.JSONDecodeError, ValueError):
            return result.strip().startswith(("错误", "Error", "[ERR]"))

    @staticmethod
    def _safe_tool_preview(result: str, result_meta: dict) -> str:
        """Keep opaque confirmation credentials out of the rendered tool log."""
        status = str((result_meta or {}).get("status") or "")
        if status == "preinstall_confirmation_required":
            return "\u5b89\u88c5\u524d\u6838\u9a8c\u5df2\u5b8c\u6210\uff0c\u7b49\u5f85\u7528\u6237\u786e\u8ba4\u3002"
        if status == "preinstall_confirmation_invalid":
            return "\u5b89\u88c5\u524d\u6838\u9a8c\u786e\u8ba4\u5df2\u5931\u6548\uff0c\u8bf7\u91cd\u65b0\u751f\u6210\u5b89\u88c5\u8ba1\u5212\u3002"
        return result[:300] if isinstance(result, str) else str(result)[:300]

    @staticmethod
    def _terminal_download_failure_message(result: str) -> str:
        """Return a final user-facing reason when this turn must stop downloading."""
        try:
            data = json.loads(result)
        except (ValueError, TypeError, json.JSONDecodeError):
            return ""
        if not isinstance(data, dict):
            return ""
        if not data.get("stop_further_downloads"):
            return ""
        if data.get("continue_other_items") is not False:
            return ""
        return str(
            data.get("message")
            or data.get("error")
            or "下载未完成，已停止本轮后续下载。"
        )

    def _pending_manual_download_targets(self) -> list[dict]:
        """Read the latest resumable Nexus gate from persisted tool history."""
        for message in reversed(self.history):
            if message.get("role") != "tool":
                continue
            try:
                data = json.loads(str(message.get("content") or ""))
            except (ValueError, TypeError, json.JSONDecodeError):
                continue
            if not isinstance(data, dict):
                continue
            status = str(data.get("status") or "")
            if (
                data.get("local_path")
                or status in {"completed", "downloaded", "installed"}
                or (
                    isinstance(data.get("success"), list)
                    and data.get("success")
                    and not data.get("pending_verification")
                )
            ):
                # A newer successful download closes any older page gate.
                return []
            if status == "manual_action_required":
                target = {
                    "mod_id": data.get("mod_id"),
                    "file_id": data.get("file_id"),
                    "nexus_slug": data.get("nexus_slug"),
                    "page_url": data.get("page_url"),
                }
                return [target] if target["mod_id"] not in (None, "") else []
            if status == "partial_manual_action_required":
                return [
                    {
                        "mod_id": item.get("mod_id"),
                        "file_id": item.get("file_id"),
                        "nexus_slug": item.get("nexus_slug"),
                        "page_url": item.get("page_url"),
                    }
                    for item in (
                        data.get("pending_verification")
                        or data.get("manual_action")
                        or []
                    )
                    if isinstance(item, dict)
                    and item.get("mod_id") not in (None, "")
                ]
        return []

    @staticmethod
    def _is_manual_resume_request(user_msg: str) -> bool:
        normalized = re.sub(r"[\s，,。.!！?？]+", "", str(user_msg or "")).casefold()
        if normalized in {"完成了", "已完成", "验证完成", "好了", "搞定了"}:
            return True
        return "我已经完成刚才要求的页面操作" in normalized

    @staticmethod
    def _manual_download_action_message(result: str) -> str:
        """Return deterministic UI copy for a resumable Nexus page gate."""
        try:
            data = json.loads(result)
        except (ValueError, TypeError, json.JSONDecodeError):
            return ""
        if not isinstance(data, dict):
            return ""
        status = str(data.get("status") or "")
        if status == "manual_action_required":
            action = str(
                data.get("user_action_required")
                or "请在已保留的 Nexus 页面完成人机验证。"
            ).strip()
            return (
                "下载已暂停，正在等待你完成 Nexus 人机验证。\n\n"
                f"{action}\n\n"
                "页面和当前下载目标都已保留，请不要关闭页面。"
                "完成后点击下方“完成了”，ModAgent 会继续同一个文件；"
                "不会重新搜索、换源或重复已经完成的下载。"
            )
        if status == "partial_manual_action_required":
            succeeded = len(data.get("success") or [])
            pending = data.get("pending_verification") or data.get("manual_action") or []
            pending = [item for item in pending if isinstance(item, dict)]
            labels = []
            for item in pending[:5]:
                label = str(
                    item.get("mod_name")
                    or item.get("name")
                    or item.get("mod_id")
                    or ""
                ).strip()
                if label:
                    labels.append(label)
            target_text = "、".join(labels)
            waiting = len(pending)
            return (
                f"本批次已完成 {succeeded} 项；还有 {waiting} 项正在等待 "
                "Nexus 人机验证"
                + (f"（{target_text}）" if target_text else "")
                + "。\n\n请在已保留的 Nexus 页面完成验证，页面无需关闭。"
                "完成后点击下方“完成了”，ModAgent 会只继续这些原目标；"
                "不会重新搜索、换源或重复已经完成的下载。"
            )
        return ""

    @staticmethod
    def _tool_summary(name: str, result: str, ok: bool) -> str:
        """给普通界面的人类可读阶段摘要；原始 JSON 只留在可展开详情。"""
        labels = {
            "snapshot_create": "安全快照已创建",
            "snapshot_restore": "快照回滚已完成",
            "batch_download": "批量下载已处理",
            "mod_download": "Mod 下载完成",
            "mod_install_batch": "批量安装已处理",
            "mod_install": "Mod 安装完成",
            "mod_install_custom": "Mod 安装完成",
            "mod_uninstall": "Mod 已卸载",
        }
        try:
            data = json.loads(result)
        except (ValueError, TypeError):
            data = {}
        if data.get("status") == "manual_action_required":
            return "等待 Nexus 人机验证；页面与当前文件已保留"
        if data.get("status") == "partial_manual_action_required":
            succeeded = len(data.get("success") or [])
            waiting = len(data.get("pending_verification") or [])
            return f"下载完成 {succeeded} 项；等待 Nexus 人机验证 {waiting} 项"
        if not ok:
            message = str(data.get("message") or data.get("error") or "操作未完成")
            if data.get("http_status"):
                message = f"{message}（HTTP {data['http_status']}）"
            return "未完成：" + (message[:120] + ("…" if len(message) > 120 else ""))
        if (
            name == "snapshot_create"
            and data.get("status") == "snapshot_deferred_to_verified_install"
        ):
            return "安全快照已顺延：通过安装前核验后由安装器自动创建"
        if name == "snapshot_restore":
            if data.get("requires_confirmation"):
                pv = data.get("preview") or {}
                external = (pv.get("external_configs") or {}).get("action_count", 0)
                return (f"回滚预览已生成：将删除 {pv.get('to_delete_count', 0)} 个、"
                        f"还原 {pv.get('to_restore_count', 0)} 个文件、处理 {external} 个用户配置；等待你的确认")
            if not data.get("complete"):
                return "回滚未完整完成，请查看待处理文件"
            return (f"回滚并复核完成：删除 {data.get('deleted', 0)} 个、"
                    f"还原 {data.get('restored', 0)} 个文件")
        if name == "mod_disable" and data.get("requires_confirmation"):
            support = data.get("decision_support") or {}
            return str(support.get("summary") or "禁用影响预览已生成；等待你的确认")
        if name == "batch_download":
            succeeded = len(data.get("success") or [])
            waiting = len(data.get("pending_verification") or [])
            failed = len(data.get("failed") or [])
            parts = [f"下载完成 {succeeded} 项"]
            if waiting:
                parts.append(f"等待人机验证 {waiting} 项")
            if failed:
                parts.append(f"失败 {failed} 项")
            return "；".join(parts)
        if name == "mod_install_batch":
            return f"安装结果：成功 {data.get('succeeded', 0)}/{data.get('total', 0)} 项"
        if name == "workshop_install":
            if data.get("status") == "steam_download_pending":
                return "Steam 已订阅，等待客户端下载完成（尚未计为已安装）"
            if data.get("already_installed"):
                return "Steam 创意工坊 Mod 已存在，未重复订阅"
            if data.get("downloaded"):
                return "Steam 创意工坊 Mod 已下载并登记"
        if name == "mod_download" and data.get("local_path"):
            import os
            return "下载完成：" + os.path.basename(data["local_path"])
        if data.get("already_installed"):
            return "已存在，已跳过重复操作"
        return labels.get(name, ("已完成 " if ok else "未完成 ") + name)

    @staticmethod
    def _deterministic_turn_summary(outcomes: list[dict]) -> str:
        """A non-LLM end marker when a tool chain cannot produce prose.

        It intentionally reports only completed tool facts.  This prevents a
        transient provider/model error from leaving the user with a spinner or
        from silently starting a new recommendation flow.
        """
        succeeded, failed = [], []
        for item in outcomes:
            label = str(item.get("summary") or item.get("name") or "操作")
            (succeeded if item.get("ok") else failed).append(label)
        lines = ["本轮处理已结束。"]
        if succeeded:
            lines.append("已完成：" + "；".join(succeeded[:4]) + "。")
        if failed:
            lines.append("未完成：" + "；".join(failed[:4]) + "。")
        lines.append("未完成项不会自动重试、改搜或安装；请按提示修正后由你明确发起下一步。")
        return "\n".join(lines)

    @staticmethod
    def _format_install_completion_report(reports: list[dict]) -> str:
        """Build an auditable result from tool facts instead of generic prose."""
        items = []
        snapshots = []
        for report in reports:
            snapshot_id = str(report.get("snapshot_id") or "").strip()
            if snapshot_id and snapshot_id not in snapshots:
                snapshots.append(snapshot_id)
            if isinstance(report.get("results"), list):
                items.extend(report["results"])
            else:
                items.append({
                    "mod_id": report.get("mod_id", ""),
                    "ok": not bool(
                        report.get("error")
                        or report.get("install_blocked")
                        or str(report.get("status") or "") in {
                            "failed",
                            "partial_failure",
                            "download_incomplete",
                            "dependency_blocked",
                            "cancelled",
                        }
                    ),
                    "name": report.get("name", ""),
                    "version": report.get("version", ""),
                    "file_id": report.get("file_id"),
                    "variant_name": report.get("variant_name", ""),
                    "files": len(report.get("files_installed") or []),
                    "files_installed": report.get("files_installed") or [],
                    "dependencies": report.get("dependencies") or [],
                    "warnings": report.get("warnings") or [],
                    "status": (
                        "already_installed"
                        if report.get("already_installed")
                        else "installed"
                    ),
                    "error": (
                        report.get("message")
                        or report.get("error")
                        or report.get("status")
                        or ""
                    ),
                })
        succeeded = sum(1 for item in items if item.get("ok"))
        lines = [
            f"安装完成：成功 {succeeded}/{len(items)} 项。",
            "",
            "| 目标 | 结果 | 版本 | 写入文件 | 依赖/警告 |",
            "|---|---|---|---:|---|",
        ]
        for item in items:
            name = str(
                item.get("name") or item.get("mod_id") or "未命名 Mod"
            ).replace("|", "\\|")
            version = str(item.get("version") or "未提供").replace("|", "\\|")
            if item.get("status") == "steam_download_pending":
                result = "已订阅，等待 Steam 客户端下载"
            elif item.get("ok"):
                result = (
                    "已存在，跳过重复安装"
                    if item.get("status") == "already_installed"
                    else "安装成功"
                )
            else:
                result = "失败：" + str(item.get("error") or "未知错误")
            dependencies = item.get("dependencies") or []
            warnings = item.get("warnings") or []
            notes = []
            if dependencies:
                notes.append(f"依赖 {len(dependencies)} 项已核验")
            else:
                notes.append("未声明额外依赖")
            if warnings:
                notes.append(f"警告 {len(warnings)} 项")
            lines.append(
                f"| {name} | {result} | {version} | "
                f"{int(item.get('files') or len(item.get('files_installed') or []))} | "
                f"{'；'.join(notes)} |"
            )
        if snapshots:
            lines.extend(["", "安全快照：" + "、".join(snapshots)])
        lines.extend([
            "",
            "本轮没有继续搜索、替换未选候选或处理历史中的其他目标。",
        ])
        return "\n".join(lines)

    @staticmethod
    def _ensure_disable_decision_support(reply: str, persisted: list[dict]) -> str:
        """Deterministic guardrail for player-impact-aware disable confirmations.

        The model may occasionally reduce a rich preview back to file counts.  The
        backend already supplied verified structured facts, so append those facts
        instead of asking the model to invent a second explanation.
        """
        support = None
        for message in reversed(persisted):
            if message.get("role") != "tool":
                continue
            try:
                data = json.loads(message.get("content") or "{}")
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            if data.get("requires_confirmation") and isinstance(data.get("decision_support"), dict):
                support = data["decision_support"]
                break
        if not support:
            return reply
        required_markers = ("暂时失去", "仍会保留", "恢复")
        if all(marker in reply for marker in required_markers):
            return reply

        impacts = []
        for item in support.get("player_impact") or []:
            impacts.append(
                f"- {item.get('name') or item.get('id')}（{item.get('role_label') or 'Mod'}）："
                f"{item.get('functionality_lost') or '对应功能将暂时不可用。'}"
            )
        retained = "、".join(
            str(item.get("name") or item.get("id"))
            for item in (support.get("retained") or [])[:12]
        ) or "未列入本次计划的其他 Mod"
        inactive = "、".join(
            str(item.get("name") or item.get("id"))
            for item in support.get("already_inactive") or []
        )
        block = [
            "\n\n### 这次诊断变更的实际影响",
            "",
            "你会暂时失去：",
            *(impacts or ["- 目标 Mod 对应的功能将暂时不可用。"]),
            "",
            f"仍会保留：{retained}。",
        ]
        if inactive:
            block.extend(["", f"无需重复处理：{inactive} 已经禁用，本次不会再次修改。"])
        block.extend([
            "",
            f"为什么这样试：{support.get('why_this_step') or ''}",
            f"建议：{support.get('recommendation') or ''}",
            f"如何恢复：{support.get('recovery') or ''}",
            f"如果故障消失：{support.get('next_if_fixed') or ''}",
            f"如果故障仍在：{support.get('next_if_not_fixed') or ''}",
            "",
            "如果你同意按这个范围做一次可逆隔离测试，请明确回复确认禁用；在你确认前不会修改文件。",
        ])
        return reply.rstrip() + "\n".join(block)

    # ── helpers ────────────────────────────────────────────────────────────

    def _assistant_toolcall_msg(self, content: str, tool_calls_data: list) -> dict:
        for index, call in enumerate(tool_calls_data):
            if not str(call.get("id") or "").strip():
                call["id"] = f"call_recovered_{index}_{int(time.time() * 1000)}"
        return {
            "role": "assistant",
            "content": content or "",
            "tool_calls": [
                {"id": t["id"], "type": "function", "function": t["function"]}
                for t in tool_calls_data
            ],
        }

    # ── streaming completion consume(缓冲,不直接 yield 文本)──────────────

    def _consume_stream(self, resp):
        collected = ""
        tool_calls_data = []
        for chunk in resp:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if delta and delta.content:
                collected += delta.content
            if delta and delta.tool_calls:
                for tc in delta.tool_calls:
                    while len(tool_calls_data) <= tc.index:
                        tool_calls_data.append({"id": "", "function": {"name": "", "arguments": ""}})
                    if tc.id:
                        tool_calls_data[tc.index]["id"] = tc.id
                    if tc.function:
                        if tc.function.name:
                            tool_calls_data[tc.index]["function"]["name"] += tc.function.name
                        if tc.function.arguments:
                            tool_calls_data[tc.index]["function"]["arguments"] += tc.function.arguments
        return collected, tool_calls_data

    def _stream(self, messages, tools):
        task_control.report_progress(stage='model', label='正在等待模型理解需求或整理结果',
                                     label_en='Waiting for the model to interpret the request or summarize results')
        self._record_prompt_metrics(messages, tools)
        return self.client.chat.completions.create(
            model=self.cfg.llm_model, messages=messages, tools=tools,
            temperature=0.3, stream=True,
        )

    def _once(self, messages, tools):
        self._record_prompt_metrics(messages, tools)
        resp = self.client.chat.completions.create(
            model=self.cfg.llm_model, messages=messages, tools=tools,
            temperature=0.3,
        )
        return resp.choices[0].message.content or ""

    def _record_prompt_metrics(self, messages, tools):
        self._last_prompt_metrics = measure_request(messages, tools)
        logging.getLogger(__name__).info("prompt_metrics %s", json.dumps(self._last_prompt_metrics))

    def _localize_recommendation_set(self, payload: dict) -> dict:
        """Translate all user-facing recommendation summaries in one small LLM call."""
        # Search/recommendation output is already generated under the selected
        # assistant language policy.  English users should keep canonical
        # English source names instead of receiving a second Chinese-only pass.
        if getattr(self.cfg, "language", "zh-CN") == "en":
            return payload
        pending = [
            {
                "selection_key": item.get("selection_key"),
                "name": item.get("name"),
                "content": item.get("content"),
                "dependencies": item.get("dependencies") or [],
                "conflict": item.get("conflict"),
            }
            for item in payload.get("items") or []
            if (
                needs_chinese_name(item.get("name"))
                or needs_chinese_localization(item.get("content"))
            )
        ]
        if not pending:
            return payload
        task_control.report_progress(stage='localize', label='正在整理中文功能说明，来源核验已返回',
                                     label_en='Preparing Chinese descriptions from returned source evidence')
        prompt = (
            "把下面每个 Mod 的 content 准确改写成简体中文功能介绍。"
            "保留专有名词，不翻译 selection_key，不虚构未提供的功能。"
            "每项必须说明它具体改变什么；原文提到适用角色、第一/第三人称、"
            "必需装备、前置、使用条件或已知限制时必须保留，不能只写泛化摘要。"
            "localized_name 必须是 name 的简短、忠实中文直译；不确定的专有名词保留英文，"
            "不得添加原标题没有的功能。原英文名会同时展示。"
            "只使用 content、dependencies 和 conflict 中已有的信息，不可根据名称猜测功能。"
            "每项通常 40-140 个中文字，只返回 JSON："
            '{"items":[{"selection_key":"原值","localized_name":"中文参考名",'
            '"content":"中文功能介绍"}]}。\n'
            + json.dumps(pending, ensure_ascii=False)
        )
        try:
            response = self.client.chat.completions.create(
                model=self.cfg.llm_model,
                messages=[
                    {"role": "system", "content": "你是面向中文玩家的 Mod 信息翻译助手。"},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.1,
            )
            translated = response.choices[0].message.content or ""
        except Exception:
            translated = []
        return apply_chinese_descriptions(payload, translated)

    # ── non-stream ─────────────────────────────────────────────────────────

    def chat(self, user_msg: str) -> str:
        self._recommendation_goal = user_msg
        self._manual_resume_targets = self._pending_manual_download_targets()
        self._manual_resume_turn = bool(
            self._manual_resume_targets
            and self._is_manual_resume_request(user_msg)
        )
        self._current_user_msg = user_msg
        self._prior_assistant_text = next((str(m.get("content") or "") for m in reversed(self.history)
                                           if m.get("role") == "assistant" and m.get("content")), "")
        self._explicit_install_target, normalized_from = (
            normalize_contextual_install_target(
                explicit_install_target(user_msg), self._prior_assistant_text,
            )
        )
        self._explicit_target_found = False
        self._turn_started_monotonic = time.monotonic()
        self._turn_search_calls = 0
        self._turn_search_calls_by_tool = {}
        self._turn_search_cache = {}
        self._turn_unique_search_queries = set()
        self._update_intent = is_update_request(user_msg)
        self._update_completed_this_turn = False
        self._status_only_turn = is_status_only_question(user_msg)
        self._diagnostic_read_only_turn = is_diagnostic_read_only_request(user_msg)
        self._turn_result_cache = {}
        self._turn_terminal_download_failures = {}
        self._turn_explicit_download_failure = ""
        system = build_prompt(self.cfg) + build_mode_prompt(
            self.cfg, route_message(user_msg).intent,
        )
        tools = build_tools_definitions(self.cfg.tier)
        if self._manual_resume_turn:
            tools = [
                tool for tool in tools
                if tool.get("function", {}).get("name")
                not in SEARCH_DISCOVERY_TOOLS | {"download_from_url", "batch_download"}
            ]
        if self._update_intent:
            tools = [
                tool for tool in tools
                if tool.get("function", {}).get("name") not in SEARCH_DISCOVERY_TOOLS
            ]
        if self._diagnostic_read_only_turn:
            tools = [
                tool for tool in tools
                if tool.get("function", {}).get("name")
                not in DIAGNOSTIC_SCOPE_BLOCKED_TOOLS
            ]
        if is_broad_recommendation_request(user_msg):
            tools = [
                tool for tool in tools
                if (
                    tool.get("function", {}).get("name")
                    not in SEARCH_DISCOVERY_TOOLS
                    or tool.get("function", {}).get("name") == "mod_recommend"
                )
            ]
        messages = [{"role": "system", "content": system}]
        self.history = sanitize_tool_history(self.history)
        messages.extend(self.history)
        if self._manual_resume_turn:
            messages.append({
                "role": "system",
                "content": (
                    "用户请求继续暂停的 Nexus 目标，实际验证状态仍以工具返回为准。"
                    "本轮只处理上下文中的暂停目标，先用 mod_download 按原 mod_id 与 file_id 继续；"
                    "禁止重新搜索、换源、调用 download_from_url 或替换文件。"
                    "底层会复用已经保留的 Nexus 页面。下载成功后才可继续原安装流程。"
                ),
            })
            messages.append(data_message("暂停目标", self._manual_resume_targets))
        if self._update_intent:
            messages.append({
                "role": "system",
                "content": (
                    "本轮是本机已安装 Mod 的检查更新/执行更新任务。"
                    "只围绕 get_installed、mod_source_align、mod_update_check 和 mod_update 闭环；"
                    "禁止搜索或推荐新的 Mod。若更新成功，立即汇报更新结果并结束本轮。"
                ),
            })
        if self._diagnostic_read_only_turn:
            messages.append({
                "role": "system",
                "content": (
                    "本轮是独立的只读故障诊断。不得复用其他问题的候选 Mod、"
                    "待确认动作或处置结论，不得禁用、启用、卸载、安装、更新或修改配置。"
                    "只使用本轮日志和本轮工具证据回答当前症状；"
                    "调用栈中的全局日志处理器不是异常归属证据。"
                ),
            })
        if self._explicit_install_target:
            messages.append({
                "role": "system",
                "content": (
                    "本轮是安装一个明确指定的 Mod，不是开放式推荐。"
                    "只能按精确名称和用户指定版本定位该目标；不得把相似、热门或"
                    "顺带搜到的其他 Mod 当作候选。找到精确来源后立即停止继续搜索。"
                    "依赖清单只能包含该目标实际声明的必要依赖；来源页里的 QQ 群、"
                    "社群、捐赠和作者宣传文字不得作为功能简介。"
                    "\n明确目标：" + json.dumps(
                        self._explicit_install_target, ensure_ascii=False
                    )
                    + (
                        f"\n实体归一：用户的“{normalized_from}”按 BepInEx 处理；"
                        "不得再用错误拼写全源盲搜。"
                        if normalized_from else ""
                    )
                ),
            })
        messages.append({"role": "user", "content": user_msg})

        # persist:本轮要写回 history 的"干净"消息(不含系统纠偏)
        persist: list[dict] = [{"role": "user", "content": user_msg}]
        empty_retries = 0
        report_retries = 0
        action_retries = 0
        reply = ""

        for _ in range(MAX_ROUNDS):
            try:
                self._record_prompt_metrics(messages, tools)
                resp = self.client.chat.completions.create(
                    model=self.cfg.llm_model, messages=messages, tools=tools, temperature=0.3,
                )
            except Exception as e:
                from .networking import friendly_network_error
                # 失败也要把用户消息落进 history,避免下一轮丢上下文
                self.history.extend(persist)
                return f"[ERR] LLM 调用失败: {friendly_network_error(e, self._network_route)}"

            msg = resp.choices[0].message

            if msg.tool_calls:
                tcd = [{"id": tc.id, "function": {"name": tc.function.name,
                        "arguments": tc.function.arguments}} for tc in msg.tool_calls]
                a_msg = self._assistant_toolcall_msg(msg.content or "", tcd)
                messages.append(a_msg); persist.append(a_msg)
                terminal_download_message = ""
                manual_download_message = ""
                toggle_batch_block = self._batch_toggle_preflight(tcd)
                for tc in msg.tool_calls:
                    try:
                        args = json.loads(tc.function.arguments)
                    except json.JSONDecodeError:
                        args = {}
                    result = (
                        toggle_batch_block
                        if toggle_batch_block
                        and tc.function.name in {"mod_disable", "mod_enable"}
                        else self._exec(tc.function.name, args)
                    )
                    t_msg = {"role": "tool", "tool_call_id": tc.id, "content": result}
                    messages.append(t_msg); persist.append(t_msg)
                    terminal_download_message = (
                        terminal_download_message
                        or self._terminal_download_failure_message(result)
                    )
                    manual_download_message = (
                        manual_download_message
                        or self._manual_download_action_message(result)
                    )
                if terminal_download_message:
                    reply = (
                        f"下载未完成：{terminal_download_message}"
                        " 本轮已结束，没有继续换源或重复下载。"
                    )
                    persist.append({"role": "assistant", "content": reply})
                    self.history.extend(persist)
                    return reply
                if manual_download_message:
                    reply = manual_download_message
                    persist.append({"role": "assistant", "content": reply})
                    self.history.extend(persist)
                    return reply
                empty_retries = 0
                continue

            reply = collapse_repeated_response(msg.content or "")
            if not reply.strip() and empty_retries < MAX_EMPTY_RETRIES:
                empty_retries += 1
                messages.append({"role": "user", "content":
                    "[系统纠偏] 你上一条回复为空。每条回复必须以一个真实的工具调用,"
                    "或一个向用户的提问结尾。请立即补上。"})
                continue

            if (
                _HAS_VALIDATOR
                and check_unfulfilled_action_promise(reply)
                and action_retries < 2
            ):
                action_retries += 1
                messages.append({"role": "assistant", "content": reply})
                messages.append(build_action_promise_correction_message())
                continue

            # P2.4 校验
            if ENABLE_REPORT_VALIDATION and _HAS_VALIDATOR and reply.strip():
                tool_results = [m for m in persist if m["role"] == "tool"]
                inputs = [m for m in persist if m["role"] == "user"]
                res = validate_report(reply, tool_results, inputs)
                if not res.ok and report_retries < 2:
                    report_retries += 1
                    messages.append({"role": "assistant", "content": reply})
                    messages.append(build_correction_message(res))
                    continue
                search_res = validate_search_report(reply, persist)
                if not search_res.ok and report_retries < 2:
                    report_retries += 1
                    messages.append({"role": "assistant", "content": reply})
                    messages.append(build_search_correction_message(search_res))
                    continue
                if not search_res.ok:
                    reply = build_search_fallback(persist)
            reply = self._ensure_disable_decision_support(reply, persist)
            persist.append({"role": "assistant", "content": reply})
            self.history.extend(persist)
            return reply

        self.history.extend(persist)
        return reply or "本轮操作已安全停止：流程没有在限定步骤内闭环。已完成的下载或文件操作会保留，未确认的破坏性操作不会执行；请点击重试继续未完成步骤。"

    # ── stream ─────────────────────────────────────────────────────────────

    def chat_stream(
        self, user_msg: str, regenerate: bool = False,
        completed_effects: list[str] | None = None,
        recommendation_selection: list[dict] | None = None,
        selection_action: str = "",
        cancel_check=None,
        task_spec: TaskSpec | None = None,
        core_runtime: AgentCoreRuntime | None = None,
        core_mode: str = "off",
    ):
        self._core_spec = task_spec
        self._core_runtime = core_runtime
        self._core_mode = str(core_mode or "off").lower()
        self._manual_resume_targets = self._pending_manual_download_targets()
        self._manual_resume_turn = bool(
            self._manual_resume_targets
            and self._is_manual_resume_request(user_msg)
        )
        self._cancel_check = cancel_check
        self._current_user_msg = user_msg
        # One read-only goal for query dispatch, evidence filtering and table
        # output. Never reuse it as an authorization or mutate the user message.
        self._recommendation_goal = user_msg
        if (task_spec is not None and self._core_mode == 'on' and not regenerate
                and task_spec.intent in {AgentMode.SEARCH_EXACT, AgentMode.RECOMMEND_BROAD}):
            self._recommendation_goal = str(task_spec.constraints.get('search_goal') or user_msg)
        self._prior_assistant_text = next((str(m.get("content") or "") for m in reversed(self.history)
                                           if m.get("role") == "assistant" and m.get("content")), "")
        self._explicit_install_target, normalized_from = (
            normalize_contextual_install_target(
                explicit_install_target(user_msg), self._prior_assistant_text,
            )
        )
        self._explicit_target_found = False
        self._turn_started_monotonic = time.monotonic()
        self._turn_search_calls = 0
        self._turn_search_calls_by_tool = {}
        self._turn_search_cache = {}
        self._turn_unique_search_queries = set()
        self._update_intent = is_update_request(user_msg)
        self._update_completed_this_turn = False
        self._diagnostic_read_only_turn = is_diagnostic_read_only_request(user_msg)
        self._selection_action = (
            selection_action
            if selection_action in {"resolve", "plan", "confirm"}
            else ""
        )
        self._selection_confirm_rows = self._normalize_selection_rows(
            recommendation_selection
        )
        self._selection_strict_nexus = bool(
            self._selection_action == "confirm"
            and self._selection_confirm_rows
            and all(
                row.get("source") == "nexus"
                for row in self._selection_confirm_rows
            )
        )
        self._selection_allowed_nexus_ids = {
            str(item.get("mod_id") or item.get("source_id") or "")
            for item in (recommendation_selection or [])
            if (
                isinstance(item, dict)
                and str(item.get("source") or "").casefold() == "nexus"
                and str(item.get("mod_id") or item.get("source_id") or "")
            )
        }
        nexus_alias_candidates: dict[str, set[str]] = {}
        for item in recommendation_selection or []:
            if (
                not isinstance(item, dict)
                or str(item.get("source") or "").casefold() != "nexus"
            ):
                continue
            canonical_id = str(
                item.get("mod_id") or item.get("source_id") or ""
            ).strip()
            if canonical_id not in self._selection_allowed_nexus_ids:
                continue
            for alias_value in (
                item.get("name"),
                item.get("localized_name"),
                item.get("selection_key"),
            ):
                alias = self._selection_alias(alias_value)
                if alias:
                    nexus_alias_candidates.setdefault(alias, set()).add(
                        canonical_id
                    )
        self._selection_nexus_alias_ids = {
            alias: next(iter(ids))
            for alias, ids in nexus_alias_candidates.items()
            if len(ids) == 1
        }
        self._selection_allowed_source_urls = {
            str(item.get("url") or "").strip()
            for item in (recommendation_selection or [])
            if isinstance(item, dict) and str(item.get("url") or "").strip()
        }
        self._selection_download_paths = set()
        self._selection_batch_download_attempted = False
        self._selection_batch_download_result = ""
        self._selection_batch_download_success = []
        self._selection_batch_download_complete = False
        self._selection_batch_install_result = ""
        self._install_completed_this_turn = False
        self._install_attempted_this_turn = False
        self._status_only_turn = is_status_only_question(user_msg)
        self._turn_result_cache = {}
        self._turn_terminal_download_failures = {}
        self._turn_explicit_download_failure = ""
        v2_active = task_spec is not None and self._core_mode == "on"
        system = (
            build_v2_prompt(self.cfg, task_spec)
            if v2_active
            else build_prompt(self.cfg) + build_mode_prompt(
                self.cfg, route_message(
                    user_msg, selection_action=selection_action,
                    regenerate=regenerate, has_selection=bool(recommendation_selection),
                ).intent,
            )
        )
        tools = build_tools_definitions(self.cfg.tier)
        if v2_active:
            tools = filter_tool_definitions(tools, task_spec)
        if self._selection_action == "resolve":
            tools = [
                tool for tool in tools
                if tool.get("function", {}).get("name") in RESOLUTION_READONLY_TOOLS
            ]
        if self._manual_resume_turn:
            tools = [
                tool for tool in tools
                if tool.get("function", {}).get("name")
                not in SEARCH_DISCOVERY_TOOLS | {"download_from_url", "batch_download"}
            ]
        if self._update_intent:
            tools = [
                tool for tool in tools
                if tool.get("function", {}).get("name") not in SEARCH_DISCOVERY_TOOLS
            ]
        if self._diagnostic_read_only_turn:
            tools = [
                tool for tool in tools
                if tool.get("function", {}).get("name")
                not in DIAGNOSTIC_SCOPE_BLOCKED_TOOLS
            ]
        if regenerate:
            tools = [
                tool for tool in tools
                if tool.get("function", {}).get("name") not in REGENERATE_BLOCKED_TOOLS
            ]
        if self._status_only_turn:
            tools = [
                tool for tool in tools
                if tool.get("function", {}).get("name")
                not in STATUS_QUESTION_BLOCKED_TOOLS
            ]
        if is_broad_recommendation_request(user_msg):
            tools = [
                tool for tool in tools
                if (
                    tool.get("function", {}).get("name")
                    not in SEARCH_DISCOVERY_TOOLS
                    or tool.get("function", {}).get("name") == "mod_recommend"
                )
            ]
        messages = [{"role": "system", "content": system}]
        self.history = sanitize_tool_history(self.history)
        messages.extend(
            compact_history_for_v2(self.history)
            if v2_active else self.history
        )
        if self._manual_resume_turn and (
            not v2_active or (
                task_spec.intent == AgentMode.EXECUTE_PLAN
                and task_spec.authorization.get("install")
            )
        ):
            messages.append({
                "role": "system",
                "content": (
                    "用户请求继续暂停的 Nexus 目标，实际验证状态仍以工具返回为准。"
                    "本轮只处理上下文中的暂停目标，先用 mod_download 按原 mod_id 与 file_id 继续；"
                    "禁止重新搜索、换源、调用 download_from_url 或替换文件。"
                    "底层会复用已经保留的 Nexus 页面。下载成功后才可继续原安装流程。"
                ),
            })
            messages.append(data_message("暂停目标", self._manual_resume_targets))
        if self._update_intent and not v2_active:
            messages.append({
                "role": "system",
                "content": (
                    "本轮是本机已安装 Mod 的检查更新/执行更新任务。"
                    "只围绕 get_installed、mod_source_align、mod_update_check 和 mod_update 闭环；"
                    "禁止搜索或推荐新的 Mod。若更新成功，立即汇报更新结果并结束本轮。"
                ),
            })
        if self._diagnostic_read_only_turn and not v2_active:
            messages.append({
                "role": "system",
                "content": (
                    "本轮是独立的只读故障诊断。不得复用其他问题的候选 Mod、"
                    "待确认动作或处置结论，不得禁用、启用、卸载、安装、更新或修改配置。"
                    "只使用本轮日志和本轮工具证据回答当前症状；"
                    "调用栈中的全局日志处理器不是异常归属证据。"
                ),
            })
        if self._status_only_turn and not v2_active:
            recommendation_context = {}
            try:
                session = db.get_session(getattr(self, "session_id", ""))
                recommendation_context = json.loads(
                    (session or {}).get("ui_state") or "{}"
                )
            except (TypeError, ValueError, json.JSONDecodeError):
                recommendation_context = {}
            context_items = []
            if recommendation_context.get("kind") == "recommendation_set":
                for item in (recommendation_context.get("items") or [])[:12]:
                    if isinstance(item, dict):
                        context_items.append({
                            "source": item.get("source"),
                            "source_id": item.get("source_id"),
                            "name": item.get("name"),
                        })
            messages.append({
                "role": "system",
                "content": (
                    "本轮是状态核实问题，不是执行授权。只能调用只读检查工具，"
                    "禁止下载、安装、更新、卸载、创建快照或绑定来源；核实后先直接回答用户的问题。"
                    "\n当前界面推荐候选（可能为空）："
                    + json.dumps(context_items, ensure_ascii=False)
                ),
            })
        if self._explicit_install_target and not v2_active:
            messages.append({
                "role": "system",
                "content": (
                    "本轮是安装一个明确指定的 Mod，不是开放式推荐。"
                    "只能按精确名称和用户指定版本定位该目标；不得把相似、热门或"
                    "顺带搜到的其他 Mod 当作候选。找到精确来源后立即停止继续搜索。"
                    "依赖清单只能包含该目标实际声明的必要依赖；来源页里的 QQ 群、"
                    "社群、捐赠和作者宣传文字不得作为功能简介。"
                    "\n明确目标：" + json.dumps(
                        self._explicit_install_target, ensure_ascii=False
                    )
                    + (
                        f"\n实体归一：用户的“{normalized_from}”按 BepInEx 处理；"
                        "不得再用错误拼写全源盲搜。"
                        if normalized_from else ""
                    )
                ),
            })
        if regenerate:
            effects = [str(item)[:240] for item in (completed_effects or [])[:20]]
            messages.append({
                "role": "system",
                "content": (
                    "这是对上一条回答的重新生成，不是重新执行任务。"
                    "历史操作摘要不是完成证据；没有成功收据就不能称为已生效。"
                    "严禁再次下载、安装、卸载、创建/恢复/删除快照、修改文件、"
                    "操作网页或再次请求这些操作的确认。可以调用只读工具核实当前状态，"
                    "然后基于当前状态直接给出新的回答；不要声称已撤销或重做旧操作。"
                ),
            })
            messages.append(data_message("历史操作摘要（需核实）", effects))
        if (
            Tier.can(getattr(self.cfg, "tier", Tier.FREE), "structured_recommendations")
            and recommendation_selection
            and selection_action in {"resolve", "plan", "confirm"}
        ):
            selection = []
            for item in recommendation_selection[:20]:
                if not isinstance(item, dict):
                    continue
                selection.append({
                    "selection_key": str(item.get("selection_key") or "")[:80],
                    "source": str(item.get("source") or "")[:40],
                    "source_id": str(item.get("source_id") or "")[:500],
                    "mod_id": item.get("mod_id"),
                    "canonical_tool_mod_id": (
                        item.get("mod_id") or item.get("source_id")
                        if str(item.get("source") or "").casefold() == "nexus"
                        else None
                    ),
                    "name": str(item.get("name") or "")[:120],
                    "version": str(item.get("version") or "")[:48],
                    "url": str(item.get("url") or "")[:500],
                    "file_id": item.get("file_id"),
                    "file_name": str(item.get("file_name") or "")[:240],
                    "variant_id": str(
                        item.get("selected_variant_id")
                        or item.get("variant_id")
                        or ""
                    )[:120],
                    "variant_name": str(item.get("variant_name") or "")[:240],
                    "target_slot": str(item.get("target_slot") or "")[:120],
                    "dependencies": [
                        str(dep)[:120] for dep in (item.get("dependencies") or [])[:8]
                    ],
                    "required_loader": str(item.get("required_loader") or "")[:40],
                    "loader_compatible": item.get("loader_compatible"),
                    "detail_verified": bool(item.get("detail_verified")),
                    "installable": bool(item.get("installable")),
                    "conflict_status": str(item.get("conflict_status") or "")[:40],
                    "conflict": str(item.get("conflict") or "")[:240],
                    "is_prerequisite": bool(item.get("is_prerequisite")),
                    "required_by": [
                        str(name)[:120] for name in (item.get("required_by") or [])[:8]
                    ],
                })
            if selection_action == "resolve":
                instruction = (
                    "用户已在智能推荐决策表中自由勾选一项或多项“我要这个”，"
                    "并点击了批量补齐按钮。本轮只补齐这些明确目标及其实际声明的必要依赖："
                    "逐项核验目标详情、可下载文件、当前游戏版本、已安装环境、冲突和依赖闭包；"
                    "必要依赖要按来源坐标精确搜索并核验，不得扩展成相似 Mod 推荐。"
                    "只形成拟安装计划，不得下载、安装、创建快照或修改游戏文件。"
                    "完成后刷新原智能推荐决策表；共享同一已满足或拟安装依赖的其他候选"
                    "可以解除相同阻塞，但不得自动勾选其他目标。"
                )
                tools = [
                    tool for tool in tools
                    if tool.get("function", {}).get("name")
                    not in REGENERATE_BLOCKED_TOOLS
                ]
            elif selection_action == "plan":
                instruction = (
                    "用户刚在推荐决策表中选择了以下候选。请以这些稳定来源 ID 为准，"
                    "核验详情、版本、依赖和已知风险。安装计划必须先列出前置/必要依赖，"
                    "说明每项被谁需要、版本条件、本机是否满足和核验状态，然后再列目标 Mod。"
                    "未核验的必要依赖必须标为阻塞项，不得静默跳过。"
                    "不得搜索或核验清单以外的相似项目，不得替换稳定来源 ID。"
                    "若加载器不兼容或依赖未满足，必须明确标为阻塞，不得询问用户是否强行安装。"
                    "给出计划后停下等待最终确认。最终确认由界面中的安装确认卡完成："
                    "不得要求用户手动回复 A/B/C、逐项编号或 y/n；不得把变体列表写成"
                    "新的文字问答。变体选择必须保留给同一张确认卡中的下拉选项。"
                    "这一轮不得下载、安装或创建快照。"
                )
                tools = [
                    tool for tool in tools
                    if tool.get("function", {}).get("name")
                    not in REGENERATE_BLOCKED_TOOLS
                ]
            else:
                instruction = (
                    "用户已在安装确认表中明确确认以下最终勾选项。"
                    "按前置依赖优先的顺序继续；只能处理清单里的条目及其经核实的必要依赖，"
                    "不得把未勾选候选重新加入。任何必要依赖仍未核验时必须停止执行并说明。"
                    "加载器不兼容、依赖缺失或详情未核验时禁止下载和安装。"
                    "清单完成后立刻汇报并结束本轮，不得返回历史搜索任务。"
                )
                tools = [
                    tool for tool in tools
                    if tool.get("function", {}).get("name") != "snapshot_create"
                ]
            tools = [
                tool for tool in tools
                if tool.get("function", {}).get("name")
                not in SEARCH_DISCOVERY_TOOLS
            ]
            if selection_action == "resolve":
                # "补齐信息/依赖" is a read-only verification pass.  A model
                # must not turn it into download/install work or a fresh broad
                # recommendation just because one source needs more detail.
                tools = [
                    tool for tool in tools
                    if tool.get("function", {}).get("name") not in {
                        "mod_download", "batch_download", "download_from_url",
                        "mod_install", "mod_install_batch", "mod_install_custom",
                        "workshop_install", "snapshot_create",
                    }
                ]
            if selection_action == "confirm":
                instruction += (
                    "\nFor Nexus tools, pass canonical_tool_mod_id exactly as "
                    "mod_id. Never put a display name, localized name, or "
                    "selection_key into a mod_id argument. Do not call "
                    "snapshot_create separately; the verified install tool "
                    "creates the snapshot after its preflight passes. For every "
                    "selected Nexus row, preserve file_id, variant_id, "
                    "variant_name, file_name and target_slot exactly. First call "
                    "batch_download once with those exact structured rows. Only "
                    "when its status is completed and every selected row appears "
                    "in success may you call mod_install_batch; pass the success "
                    "rows verbatim as mod_install_batch.items. Never reconstruct "
                    "an item from a display name, never retry a failed batch in "
                    "the same turn, and never continue after cancellation or "
                    "manual_action_required."
                )
            messages.append({
                "role": "system",
                "content": instruction,
            })
            messages.append(data_message("结构化选择", selection))
        messages.append({"role": "user", "content": user_msg})

        persist: list[dict] = [{"role": "user", "content": user_msg}]
        empty_retries = 0
        # Preserve user refinements as data, never as write authorization.
        search_goal = self._recommendation_goal
        if v2_active and search_goal != user_msg:
            messages.insert(-1, data_message("用户补充后的搜索目标", search_goal))
        search_dispatch_used = False
        state_retries = 0                  # v1 状态校验:最多逼它补调一次工具
        report_retries = 0
        action_retries = 0
        final_text = ""
        recommendation_evidence: list[tuple[str, str]] = []
        recommendation_update: dict = {}
        completed_install_names: list[str] = []
        completed_install_reports: list[dict] = []
        completed_update_names: list[str] = []
        progress_ordinals: dict[str, int] = {}
        turn_outcomes: list[dict] = []

        # 开发者模式:开一个轮次(记录 pre_history 供重放)
        dev = _HAS_TRACE and getattr(self.cfg, "dev_mode", False)
        self._turn_id = None
        self._regenerating = bool(regenerate)
        if dev:
            try:
                self._turn_id = debug_trace.start_turn(getattr(self, "session_id", ""), user_msg,
                                                       pre_history=list(self.history))
            except Exception:
                dev = False
                self._turn_id = None

        try:
            for _ in range(MAX_ROUNDS):
                if self._is_cancelled():
                    break
                try:
                    resp = self._stream(messages, tools)
                    collected, tool_calls_data = self._consume_stream(resp)
                except Exception as e:
                    from .networking import friendly_network_error, model_failure_summary
                    final_text, retryable = model_failure_summary(e, self._network_route)
                    yield self._emit({"error": friendly_network_error(e, self._network_route)})
                    yield self._emit({"chunk": final_text})
                    persist.append({"role": "assistant", "content": final_text})
                    if self._core_runtime:
                        self._core_runtime.interrupt(final_text, retryable=retryable)
                    break

                if self._is_cancelled():
                    break

                if (v2_active and task_spec.intent in {AgentMode.SEARCH_EXACT, AgentMode.RECOMMEND_BROAD}
                        and not tool_calls_data and not search_dispatch_used
                        and not any(name in SEARCH_DISCOVERY_TOOLS for name, _result in recommendation_evidence)
                        and (getattr(self.cfg, "game_name", "") or getattr(self.cfg, "game_slug", ""))
                        and any(t.get("function", {}).get("name") == "mod_recommend" for t in tools)):
                    # A prose-only LLM reply cannot silently turn an explicit
                    # search into another preference questionnaire. Dispatch
                    # the already authorized read-only query once, through the
                    # same permission/receipt path as every other tool call.
                    search_dispatch_used = True
                    collected = ""
                    tool_calls_data = [{"id": "search-dispatch-" + task_spec.turn_id,
                        "type": "function", "function": {"name": "mod_recommend",
                        "arguments": json.dumps({"query": search_goal}, ensure_ascii=False)}}]

                # ── 有工具调用:预告文本不外发(P2.3),执行工具并回报真实状态 ──
                if tool_calls_data:
                    a_msg = self._assistant_toolcall_msg(collected, tool_calls_data)
                    messages.append(a_msg); persist.append(a_msg)

                    if not BUFFER_PRETOOL_TEXT and collected.strip():
                        yield self._emit({"chunk": collected})

                    yield self._emit({"tool": [t["function"]["name"] for t in tool_calls_data]})
                    terminal_download_message = ""
                    manual_download_message = ""
                    toggle_batch_block = self._batch_toggle_preflight(
                        tool_calls_data
                    )
                    for t in tool_calls_data:
                        if self._is_cancelled():
                            break
                        tool_name = str(t["function"].get("name") or "")
                        progress = user_visible_progress(
                            tool_name,
                            progress_ordinals.get(tool_name, 0) + 1,
                        )
                        progress_ordinals[tool_name] = progress_ordinals.get(tool_name, 0) + 1
                        # This is operational state from our executor, not an
                        # LLM draft or chain-of-thought.  It must remain visible
                        # even when the low-level tool itself is quiet.
                        yield self._emit({"progress": {
                            **progress,
                            "tool": tool_name,
                            "current": progress_ordinals[tool_name],
                        }})
                        try:
                            args = json.loads(t["function"]["arguments"])
                        except json.JSONDecodeError:
                            args = {}
                        result = (
                            toggle_batch_block
                            if toggle_batch_block
                            and t["function"]["name"] in {
                                "mod_disable", "mod_enable"
                            }
                            else self._exec(t["function"]["name"], args)
                        )
                        if self._is_cancelled():
                            break
                        if t["function"]["name"] in {
                            "mod_install", "mod_install_custom", "mod_install_batch",
                            "workshop_install",
                        }:
                            try:
                                install_result = json.loads(result)
                            except (TypeError, ValueError, json.JSONDecodeError):
                                install_result = {}
                            if (
                                install_result.get("files_installed")
                                or install_result.get("already_installed")
                                or isinstance(install_result.get("results"), list)
                                or install_result.get("error")
                                or install_result.get("install_blocked")
                                or t["function"]["name"] == "workshop_install"
                            ):
                                completed_install_reports.append(install_result)
                                installed_name = str(
                                    install_result.get("name")
                                    or args.get("mod_id")
                                    or "已选 Mod"
                                )
                                batch_names = [
                                    str(item.get("name") or item.get("mod_id") or "").strip()
                                    for item in (install_result.get("results") or [])
                                    if isinstance(item, dict) and item.get("ok")
                                ]
                                for name in batch_names or [installed_name]:
                                    if name and name not in completed_install_names:
                                        completed_install_names.append(name)
                        if (
                            Tier.can(
                                getattr(self.cfg, "tier", Tier.FREE),
                                "structured_recommendations",
                            )
                            and selection_action == ""
                            and not self._update_intent
                        ):
                            recommendation_evidence.append(
                                (t["function"]["name"], result)
                            )
                        if (
                            t["function"]["name"] == "nexus_get_detail"
                            and not self._is_error(result)
                            and selection_action != "confirm"
                        ):
                            try:
                                current_session = db.get_session(
                                    getattr(self, "session_id", "")
                                )
                                current_state = json.loads(
                                    (current_session or {}).get("ui_state") or "{}"
                                )
                            except (
                                TypeError, ValueError, json.JSONDecodeError
                            ):
                                current_state = {}
                            promoted = promote_verified_recommendation(
                                current_state,
                                "nexus",
                                result,
                                mod_loader=self._current_mod_loader(),
                                game_slug=str(
                                    getattr(self.cfg, "game_slug", "") or ""
                                ),
                            )
                            if promoted.get("items"):
                                recommendation_update = (
                                    self._localize_recommendation_set(promoted)
                                )
                                db.update_session_ui_state(
                                    getattr(self, "session_id", ""),
                                    recommendation_update,
                                )
                        t_msg = {"role": "tool", "tool_call_id": t["id"], "content": result}
                        messages.append(t_msg); persist.append(t_msg)
                        terminal_download_message = (
                            terminal_download_message
                            or self._terminal_download_failure_message(result)
                        )
                        manual_download_message = (
                            manual_download_message
                            or self._manual_download_action_message(result)
                        )
                        try:
                            result_meta = json.loads(result)
                        except (ValueError, TypeError, json.JSONDecodeError):
                            result_meta = {}
                        receipt_outcome = ToolOutcome.from_legacy(result, legacy_ok=not self._is_error(result))
                        tool_ok = receipt_outcome.succeeded
                        tool_summary = self._tool_summary(
                            t["function"]["name"], result, tool_ok
                        )
                        turn_outcomes.append({
                            "name": t["function"]["name"],
                            "ok": tool_ok,
                            "summary": tool_summary,
                            "status": str(result_meta.get("status") or ""),
                        })
                        yield self._emit({"tool_result": {
                            "name": t["function"]["name"], "ok": tool_ok,
                            "outcome_status": receipt_outcome.status.value,
                            "execution_complete": bool(self._install_completed_this_turn),
                            "summary": tool_summary,
                            "preview": self._safe_tool_preview(result, result_meta),
                            "status": str(result_meta.get("status") or ""),
                            "install_blocked": bool(result_meta.get("install_blocked")),
                            "all_selected_installed": result_meta.get(
                                "all_selected_installed"
                            ),
                        }})
                        if (
                            selection_action == "plan"
                            and t["function"]["name"] == "nexus_get_detail"
                            and self._is_error(result)
                        ):
                            yield self._emit({
                                "plan_blocked": True,
                                "plan_block_reason": (
                                    "所选候选的来源详情未能完成核验，"
                                    "不会生成可执行确认表。"
                                ),
                            })
                        if t["function"]["name"] == "mod_update_check":
                            try:
                                update_report = json.loads(result)
                            except (TypeError, ValueError, json.JSONDecodeError):
                                update_report = {}
                            if (
                                isinstance(update_report, dict)
                                and isinstance(update_report.get("items"), list)
                            ):
                                yield self._emit({"update_report": update_report})
                        if (
                            t["function"]["name"] == "mod_update"
                            and not self._is_error(result)
                        ):
                            try:
                                updated = json.loads(result)
                            except (TypeError, ValueError, json.JSONDecodeError):
                                updated = {}
                            updated_name = str(updated.get("updated") or "").strip()
                            if updated_name and updated_name not in completed_update_names:
                                completed_update_names.append(updated_name)
                    if terminal_download_message:
                        final_text = (
                            f"下载未完成：{terminal_download_message}"
                            " 本轮已结束，没有继续换源或重复下载。"
                        )
                        yield self._emit({"chunk": final_text})
                        persist.append({
                            "role": "assistant", "content": final_text
                        })
                        break
                    if manual_download_message:
                        final_text = manual_download_message
                        yield self._emit({"chunk": final_text})
                        persist.append({
                            "role": "assistant", "content": final_text
                        })
                        break
                    if recommendation_update.get("items"):
                        promoted = recommendation_update.get("promotion") or {}
                        if promoted.get("installable"):
                            guidance = (
                                "详情核验已完成：原来的“保留目标”已在原决策表中"
                                "升级为可勾选项，并继承为已选择。"
                                "请让用户在同一张表中统一生成安装计划；"
                                "不要另写 y/n 安装确认。"
                            )
                        else:
                            guidance = (
                                "详情核验已完成，但该目标仍被依赖、加载器或来源风险阻塞。"
                                "原决策表已原地更新阻塞原因；不得询问用户强行安装。"
                            )
                        messages.append({"role": "system", "content": guidance})
                        if self._core_runtime and selection_action == "plan":
                            self._core_runtime.record_plan_revision(recommendation_update)
                        yield self._emit({
                            "recommendations_update": recommendation_update,
                            "plan_blocked": bool(
                                selection_action == "plan"
                                and not promoted.get("installable")
                            ),
                        })
                        recommendation_update = {}
                    if (
                        self._install_attempted_this_turn
                        and (
                            selection_action == "confirm"
                            or is_short_install_confirmation(
                                user_msg, self._prior_assistant_text
                            )
                        )
                    ):
                        final_text = self._format_install_completion_report(
                            completed_install_reports
                        )
                        yield self._emit({"chunk": final_text})
                        persist.append({
                            "role": "assistant", "content": final_text
                        })
                        break
                    if self._update_intent and self._update_completed_this_turn:
                        updated = "、".join(completed_update_names) or "已确认目标"
                        final_text = (
                            f"更新完成：{updated}。"
                            "本轮已结束，没有转入新 Mod 搜索或推荐。"
                        )
                        yield self._emit({"chunk": final_text})
                        persist.append({
                            "role": "assistant", "content": final_text
                        })
                        break
                    empty_retries = 0
                    continue

                # ── 无工具调用:候选最终回复 ──
                if not collected.strip():
                    if empty_retries < MAX_EMPTY_RETRIES:          # P2.2 护栏
                        empty_retries += 1
                        messages.append({"role": "user", "content":
                            "[系统纠偏] 你上一条回复为空。每条回复必须以一个真实的工具调用,"
                            "或一个向用户的提问结尾。请立即补上。"})
                        continue
                    final_text = "\n⚠️ 模型连续返回空响应，本轮已中止；没有继续搜索、下载或安装，请重试或换个说法。"
                    yield self._emit({"chunk": final_text})
                    persist.append({"role": "assistant", "content": final_text})
                    break

                final_text = collapse_repeated_response(collected)

                if (
                    _HAS_VALIDATOR
                    and check_unfulfilled_action_promise(final_text)
                    and action_retries < 2
                ):
                    action_retries += 1
                    messages.append({"role": "assistant", "content": final_text})
                    messages.append(build_action_promise_correction_message())
                    continue

                # ── v1 状态校验:该查状态却没调工具、还报了具体数字/存在性 → 拦下重跑 ──
                if ENABLE_STATE_CHECK and _HAS_VALIDATOR and state_retries < 1:
                    tool_names_this_turn = [
                        tc["function"]["name"]
                        for m in persist if m.get("role") == "assistant"
                        for tc in (m.get("tool_calls") or [])
                    ]
                    verdict = check_unsourced_state(user_msg, final_text, tool_names_this_turn)
                    if _HAS_TRACE and getattr(self.cfg, "dev_mode", False):
                        try:
                            debug_trace.record_event("state_check", verdict, turn_id=self._turn_id)
                        except Exception:
                            pass
                    if verdict["should_block"]:
                        state_retries += 1
                        yield self._emit({"chunk": "🔍 正在核实…\n"})
                        messages.append({"role": "assistant", "content": final_text})
                        messages.append(build_state_correction_message())
                        continue          # 回主循环:让它先调工具,再据实回答

                # ── P2.4 汇报校验 ──
                if ENABLE_REPORT_VALIDATION and _HAS_VALIDATOR:
                    tool_results = [m for m in persist if m["role"] == "tool"]
                    inputs = [m for m in persist if m["role"] == "user"]
                    res = validate_report(final_text, tool_results, inputs)
                    if not res.ok and report_retries < 2:
                        report_retries += 1
                        messages.append({"role": "assistant", "content": final_text})
                        messages.append(build_correction_message(res))
                        continue
                    search_res = validate_search_report(final_text, persist)
                    if not search_res.ok and report_retries < 2:
                        report_retries += 1
                        messages.append({"role": "assistant", "content": final_text})
                        messages.append(build_search_correction_message(search_res))
                        continue
                    if not search_res.ok:
                        final_text = build_search_fallback(persist)

                final_text = self._ensure_disable_decision_support(final_text, persist)
                if selection_action == "plan":
                    final_text = structured_plan_footer(final_text)
                recommendation_set = {}
                resolution_base_state = {}
                if selection_action == "resolve":
                    try:
                        current_session = db.get_session(
                            getattr(self, "session_id", "")
                        )
                        resolution_base_state = json.loads(
                            (current_session or {}).get("ui_state") or "{}"
                        )
                    except (TypeError, ValueError, json.JSONDecodeError):
                        resolution_base_state = {}
                if (
                    Tier.can(
                        getattr(self.cfg, "tier", Tier.FREE),
                        "structured_recommendations",
                    )
                    and selection_action == ""
                    and not self._update_intent
                ):
                    try:
                        refresh_local_inventory(self.cfg)
                    except Exception:
                        pass
                    recommendation_set = recommendations_from_tool_evidence(
                        recommendation_evidence,
                        limit=max(
                            2,
                            min(
                                int(getattr(self.cfg, "recommendation_limit", 10) or 10),
                                20,
                            ),
                        ),
                        game_slug=str(getattr(self.cfg, "game_slug", "") or ""),
                        game_name=str(getattr(self.cfg, "game_name", "") or ""),
                        user_goal=self._recommendation_goal,
                        mod_loader=self._current_mod_loader(),
                        target_name=(
                            ""
                            if selection_action == "resolve"
                            else self._explicit_install_target.get("name", "")
                        ),
                        target_version=(
                            ""
                            if selection_action == "resolve"
                            else self._explicit_install_target.get("version", "")
                        ),
                    )
                    if selection_action == "resolve" and recommendation_set.get("items"):
                        current_state = resolution_base_state
                        for target in recommendation_selection or []:
                            if not isinstance(target, dict):
                                continue
                            target_key = str(
                                target.get("selection_key") or ""
                            )
                            if not target_key:
                                continue
                            current_state = merge_recommendation_resolution(
                                current_state,
                                recommendation_set,
                                target_selection_key=target_key,
                                game_slug=str(
                                    getattr(self.cfg, "game_slug", "") or ""
                                ),
                            )
                        recommendation_set = current_state
                    elif (
                        selection_action == "resolve"
                        and resolution_base_state.get("kind") == "recommendation_set"
                    ):
                        # A source page may be temporarily unavailable or may
                        # not have a structured detail adapter yet.  Preserve
                        # the existing table instead of replacing it with an
                        # empty result and forcing the user into a text y/n
                        # detour.  The row remains visibly unresolved.
                        recommendation_set = resolution_base_state
                if self._core_runtime and not selection_action:
                    self._core_runtime.record_search_result(recommendation_set)
                if recommendation_set.get("items"):
                    recommendation_set = self._localize_recommendation_set(
                        recommendation_set
                    )
                    final_text = recommendation_analysis_text(
                        final_text, recommendation_set
                    )
                    # The structured decision table is the primary interaction.
                    # Emit it before the potentially long narrative so the
                    # renderer does not appear frozen while laying out both.
                    yield self._emit({"recommendations": recommendation_set})
                    if selection_action == "resolve":
                        final_text = (
                            "已按你选中的条目完成本轮只读核验，并原位刷新智能推荐清单。"
                            "请直接在清单中继续选择“安装”或“补齐依赖”；不需要回复 y/n。\n\n"
                            + final_text
                        )
                    yield self._emit({"chunk": final_text})
                else:
                    if recommendation_set.get('goal_reviewed'):
                        final_text = recommendation_analysis_text('', recommendation_set)
                    yield self._emit({"chunk": final_text})        # 缓冲后一次性发出
                persist.append({"role": "assistant", "content": final_text})
                break
            else:
                # A search-only loop must never discard the evidence it has
                # already collected.  The model may fail to emit its own
                # closing text, but the UI still needs the real candidates.
                fallback_recommendations = {}
                if (
                    Tier.can(
                        getattr(self.cfg, "tier", Tier.FREE),
                        "structured_recommendations",
                    )
                    # A resolve turn only enriches the item already selected
                    # in the existing decision table.  Falling back to a new
                    # recommendation set here used to make "补齐信息" look
                    # like a second, unrelated search/recommendation task.
                    and selection_action == ""
                    and not self._update_intent
                    and recommendation_evidence
                ):
                    try:
                        refresh_local_inventory(self.cfg)
                    except Exception:
                        pass
                    fallback_recommendations = recommendations_from_tool_evidence(
                        recommendation_evidence,
                        limit=max(
                            2,
                            min(
                                int(getattr(self.cfg, "recommendation_limit", 10) or 10),
                                20,
                            ),
                        ),
                        game_slug=str(getattr(self.cfg, "game_slug", "") or ""),
                        game_name=str(getattr(self.cfg, "game_name", "") or ""),
                        user_goal=self._recommendation_goal,
                        mod_loader=self._current_mod_loader(),
                        target_name=self._explicit_install_target.get("name", ""),
                        target_version=self._explicit_install_target.get("version", ""),
                    )
                if self._core_runtime:
                    self._core_runtime.record_search_result(fallback_recommendations)
                if fallback_recommendations.get("items"):
                    fallback_recommendations = self._localize_recommendation_set(
                        fallback_recommendations
                    )
                    sources = sorted({name for name, _result in recommendation_evidence})
                    final_text = (
                        "搜索已达到本轮上限，已停止继续扩展关键词；以下是已搜到并通过相关性筛选的候选。"
                        + (" 已检查来源：" + "、".join(sources) + "。\n\n" if sources else "\n\n")
                        + recommendation_analysis_text("", fallback_recommendations)
                    )
                    yield self._emit({"recommendations": fallback_recommendations})
                elif fallback_recommendations.get('goal_reviewed'):
                    final_text = recommendation_analysis_text('', fallback_recommendations)
                final_text = final_text or "本轮操作已安全停止：流程没有在限定步骤内闭环。已完成的下载或文件操作会保留，未确认的破坏性操作不会执行；请点击重试继续未完成步骤。"
                if self._core_runtime:
                    self._core_runtime.interrupt(final_text, retryable=False)
                yield self._emit({"chunk": final_text})
                persist.append({"role": "assistant", "content": final_text})
        except Exception as exc:
            # Do not let finally claim success before the API notices a
            # mid-turn failure. Keep completed receipts, but stop new work.
            final_text = "本轮执行中断，未继续执行后续操作。请查看已完成项和未完成项后再决定下一步。"
            if self._core_runtime:
                self._core_runtime.interrupt(final_text, retryable=False)
            yield self._emit({"error": type(exc).__name__})
            yield self._emit({"chunk": final_text})
            persist.append({"role": "assistant", "content": final_text})
        finally:
            if not self._is_cancelled() and not final_text and turn_outcomes:
                final_text = self._deterministic_turn_summary(turn_outcomes)
                yield self._emit({"chunk": final_text})
                persist.append({"role": "assistant", "content": final_text})
            # ✅ 真正的 history 保全:把本轮完整、未截断、角色正确的消息写回
            #   (含 assistant 的 tool_calls 与配对的 tool 结果;不含系统纠偏消息)
            if not self._is_cancelled():
                self.history.extend(persist)
            if self._core_runtime and not self._is_cancelled():
                self._core_runtime.finalize_from_text(
                    final_text,
                    waiting_confirmation=(self._selection_action == "plan"),
                )
            if dev:
                try:
                    debug_trace.finish_turn(history=list(self.history), final_text=final_text,
                                            turn_id=self._turn_id)
                except Exception:
                    pass
            yield self._emit({"done": True})
            self._turn_id = None
            self._regenerating = False
            self._current_user_msg = ""
            self._status_only_turn = False
            self._diagnostic_read_only_turn = False
            self._prior_assistant_text = ""
            self._turn_result_cache = {}
            self._turn_search_calls_by_tool = {}
            self._turn_search_cache = {}
            self._turn_unique_search_queries = set()
            self._turn_terminal_download_failures = {}
            self._turn_explicit_download_failure = ""
            self._selection_action = ""
            self._selection_allowed_nexus_ids = set()
            self._selection_nexus_alias_ids = {}
            self._selection_allowed_source_urls = set()
            self._selection_download_paths = set()
            self._selection_confirm_rows = []
            self._selection_strict_nexus = False
            self._selection_batch_download_attempted = False
            self._selection_batch_download_result = ""
            self._selection_batch_download_success = []
            self._selection_batch_download_complete = False
            self._selection_batch_install_result = ""
            self._install_completed_this_turn = False
            self._install_attempted_this_turn = False
            self._update_intent = False
            self._update_completed_this_turn = False
            self._manual_resume_turn = False
            self._manual_resume_targets = []
            self._cancel_check = None
            self._core_spec = None
            self._core_runtime = None
            self._core_mode = "off"
