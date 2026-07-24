import json
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as _ToolTimeout
from .config import Config
from .config import current_edition
from .prompts import build_prompt
from .tools import build_tools_definitions, execute, refresh_local_inventory
from . import db
from .recommendation_ui import (
    apply_chinese_descriptions,
    needs_chinese_localization,
    recommendation_analysis_text,
    recommendations_from_tool_evidence,
)

# 工具看门狗:任何工具超过此秒数未返回,视为卡死,返回错误让对话继续
# (被卡住的线程无法强杀,会残留在后台,但 SSE 流不再被拖死)
TOOL_TIMEOUT_S = 300
_TOOL_POOL = ThreadPoolExecutor(max_workers=4, thread_name_prefix="tool")

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
    "mod_dependency_set", "mod_source_align",
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

    def _exec(self, name: str, args: dict) -> str:
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
            result = fut.result(timeout=TOOL_TIMEOUT_S)
            ok = not self._is_error(result)
        except _ToolTimeout:
            result = json.dumps({
                "error": f"{name} 执行超时(>{TOOL_TIMEOUT_S}s),已跳过。",
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
            except (ValueError, TypeError):
                pass
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
            return isinstance(data, dict) and "error" in data
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
            }
            for item in payload.get("items") or []
            if needs_chinese_localization(item.get("content"))
        ]
        if not pending:
            return payload
        prompt = (
            "把下面 Mod 的 content 准确改写成简体中文功能介绍。"
            "保留专有名词，不翻译 selection_key，不虚构未提供的功能。"
            "只翻译或压缩 content 中明确存在的信息，不可根据 Mod 名称猜测用途。"
            "每项 15-70 个中文字，只返回 JSON："
            '{"items":[{"selection_key":"原值","content":"中文功能介绍"}]}。\n'
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
            current_edition() == "subscription"
            and recommendation_selection
            and selection_action in {"plan", "confirm"}
        ):
            selection = []
            for item in recommendation_selection[:12]:
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
                })
            if selection_action == "plan":
                instruction = (
                    "用户刚在 Pro 推荐表中选择了以下候选。请以这些稳定来源 ID 为准，"
                    "核验详情、版本、依赖和已知风险，给出安装计划并停下等待最终确认。"
                    "这一轮不得下载、安装或创建快照。"
                )
                tools = [
                    tool for tool in tools
                    if tool.get("function", {}).get("name")
                    not in REGENERATE_BLOCKED_TOOLS
                ]
            else:
                instruction = (
                    "用户已在 Pro 安装确认表中明确确认以下最终勾选项。"
                    "按正常安装流程继续；只能处理清单里的条目及其经核实的必需依赖，"
                    "不得把未勾选候选重新加入。"
                )
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
                            current_edition() == "subscription"
                            and not selection_action
                        ):
                            recommendation_evidence.append(
                                (t["function"]["name"], result)
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
                    current_edition() == "subscription"
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
