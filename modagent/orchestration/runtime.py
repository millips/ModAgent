from __future__ import annotations

import hashlib
import json
import threading
from functools import wraps
from collections.abc import Callable
from typing import Any

from . import store
from .models import AgentMode, PlanRevision, TaskResult, TaskSpec, TaskState
from .policies import MUTATING_TOOLS, SEARCH_TOOLS, tool_is_allowed
from .outcomes import OutcomeStatus, ToolOutcome


def _serialized(method):
    @wraps(method)
    def wrapped(self, *args, **kwargs):
        with self._lock:
            try:
                return method(self, *args, **kwargs)
            except Exception:
                if self.enforcing:
                    raise
                # Observation must not cause the legacy action to fail.
                return None
    return wrapped


_TRANSITIONS = {
    TaskState.RECEIVED: {TaskState.CLASSIFIED, TaskState.CANCELLED},
    TaskState.CLASSIFIED: {TaskState.GATHERING, TaskState.PRESENTING, TaskState.CANCELLED},
    TaskState.GATHERING: {
        TaskState.PRESENTING, TaskState.EXECUTING, TaskState.VERIFYING,
        TaskState.PARTIAL, TaskState.BLOCKED, TaskState.FAILED, TaskState.CANCELLED,
    },
    TaskState.PRESENTING: {
        TaskState.WAITING_CONFIRMATION, TaskState.VERIFYING,
        TaskState.COMPLETED, TaskState.PARTIAL, TaskState.BLOCKED,
        TaskState.FAILED, TaskState.CANCELLED,
    },
    TaskState.WAITING_CONFIRMATION: {
        TaskState.EXECUTING, TaskState.CANCELLED, TaskState.PAUSED_BY_NEW_TURN,
    },
    TaskState.EXECUTING: {
        TaskState.VERIFYING, TaskState.PARTIAL, TaskState.BLOCKED,
        TaskState.FAILED, TaskState.CANCELLED,
    },
    TaskState.VERIFYING: {
        TaskState.COMPLETED, TaskState.PARTIAL, TaskState.BLOCKED,
        TaskState.FAILED, TaskState.CANCELLED,
    },
}


