import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as _ToolTimeout
from .config import Config, Tier
from .prompts import build_prompt
from .tools import build_tools_definitions, execute, refresh_local_inventory
from . import db
from .recommendation_ui import (
    apply_chinese_descriptions,
    needs_chinese_name,
    needs_chinese_localization,
    promote_verified_recommendation,
    recommendation_analysis_text,
    recommendations_from_tool_evidence,
)

# 工具看门狗:任何工具超过此秒数未返回,视为卡死,返回错误让对话继续
# (被卡住的线程无法强杀,会残留在后台,但 SSE 流不再被拖死)
TOOL_TIMEOUT_S = 300
TOOL_TIMEOUTS = {
    "mod_recommend": 55,
    "nexus_search": 45,
    "workshop_search": 35,
    "thunderstore_search": 35,
    "github_search": 35,
    "gamebanana_search": 35,
}
SEARCH_DISCOVERY_TOOLS = {
    "mod_recommend", "nexus_search", "workshop_search",
    "thunderstore_search", "github_search", "gamebanana_search",
}
SEARCH_TURN_BUDGET_S = 180
SEARCH_TURN_MAX_CALLS = 6
_TOOL_POOL = ThreadPoolExecutor(max_workers=4, thread_name_prefix="tool")
RECOMMENDATION_TARGET_TOOLS = {
    "nexus_get_detail", "mod_download", "mod_install",
    "batch_download", "mod_install_batch", "mod_install_custom",
    "download_from_url",
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
BUFFER_PRETOOL_TEXT = True           # P2.3:工具调用前的预告文本不直接流给用户
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


def is_short_install_confirmation(value: str, prior_reply: str = "") -> bool:
    text = str(value or "").strip().casefold().replace(" ", "")
    confirmations = {
        "y", "yes", "ok", "okay", "确认", "确认安装", "安装吧", "继续安装",
    }
    prior = str(prior_reply or "")
    return text in confirmations and any(
        marker in prior for marker in ("安装计划", "确认安装", "确认？", "确认?")
    )


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
        self._destructive_preview_turns: dict[str, str | None] = {}
        self._status_only_turn = False
        self._turn_started_monotonic = time.monotonic()
        self._turn_search_calls = 0
        self._selection_action = ""
        self._selection_allowed_nexus_ids: set[str] = set()
        self._selection_allowed_source_urls: set[str] = set()
        self._selection_download_paths: set[str] = set()
        self._install_completed_this_turn = False

    @property
    def client(self):
        if self._client_obj is None:
            from openai import OpenAI
            from .networking import build_http_client
            http_client, self._network_route = build_http_client(
                self.cfg.llm_endpoint, timeout=120
            )
            self._client_obj = OpenAI(
                base_url=self.cfg.llm_endpoint,
                api_key=self.cfg.llm_api_key,
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
        checks = (
            ("BepInEx", os.path.join(root, "BepInEx")),
            ("MelonLoader", os.path.join(root, "MelonLoader")),
            ("SMAPI", os.path.join(root, "StardewModdingAPI.exe")),
        )
        return next(
            (loader for loader, path in checks if root and os.path.exists(path)),
            "",
        )

    def _exec(self, name: str, args: dict) -> str:
        if self._install_completed_this_turn and name in SEARCH_DISCOVERY_TOOLS:
            return json.dumps({
                "error": "post_install_search_blocked",
                "tool": name,
                "message": (
                    "本轮确认的安装已经完成；禁止自动回到历史搜索任务。"
                    "请先向用户汇报本次安装结果，其他搜索必须等待新的明确请求。"
                ),
            }, ensure_ascii=False)
        if self._selection_action in {"plan", "confirm"}:
            if self._selection_action == "confirm" and name == "snapshot_create":
                return json.dumps({
                    "error": "premature_snapshot_blocked",
                    "tool": name,
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
            name in {"mod_install", "mod_install_batch"}
            and (
                self._selection_action == "confirm"
                or is_short_install_confirmation(
                    self._current_user_msg, self._prior_assistant_text
                )
            )
        ):
            args = {**args, "require_verified_preflight": True}
        if name in SEARCH_DISCOVERY_TOOLS:
            elapsed = time.monotonic() - self._turn_started_monotonic
            if (
                self._turn_search_calls >= SEARCH_TURN_MAX_CALLS
                or elapsed >= SEARCH_TURN_BUDGET_S
            ):
                return json.dumps({
                    "error": "search_budget_exhausted",
                    "message": (
                        "本轮搜索已达到时间或调用预算，已停止继续重试。"
                        "请用现有已核验结果回答，并明确说明未解决部分。"
                    ),
                    "elapsed_seconds": round(elapsed, 1),
                    "search_calls": self._turn_search_calls,
                }, ensure_ascii=False)
            self._turn_search_calls += 1
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
        if name in {"mod_download", "download_from_url"} and signature in self._turn_result_cache:
            prior = json.loads(self._turn_result_cache[signature])
            prior["reused_result"] = True
            prior["message"] = "同一下载本轮已完成，直接复用先前结果，未再次联网下载。"
            return json.dumps(prior, ensure_ascii=False)
        t0 = time.time()
        try:
            fut = _TOOL_POOL.submit(execute, name, args, self.cfg)
            timeout_seconds = TOOL_TIMEOUTS.get(name, TOOL_TIMEOUT_S)
            result = fut.result(timeout=timeout_seconds)
            ok = not self._is_error(result)
        except _ToolTimeout:
            timeout_seconds = TOOL_TIMEOUTS.get(name, TOOL_TIMEOUT_S)
            result = json.dumps({
                "error": f"{name} 执行超时(>{timeout_seconds}s),已跳过。",
                "hint": "该工具可能在遍历超大目录或等待外部资源。请换用其他方式完成当前目标,并向用户如实说明此工具超时。",
            }, ensure_ascii=False)
            ok = False
        except Exception as e:
            result = json.dumps({"error": f"{name} 执行异常: {e}"}, ensure_ascii=False)
            ok = False
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
        if ok and name in {"mod_install", "mod_install_custom", "mod_install_batch"}:
            try:
                parsed = json.loads(result)
            except (ValueError, TypeError, json.JSONDecodeError):
                parsed = {}
            if (
                parsed.get("files_installed")
                or parsed.get("already_installed")
                or (
                    name == "mod_install_batch"
                    and int(parsed.get("succeeded") or 0) > 0
                    and int(parsed.get("failed") or 0) == 0
                )
            ):
                self._install_completed_this_turn = True
        if _HAS_TRACE and getattr(self.cfg, "dev_mode", False):
            try:
                debug_trace.record_tool(name, args, result, (time.time() - t0) * 1000.0, ok,
                                        turn_id=self._turn_id)
            except Exception:
                pass
        return result

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
            return isinstance(data, dict) and (
                "error" in data
                or bool(data.get("install_blocked"))
                or data.get("status") in {
                    "dependency_blocked",
                    "detail_verification_required",
                    "missing_dependencies",
                    "incompatible_loader",
                }
            )
        except (json.JSONDecodeError, ValueError):
            return result.strip().startswith(("错误", "Error", "[ERR]"))

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
        if not ok:
            message = str(data.get("message") or data.get("error") or "操作未完成")
            return "未完成：" + (message[:72] + ("…" if len(message) > 72 else ""))
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
            return f"下载进度：成功 {len(data.get('success') or [])} 项，待处理 {len(data.get('failed') or [])} 项"
        if name == "mod_install_batch":
            return f"安装结果：成功 {data.get('succeeded', 0)}/{data.get('total', 0)} 项"
        if name == "mod_download" and data.get("local_path"):
            import os
            return "下载完成：" + os.path.basename(data["local_path"])
        if data.get("already_installed"):
            return "已存在，已跳过重复操作"
        return labels.get(name, ("已完成 " if ok else "未完成 ") + name)

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
        return self.client.chat.completions.create(
            model=self.cfg.llm_model, messages=messages, tools=tools,
            temperature=0.3, stream=True,
        )

    def _once(self, messages, tools):
        resp = self.client.chat.completions.create(
            model=self.cfg.llm_model, messages=messages, tools=tools,
            temperature=0.3,
        )
        return resp.choices[0].message.content or ""

    def _localize_recommendation_set(self, payload: dict) -> dict:
        """Translate all user-facing recommendation summaries in one small LLM call."""
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
        self._current_user_msg = user_msg
        self._turn_started_monotonic = time.monotonic()
        self._turn_search_calls = 0
        self._status_only_turn = is_status_only_question(user_msg)
        self._prior_assistant_text = next((str(m.get("content") or "") for m in reversed(self.history)
                                           if m.get("role") == "assistant" and m.get("content")), "")
        self._turn_result_cache = {}
        system = build_prompt(self.cfg)
        tools = build_tools_definitions(self.cfg.tier)
        messages = [{"role": "system", "content": system}]
        self.history = sanitize_tool_history(self.history)
        messages.extend(self.history)
        messages.append({"role": "user", "content": user_msg})

        # persist:本轮要写回 history 的"干净"消息(不含系统纠偏)
        persist: list[dict] = [{"role": "user", "content": user_msg}]
        empty_retries = 0
        report_retries = 0
        action_retries = 0
        reply = ""

        for _ in range(MAX_ROUNDS):
            try:
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
                for tc in msg.tool_calls:
                    try:
                        args = json.loads(tc.function.arguments)
                    except json.JSONDecodeError:
                        args = {}
                    result = self._exec(tc.function.name, args)
                    t_msg = {"role": "tool", "tool_call_id": tc.id, "content": result}
                    messages.append(t_msg); persist.append(t_msg)
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
    ):
        self._current_user_msg = user_msg
        self._turn_started_monotonic = time.monotonic()
        self._turn_search_calls = 0
        self._selection_action = (
            selection_action if selection_action in {"plan", "confirm"} else ""
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
        self._selection_allowed_source_urls = {
            str(item.get("url") or "").strip()
            for item in (recommendation_selection or [])
            if isinstance(item, dict) and str(item.get("url") or "").strip()
        }
        self._selection_download_paths = set()
        self._install_completed_this_turn = False
        self._status_only_turn = is_status_only_question(user_msg)
        self._prior_assistant_text = next((str(m.get("content") or "") for m in reversed(self.history)
                                           if m.get("role") == "assistant" and m.get("content")), "")
        self._turn_result_cache = {}
        system = build_prompt(self.cfg)
        tools = build_tools_definitions(self.cfg.tier)
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
        messages = [{"role": "system", "content": system}]
        self.history = sanitize_tool_history(self.history)
        messages.extend(self.history)
        if self._status_only_turn:
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
        if regenerate:
            effects = [str(item)[:240] for item in (completed_effects or [])[:20]]
            effect_text = "；".join(effects) if effects else "上一轮已经执行的操作"
            messages.append({
                "role": "system",
                "content": (
                    "这是对上一条回答的重新生成，不是重新执行任务。"
                    f"这些操作已经生效：{effect_text}。"
                    "严禁再次下载、安装、卸载、创建/恢复/删除快照、修改文件、"
                    "操作网页或再次请求这些操作的确认。可以调用只读工具核实当前状态，"
                    "然后基于当前状态直接给出新的回答；不要声称已撤销或重做旧操作。"
                ),
            })
        if (
            Tier.can(getattr(self.cfg, "tier", Tier.FREE), "structured_recommendations")
            and recommendation_selection
            and selection_action in {"plan", "confirm"}
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
                    "name": str(item.get("name") or "")[:120],
                    "version": str(item.get("version") or "")[:48],
                    "url": str(item.get("url") or "")[:500],
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
            if selection_action == "plan":
                instruction = (
                    "用户刚在推荐决策表中选择了以下候选。请以这些稳定来源 ID 为准，"
                    "核验详情、版本、依赖和已知风险。安装计划必须先列出前置/必要依赖，"
                    "说明每项被谁需要、版本条件、本机是否满足和核验状态，然后再列目标 Mod。"
                    "未核验的必要依赖必须标为阻塞项，不得静默跳过。"
                    "不得搜索或核验清单以外的相似项目，不得替换稳定来源 ID。"
                    "若加载器不兼容或依赖未满足，必须明确标为阻塞，不得询问用户是否强行安装。"
                    "给出计划后停下等待最终确认。"
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
            messages.append({
                "role": "system",
                "content": instruction + "\n结构化选择："
                + json.dumps(selection, ensure_ascii=False),
            })
        messages.append({"role": "user", "content": user_msg})

        persist: list[dict] = [{"role": "user", "content": user_msg}]
        empty_retries = 0
        state_retries = 0                  # v1 状态校验:最多逼它补调一次工具
        report_retries = 0
        action_retries = 0
        final_text = ""
        recommendation_evidence: list[tuple[str, str]] = []
        recommendation_update: dict = {}
        completed_install_names: list[str] = []

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
                try:
                    resp = self._stream(messages, tools)
                except Exception as e:
                    from .networking import friendly_network_error
                    yield self._emit({
                        "error": friendly_network_error(e, self._network_route)
                    })
                    break

                collected, tool_calls_data = self._consume_stream(resp)

                # ── 有工具调用:预告文本不外发(P2.3),执行工具并回报真实状态 ──
                if tool_calls_data:
                    a_msg = self._assistant_toolcall_msg(collected, tool_calls_data)
                    messages.append(a_msg); persist.append(a_msg)

                    if not BUFFER_PRETOOL_TEXT and collected.strip():
                        yield self._emit({"chunk": collected})

                    yield self._emit({"tool": [t["function"]["name"] for t in tool_calls_data]})
                    for t in tool_calls_data:
                        try:
                            args = json.loads(t["function"]["arguments"])
                        except json.JSONDecodeError:
                            args = {}
                        result = self._exec(t["function"]["name"], args)
                        if (
                            t["function"]["name"] in {
                                "mod_install", "mod_install_custom", "mod_install_batch"
                            }
                            and not self._is_error(result)
                        ):
                            try:
                                install_result = json.loads(result)
                            except (TypeError, ValueError, json.JSONDecodeError):
                                install_result = {}
                            if (
                                install_result.get("files_installed")
                                or install_result.get("already_installed")
                            ):
                                installed_name = str(
                                    install_result.get("name")
                                    or args.get("mod_id")
                                    or "已选 Mod"
                                )
                                if installed_name not in completed_install_names:
                                    completed_install_names.append(installed_name)
                        if (
                            Tier.can(
                                getattr(self.cfg, "tier", Tier.FREE),
                                "structured_recommendations",
                            )
                            and not selection_action
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
                        yield self._emit({"tool_result": {
                            "name": t["function"]["name"], "ok": not self._is_error(result),
                            "summary": self._tool_summary(
                                t["function"]["name"], result, not self._is_error(result)
                            ),
                            "preview": (result[:300] if isinstance(result, str) else str(result)[:300]),
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
                        yield self._emit({
                            "recommendations_update": recommendation_update,
                            "plan_blocked": bool(
                                selection_action == "plan"
                                and not promoted.get("installable")
                            ),
                        })
                        recommendation_update = {}
                    if (
                        self._install_completed_this_turn
                        and (
                            selection_action == "confirm"
                            or is_short_install_confirmation(
                                user_msg, self._prior_assistant_text
                            )
                        )
                    ):
                        installed = "、".join(completed_install_names) or "已确认目标"
                        final_text = (
                            f"已完成本次明确确认的安装：{installed}。"
                            "本轮已在这里结束，没有继续搜索、替换候选或处理历史中的其他目标。"
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
                    yield self._emit({"chunk": "\n⚠️ 模型连续返回空响应,本轮已中止,请重试或换个说法。"})
                    final_text = ""
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
                recommendation_set = {}
                if (
                    Tier.can(
                        getattr(self.cfg, "tier", Tier.FREE),
                        "structured_recommendations",
                    )
                    and not selection_action
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
                        mod_loader=self._current_mod_loader(),
                    )
                if recommendation_set.get("items"):
                    recommendation_set = self._localize_recommendation_set(
                        recommendation_set
                    )
                    final_text = recommendation_analysis_text(
                        final_text, recommendation_set
                    )
                    yield self._emit({"chunk": final_text})
                    yield self._emit({"recommendations": recommendation_set})
                else:
                    yield self._emit({"chunk": final_text})        # 缓冲后一次性发出
                persist.append({"role": "assistant", "content": final_text})
                break
            else:
                final_text = final_text or "本轮操作已安全停止：流程没有在限定步骤内闭环。已完成的下载或文件操作会保留，未确认的破坏性操作不会执行；请点击重试继续未完成步骤。"
                yield self._emit({"chunk": final_text})
                persist.append({"role": "assistant", "content": final_text})
        finally:
            # ✅ 真正的 history 保全:把本轮完整、未截断、角色正确的消息写回
            #   (含 assistant 的 tool_calls 与配对的 tool 结果;不含系统纠偏消息)
            self.history.extend(persist)
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
            self._prior_assistant_text = ""
            self._turn_result_cache = {}
            self._selection_action = ""
            self._selection_allowed_nexus_ids = set()
            self._selection_allowed_source_urls = set()
            self._selection_download_paths = set()
            self._install_completed_this_turn = False
