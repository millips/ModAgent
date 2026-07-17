"""
ModAgent 开发者模式 —— 运行时 trace 记录器
放置:modagent/debug_trace.py

作用:给"agent 说了什么" vs "后端真做了什么"提供上帝视角。
记录三类东西,按轮次(turn)组织:
  1) 工具调用:name / args / result / 耗时ms / 成败
  2) SSE 事件:发给前端的每个 chunk/tool/tool_result
  3) 轮次结束时的真实 history 结构

设计要点:
- 用 contextvars 传递"当前轮次",这样 agent 里的 _exec 无需改签名就能把工具调用归到正确轮次。
- 内存环形缓冲(最近 N 轮)供实时面板轮询;同时可选落 DB 供重放。
- 所有记录函数在"没有当前轮次"时静默 no-op,绝不因 debug 记录影响主流程。
"""
from __future__ import annotations

import contextvars
import copy
import time
import threading

# 当前轮次的 id(agent 在每轮开始时 set)
_current_turn: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "modagent_current_turn", default=None
)

_LOCK = threading.Lock()
_TURNS: dict[str, dict] = {}      # turn_id -> turn dict
_ORDER: list[str] = []            # 轮次顺序(旧->新)
_MAX_TURNS = 50                   # 环形缓冲上限

# 可选:落 DB 的回调(由 api/agent 注入,避免循环 import)。签名: fn(turn: dict)
_persist_cb = None


def set_persist_callback(fn):
    global _persist_cb
    _persist_cb = fn


def _now_ms() -> float:
    return time.time() * 1000.0


def start_turn(session_id: str, user_msg: str, pre_history: list | None = None) -> str:
    """一轮对话开始。返回 turn_id 并设为当前上下文。"""
    turn_id = f"turn_{int(time.time()*1000)}_{threading.get_ident() % 100000}"
    turn = {
        "turn_id": turn_id,
        "session_id": session_id,
        "user_msg": user_msg,
        "started_at": time.time(),
        "finished_at": None,
        "pre_history": copy.deepcopy(pre_history) if pre_history else [],
        "tools": [],        # [{seq,name,args,result,ms,ok,ts}]
        "events": [],       # [{ts,kind,payload}]
        "history_after": None,
        "final_text": None,
    }
    with _LOCK:
        _TURNS[turn_id] = turn
        _ORDER.append(turn_id)
        while len(_ORDER) > _MAX_TURNS:
            old = _ORDER.pop(0)
            _TURNS.pop(old, None)
    _current_turn.set(turn_id)
    return turn_id


def _cur() -> dict | None:
    tid = _current_turn.get()
    if tid is None:
        return None
    return _TURNS.get(tid)


def _resolve(turn_id: str | None) -> dict | None:
    """优先用显式 turn_id 定位轮次;没传才回退到 contextvar。
    显式 turn_id 是为了在 FastAPI 流式响应(生成器可能跨线程驱动、contextvar 会丢)下
    仍能可靠归属到正确轮次。"""
    if turn_id is not None:
        return _TURNS.get(turn_id)
    return _cur()


def record_event(kind: str, payload, turn_id: str | None = None) -> None:
    """记录一个发给前端的 SSE 事件(chunk/tool/tool_result/error/done)。"""
    t = _resolve(turn_id)
    if t is None:
        return
    with _LOCK:
        t["events"].append({"ts": time.time(), "kind": kind, "payload": payload})


def record_tool(name: str, args, result, ms: float, ok: bool, turn_id: str | None = None) -> None:
    t = _resolve(turn_id)
    if t is None:
        return
    with _LOCK:
        t["tools"].append({
            "seq": len(t["tools"]),
            "name": name,
            "args": args,
            "result": result if isinstance(result, str) else str(result),
            "ms": round(ms, 1),
            "ok": ok,
            "ts": time.time(),
        })


def finish_turn(history: list | None = None, final_text: str | None = None,
                turn_id: str | None = None) -> None:
    t = _resolve(turn_id)
    if t is None:
        return
    with _LOCK:
        t["finished_at"] = time.time()
        t["history_after"] = copy.deepcopy(history) if history is not None else None
        t["final_text"] = final_text
    if _persist_cb:
        try:
            _persist_cb(dict(t))
        except Exception:
            pass
    # 只有在依赖 contextvar(未显式传 turn_id)时才清它;
    # 显式传时不动 contextvar,避免误清别的轮次。
    if turn_id is None:
        _current_turn.set(None)


# ── 读取(供 /debug 端点)────────────────────────────────────────────────

def get_last_turn() -> dict | None:
    with _LOCK:
        if not _ORDER:
            return None
        return copy.deepcopy(_TURNS[_ORDER[-1]])


def get_turn(turn_id: str) -> dict | None:
    with _LOCK:
        t = _TURNS.get(turn_id)
        return copy.deepcopy(t) if t else None


def list_turns(limit: int = 20) -> list[dict]:
    """返回轮次摘要(不含大字段),最新在前。"""
    with _LOCK:
        out = []
        for tid in reversed(_ORDER[-limit:]):
            t = _TURNS[tid]
            out.append({
                "turn_id": t["turn_id"],
                "session_id": t["session_id"],
                "user_msg": t["user_msg"][:80],
                "started_at": t["started_at"],
                "finished_at": t["finished_at"],
                "tool_count": len(t["tools"]),
                "event_count": len(t["events"]),
            })
        return out


def clear() -> None:
    with _LOCK:
        _TURNS.clear()
        _ORDER.clear()


# ── 供 /debug/exec 使用:开一个临时轮次,记录单次手动工具调用 ──────────────

def start_manual_turn(label: str = "manual_exec") -> str:
    return start_turn(session_id="__debug__", user_msg=label, pre_history=[])


if __name__ == "__main__":
    tid = start_turn("s1", "帮我装 mod")
    record_event("tool", ["snapshot_create"])
    record_tool("snapshot_create", {"trigger_mod_name": "x"},
                '{"snapshot_id": "snap_20260705_120000"}', 12.3, True)
    record_event("chunk", "快照建好了")
    finish_turn(history=[{"role": "user", "content": "帮我装 mod"}], final_text="快照建好了")
    import json
    print(json.dumps(get_last_turn(), ensure_ascii=False, indent=2))
    print("list:", json.dumps(list_turns(), ensure_ascii=False))