class AgentCoreRuntime:
    def __init__(
        self,
        spec: TaskSpec,
        *,
        feature_mode: str = "shadow",
        event_sink: Callable[[dict[str, Any]], None] | None = None,
    ):
        self.spec = spec
        self.feature_mode = str(feature_mode or "off").lower()
        self.event_sink = event_sink
        self.state = TaskState.RECEIVED
        self._finished = False
        self._lock = threading.RLock()
        self._tool_successes: list[dict[str, Any]] = []
        self._tool_failures: list[dict[str, Any]] = []
        self._search_result = None
        self._plan_revision: PlanRevision | None = None

    def record_search_result(self, payload: dict) -> None:
        if self.enforcing and self.spec.intent in {AgentMode.SEARCH_EXACT, AgentMode.RECOMMEND_BROAD}:
            items = payload.get('items') or []
            self._search_result = {
                'candidates': len(items),
                'matched': sum((item.get('goal_fit') or {}).get('status') == 'matched' for item in items),
                'requested': (payload.get('requirements') or {}).get('requested_count'),
            }

    @_serialized
    def record_plan_revision(self, payload: dict[str, Any]) -> None:
        """Capture the verified rows that will be shown for confirmation."""
        if not self.enforcing or self.spec.intent != AgentMode.BUILD_PLAN:
            return
        items = [dict(item) for item in (payload.get("items") or []) if isinstance(item, dict)]
        selected = {str(key) for key in (payload.get("selected_keys") or []) if str(key)}
        if not selected:
            selected = {
                str(item.get("selection_key")) for item in self.spec.targets
                if str(item.get("selection_key") or "")
            }
        targets = [
            item for item in items
            if str(item.get("selection_key") or "") in selected
            and item.get("installable") is not False
        ]
        if not targets:
            targets = [dict(item) for item in self.spec.targets]
        if targets:
            self._plan_revision = PlanRevision.create(
                task_id=self.spec.task_id, session_id=self.spec.session_id,
                game_id=self.spec.game_id, targets=targets,
            )

    @property
    def enforcing(self) -> bool:
        return self.feature_mode == "on"

    @_serialized
    def start(self) -> None:
        store.create_task(self.spec, self.state)
        self._emit("task_started", {
            "intent": self.spec.intent.value,
            "goal": self.spec.user_goal,
            "feature_mode": self.feature_mode,
        })
        self.transition(TaskState.CLASSIFIED, {
            "intent": self.spec.intent.value,
            "confidence": self.spec.confidence,
            "reason": self.spec.route_reason,
        })

    def transition(self, state: TaskState, payload: dict[str, Any] | None = None) -> None:
        if self._finished:
            return
        if state == self.state:
            return
        if self.state.terminal or state not in _TRANSITIONS.get(self.state, set()):
            raise ValueError(f"invalid task transition: {self.state.value} -> {state.value}")
        self.state = state
        store.update_state(self.spec.task_id, state)
        self._emit("phase_changed", payload or {"phase": state.value})

    def begin_gathering(self) -> None:
        if self.state == TaskState.CLASSIFIED:
            self.transition(TaskState.GATHERING, {"phase": "gathering"})

    def tool_allowed(self, tool_name: str) -> bool:
        return tool_is_allowed(self.spec, tool_name)

    @_serialized
    def tool_started(self, tool_name: str, args: dict[str, Any]) -> None:
        if self._finished:
            return
        self.begin_gathering()
        self._emit("tool_started", {
            "tool": str(tool_name),
            "write_capable": str(tool_name) in MUTATING_TOOLS,
            "target": self._target_key(args),
        })

    @_serialized
    def tool_blocked(self, tool_name: str, reason: str) -> None:
        if self._finished:
            return
        self.begin_gathering()
        item = {"tool": str(tool_name), "reason": str(reason)}
        self._tool_failures.append(item)
        self._emit("tool_finished", {**item, "ok": False, "blocked": True})

    @_serialized
    def tool_finished(self, tool_name: str, args: dict[str, Any], result: str, ok: bool) -> None:
        if self._finished:
            return
        outcome = ToolOutcome.from_legacy(result, legacy_ok=ok)
        ok = outcome.succeeded
        target_key = self._target_key(args)
        self._emit("tool_finished", {
            "tool": str(tool_name), "ok": bool(ok), "target": target_key,
            "status": outcome.status.value,
        })
        record = {"tool": str(tool_name), "target": target_key,
                  "status": outcome.status.value, "reason": outcome.reason,
                  "retryable": outcome.retryable}
        (self._tool_successes if ok else self._tool_failures).append(record)
        # Shadow observes only. Its receipts cannot suppress a real operation
        # now or become executable checkpoints after changing the feature flag.
        if not self.enforcing:
            return
        store.save_checkpoint_step(
            self.spec.task_id,
            self.step_key(tool_name, args),
            {
                "tool": str(tool_name),
                "target": target_key,
                "ok": bool(ok),
                "result": str(result or ""),
            },
        )
        if ok and str(tool_name) in MUTATING_TOOLS:
            key = self.idempotency_key(tool_name, args)
            store.record_effect(
                key, task_id=self.spec.task_id, tool_name=tool_name,
                target_key=target_key, status="completed", result=result,
            )

    def idempotency_key(self, tool_name: str, args: dict[str, Any]) -> str:
        identity = json.dumps({
            "task_id": self.spec.task_id,
            "game_id": self.spec.game_id,
            "tool": str(tool_name),
            # Include file/component and whole batch identities. This is a
            # conservative legacy key, not the future verified operation_id.
            "args": args,
        }, ensure_ascii=False, sort_keys=True, default=str)
        return hashlib.sha256(identity.encode("utf-8")).hexdigest()

    def step_key(self, tool_name: str, args: dict[str, Any]) -> str:
        identity = json.dumps({
            "tool": str(tool_name),
            "args": args,
        }, ensure_ascii=False, sort_keys=True, default=str)
        return hashlib.sha256(identity.encode("utf-8")).hexdigest()

    def completed_step(self, tool_name: str, args: dict[str, Any]) -> dict[str, Any] | None:
        if not self.enforcing or not self.spec.resumed_from or str(tool_name) in MUTATING_TOOLS:
            return None
        step = store.get_checkpoint_step(
            self.spec.task_id, self.step_key(tool_name, args),
        )
        return step if step and step.get("ok") is True else None

    def completed_effect(self, tool_name: str, args: dict[str, Any]) -> dict[str, Any] | None:
        if not self.enforcing or str(tool_name) not in MUTATING_TOOLS:
            return None
        return store.get_effect(self.idempotency_key(tool_name, args))

    @_serialized
    def finish(self, result: TaskResult, state: TaskState | None = None) -> None:
        if self._finished:
            return
        terminal = state or {
            "completed": TaskState.COMPLETED,
            "partial": TaskState.PARTIAL,
            "blocked": TaskState.BLOCKED,
            "failed": TaskState.FAILED,
            "cancelled": TaskState.CANCELLED,
        }.get(result.status, TaskState.FAILED)
        if not terminal.terminal:
            raise ValueError("finish requires a terminal state")
        self.state = terminal
        self._finished = True
        store.update_state(self.spec.task_id, terminal, result=result)
        event_type = {
            TaskState.COMPLETED: "task_completed",
            TaskState.PARTIAL: "task_partial",
            TaskState.BLOCKED: "task_failed",
            TaskState.FAILED: "task_failed",
            TaskState.CANCELLED: "task_cancelled",
            TaskState.PAUSED_BY_NEW_TURN: "task_cancelled",
        }[terminal]
        self._emit(event_type, {"result": result.to_dict(), "intent": self.spec.intent.value,
            "recovery_available": bool(self.spec.targets and self.spec.constraints.get('game_instance_id')
                                       and terminal != TaskState.COMPLETED),
            "presentation": {"show_card": not (
                self.spec.intent == AgentMode.CHAT_EXPLAIN and terminal == TaskState.COMPLETED
                and not self._tool_successes and not self._tool_failures)}})

    @_serialized
    def wait_for_confirmation(self, summary: str) -> None:
        if self._finished:
            return
        if self.enforcing and not self.spec.targets:
            self.finish(TaskResult(
                status='blocked', summary='没有可核验的所选目标，尚未生成可确认的清单。请先在推荐表中选择目标。',
                not_completed=({'reason': '缺少所选目标'},), retryable=False), TaskState.BLOCKED)
            return
        if self.state == TaskState.CLASSIFIED:
            self.transition(TaskState.PRESENTING, {"phase": "presenting"})
        elif self.state == TaskState.GATHERING:
            self.transition(TaskState.PRESENTING, {"phase": "presenting"})
        if self.state == TaskState.PRESENTING:
            self.transition(TaskState.WAITING_CONFIRMATION, {"phase": "waiting_confirmation"})
        if self.enforcing:
            if self._plan_revision is None:
                self.record_plan_revision({
                    "items": [dict(item) for item in self.spec.targets],
                    "selected_keys": [item.get("selection_key") for item in self.spec.targets],
                })
            if self._plan_revision is None:
                self.finish(TaskResult(
                    status="blocked", summary="计划缺少可冻结的服务端目标，未创建安装授权。",
                    not_completed=({"reason": "plan_revision_missing"},), retryable=False,
                ), TaskState.BLOCKED)
                return
            try:
                store.save_plan_revision(self._plan_revision)
            except ValueError as exc:
                self.finish(TaskResult(
                    status="blocked", summary="计划版本无法安全冻结，未创建安装授权。",
                    not_completed=({"reason": str(exc)},), retryable=False,
                ), TaskState.BLOCKED)
                return
        result = TaskResult(
            status="blocked",
            summary="Checks ended; review the pending selection. Nothing is authorized by this status alone." if self.spec.language == "en" else "本轮核验已结束，请查看待确认清单；此状态不代表已安装，也不构成安装授权。",
            completed=tuple(self._tool_successes),
            not_completed=({"reason": "waiting_for_confirmation"},),
            next_actions=({"action": "confirm_or_adjust_plan"},),
            retryable=True,
        )
        store.update_state(self.spec.task_id, TaskState.WAITING_CONFIRMATION, result=result)
        payload = {"result": result.to_dict()}
        if self._plan_revision is not None:
            payload["plan_revision"] = {
                "revision_id": self._plan_revision.revision_id,
                "task_id": self._plan_revision.task_id,
            }
        self._emit("decision_required", payload)
        self._finished = True

    @_serialized
    def finalize_from_text(self, summary: str, *, waiting_confirmation: bool = False) -> None:
        if self._finished:
            return
        text = self._summary(summary)
        if waiting_confirmation and text and not self._tool_failures:
            self.wait_for_confirmation(text)
            return
        if self._tool_failures and (self._tool_successes or any(
            item.get("status") == "partial" for item in self._tool_failures
        )):
            status, state = "partial", TaskState.PARTIAL
        elif self._tool_failures:
            if all(item.get("status") in {"waiting_user", "blocked", "unknown"}
                   for item in self._tool_failures):
                status, state = "blocked", TaskState.BLOCKED
            elif all(item.get("status") == "cancelled" for item in self._tool_failures):
                status, state = "cancelled", TaskState.CANCELLED
            else:
                status, state = "failed", TaskState.FAILED
        elif not text and not self._tool_successes:
            status, state = "failed", TaskState.FAILED
        elif self.spec.intent in {AgentMode.SEARCH_EXACT, AgentMode.RECOMMEND_BROAD} and not any(
            item["tool"] in SEARCH_TOOLS for item in self._tool_successes
        ):
            status, state = "blocked", TaskState.BLOCKED
            text = ("Search has not been performed; no verified search results are available."
                    if self.spec.language == "en" else "尚未执行有效搜索，没有可核验的搜索结果。")
        elif self.spec.intent == AgentMode.EXECUTE_PLAN and not any(
            item["tool"] in {"mod_install", "mod_install_custom", "mod_install_batch",
                             "workshop_install", "tool_extract", "game_config_write"}
            for item in self._tool_successes
        ):
            status, state = "blocked", TaskState.BLOCKED
            text = "没有取得安装完成的工具证据；未确认计划或未完成项目需要先核验，不能仅凭模型回复标记完成。"
        else:
            status, state = "completed", TaskState.COMPLETED
        if self.spec.intent in {AgentMode.SEARCH_EXACT, AgentMode.RECOMMEND_BROAD} and status == "completed":
            count = sum(item["tool"] in SEARCH_TOOLS for item in self._tool_successes)
            text = (f"Search finished: {count} successful search steps. See the results above."
                    if self.spec.language == "en" else f"搜索结束：{count} 个搜索步骤成功，匹配结果见上方。")
        elif self.spec.intent in {AgentMode.SEARCH_EXACT, AgentMode.RECOMMEND_BROAD} and self._tool_failures:
            text = ("Some sources failed; available search results have been retained."
                    if self.spec.language == "en" else "部分来源未完成；已经取得的搜索结果已保留。") if status == "partial" else (
                "Search did not complete. Failed sources do not prove that matching Mods do not exist."
                if self.spec.language == "en" else "搜索未完成。来源失败不能证明没有相关 Mod，请查看未完成项。")
        elif self.spec.intent == AgentMode.CHAT_EXPLAIN and status == "completed" and not self._tool_successes:
            text = "Answered." if self.spec.language == "en" else "已回答本轮问题。"
        if self._search_result is not None and status in {'completed', 'partial'}:
            result = self._search_result
            matched, requested = result['matched'], result['requested']
            insufficient = matched == 0 or (requested is not None and matched < requested)
            if insufficient:
                status, state = 'partial', TaskState.PARTIAL
            if self.spec.language.startswith('en'):
                text = f"Search ended: {result['candidates']} candidates, {matched} with goal-matching evidence."
                if requested is not None:
                    text += f' Requested: {requested}.'
                if insufficient:
                    text += ' The requested results were not fully obtained; unrelated Mods were not counted as matches.'
                if self._tool_failures:
                    text += ' Some steps were blocked or failed; available results were retained.'
            else:
                text = f"搜索结束：展示 {result['candidates']} 个候选，其中 {matched} 个具有需求匹配证据。"
                if requested is not None:
                    text += f'你要求 {requested} 项。'
                if insufficient:
                    text += '尚未取得足够的匹配结果，不以无关 Mod 凑数。'
                if self._tool_failures:
                    text += '部分步骤受限或失败，已保留现有结果。'
        if not text:
            text = (
                "任务已部分完成，失败项可单独重试。"
                if status == "partial" else
                "任务执行失败，未得到可验证的完成结果。"
                if status == "failed" else
                "任务已暂停，需要用户处理未完成项。"
                if status == "blocked" else "本轮任务已完成。"
            )
        self.finish(TaskResult(
            status=status,
            summary=text,
            completed=tuple(self._tool_successes),
            not_completed=tuple(self._tool_failures),
            retryable=status in {"partial", "failed"},
            next_actions=(
                ({"action": "retry_failed_items"},)
                if status in {"partial", "failed"} else ()
            ),
        ), state=state)

    def cancel(self, reason: str, *, replaced: bool = False) -> None:
        if self._finished:
            return
        state = TaskState.PAUSED_BY_NEW_TURN if replaced else TaskState.CANCELLED
        result = TaskResult(
            status="cancelled", summary=str(reason or "任务已取消"),
            not_completed=({"reason": str(reason or "任务已取消")},),
            retryable=bool(replaced),
        )
        self.finish(result, state=state)

    def fail(self, message: str, *, retryable: bool = False) -> None:
        self.finish(TaskResult(
            status="failed", summary=str(message or "任务失败"),
            not_completed=({"reason": str(message or "任务失败")},),
            retryable=retryable,
        ), state=TaskState.FAILED)

    @_serialized
    def interrupt(self, message: str, *, retryable: bool = False) -> None:
        """An orchestration failure is not erased by successful earlier tools."""
        if self._finished:
            return
        partial = bool(self._tool_successes)
        self.finish(TaskResult(
            status="partial" if partial else "failed", summary=str(message),
            completed=tuple(self._tool_successes),
            not_completed=tuple(self._tool_failures) + ({"reason": str(message)},),
            retryable=retryable,
        ), state=TaskState.PARTIAL if partial else TaskState.FAILED)

    def _emit(self, event_type: str, payload: dict[str, Any]) -> None:
        event = store.append_event(self.spec.task_id, event_type, self.state, payload)
        if self.enforcing and self.event_sink is not None:
            self.event_sink(event)

    @staticmethod
    def _target_key(args: dict[str, Any]) -> str:
        for key in (
            "selection_key", "mod_id", "source_id", "snapshot_id", "file_id",
            "url", "local_path", "query",
        ):
            value = args.get(key)
            if value not in (None, ""):
                return f"{key}:{value}"
        return "task"

    @staticmethod
    def _summary(value: str, limit: int = 800) -> str:
        text = str(value or "").strip()
        if len(text) <= limit:
            return text
        return text[: limit - 1].rstrip() + "…"
