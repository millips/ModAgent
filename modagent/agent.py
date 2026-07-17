import json
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as _ToolTimeout
from .config import Config
from .prompts import build_prompt
from .tools import build_tools_definitions, execute

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
        build_search_fallback,
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


class Agent:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.history: list[dict] = []
        self._client_obj = None
        self._turn_id = None          # 当前轮次的 trace id(显式传给 debug_trace,避免 contextvar 跨线程丢失)

    @property
    def client(self):
        if self._client_obj is None:
            from openai import OpenAI
            self._client_obj = OpenAI(
                base_url=self.cfg.llm_endpoint,
                api_key=self.cfg.llm_api_key,
                timeout=120,
            )
        return self._client_obj

    def reset(self):
        self.history = []

    def _exec(self, name: str, args: dict) -> str:
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

    # ── helpers ────────────────────────────────────────────────────────────

    def _assistant_toolcall_msg(self, content: str, tool_calls_data: list) -> dict:
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

    # ── non-stream ─────────────────────────────────────────────────────────

    def chat(self, user_msg: str) -> str:
        system = build_prompt(self.cfg)
        tools = build_tools_definitions(self.cfg.tier)
        messages = [{"role": "system", "content": system}]
        messages.extend(self.history)
        messages.append({"role": "user", "content": user_msg})

        # persist:本轮要写回 history 的"干净"消息(不含系统纠偏)
        persist: list[dict] = [{"role": "user", "content": user_msg}]
        empty_retries = 0
        reply = ""

        for _ in range(MAX_ROUNDS):
            try:
                resp = self.client.chat.completions.create(
                    model=self.cfg.llm_model, messages=messages, tools=tools, temperature=0.3,
                )
            except Exception as e:
                # 失败也要把用户消息落进 history,避免下一轮丢上下文
                self.history.extend(persist)
                return f"[ERR] LLM 调用失败: {e}"

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

            reply = msg.content or ""
            if not reply.strip() and empty_retries < MAX_EMPTY_RETRIES:
                empty_retries += 1
                messages.append({"role": "user", "content":
                    "[系统纠偏] 你上一条回复为空。每条回复必须以一个真实的工具调用,"
                    "或一个向用户的提问结尾。请立即补上。"})
                continue

            # P2.4 校验
            if ENABLE_REPORT_VALIDATION and _HAS_VALIDATOR and reply.strip():
                tool_results = [m for m in persist if m["role"] == "tool"]
                inputs = [m for m in persist if m["role"] == "user"]
                res = validate_report(reply, tool_results, inputs)
                if not res.ok:
                    messages.append({"role": "assistant", "content": reply})
                    messages.append(build_correction_message(res))
                    try:
                        reply = self._once(messages, tools) or reply
                    except Exception:
                        pass
                    if not validate_search_report(reply, persist).ok:
                        reply = build_search_fallback(persist)
                search_res = validate_search_report(reply, persist)
                if not search_res.ok:
                    messages.append({"role": "assistant", "content": reply})
                    messages.append(build_search_correction_message(search_res))
                    try:
                        reply = self._once(messages, tools) or reply
                    except Exception:
                        pass
            persist.append({"role": "assistant", "content": reply})
            self.history.extend(persist)
            return reply

        self.history.extend(persist)
        return reply or "已达到最大工具调用次数（20）。"

    # ── stream ─────────────────────────────────────────────────────────────

    def chat_stream(self, user_msg: str):
        system = build_prompt(self.cfg)
        tools = build_tools_definitions(self.cfg.tier)
        messages = [{"role": "system", "content": system}]
        messages.extend(self.history)
        messages.append({"role": "user", "content": user_msg})

        persist: list[dict] = [{"role": "user", "content": user_msg}]
        empty_retries = 0
        state_retries = 0                  # v1 状态校验:最多逼它补调一次工具
        final_text = ""

        # 开发者模式:开一个轮次(记录 pre_history 供重放)
        dev = _HAS_TRACE and getattr(self.cfg, "dev_mode", False)
        self._turn_id = None
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
                    yield self._emit({"error": str(e)})
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
                        t_msg = {"role": "tool", "tool_call_id": t["id"], "content": result}
                        messages.append(t_msg); persist.append(t_msg)
                        yield self._emit({"tool_result": {
                            "name": t["function"]["name"], "ok": not self._is_error(result),
                            "preview": (result[:300] if isinstance(result, str) else str(result)[:300]),
                        }})
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

                final_text = collected

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
                    if not res.ok:
                        messages.append({"role": "assistant", "content": final_text})
                        messages.append(build_correction_message(res))
                        try:
                            final_text = self._once(messages, tools) or final_text
                        except Exception:
                            pass
                        if not validate_search_report(final_text, persist).ok:
                            final_text = build_search_fallback(persist)
                    search_res = validate_search_report(final_text, persist)
                    if not search_res.ok:
                        messages.append({"role": "assistant", "content": final_text})
                        messages.append(build_search_correction_message(search_res))
                        try:
                            final_text = self._once(messages, tools) or final_text
                        except Exception:
                            pass

                yield self._emit({"chunk": final_text})            # 缓冲后一次性发出
                persist.append({"role": "assistant", "content": final_text})
                break
            else:
                final_text = final_text or "已达到最大工具调用次数（20）。"
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
