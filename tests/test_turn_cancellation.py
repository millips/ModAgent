import json
import threading

import pytest

from modagent import api, progress, task_control
from modagent.agent import Agent
from modagent.config import Config


def test_cancelled_agent_refuses_new_tool_execution():
    agent = Agent(Config())
    agent._cancel_check = lambda: True

    result = json.loads(agent._exec("github_search", {"query": "ignored"}))

    assert result["error"] == "task_cancelled"
    assert result["stop_further_downloads"] is True


def test_task_control_reaches_worker_thread():
    cancelled = threading.Event()
    cancelled.set()

    with task_control.bind(cancelled.is_set):
        with pytest.raises(task_control.TaskCancelled):
            task_control.raise_if_cancelled()


def test_aborted_progress_rejects_late_updates_from_stale_worker():
    ready = threading.Event()
    resume = threading.Event()

    def stale_worker():
        assert progress.start([{"mod_id": "same", "name": "old"}])
        progress.set_pct("same", 20)
        ready.set()
        resume.wait(timeout=2)
        progress.set_pct("same", 90)
        progress.finish()

    worker = threading.Thread(target=stale_worker)
    worker.start()
    assert ready.wait(timeout=2)
    assert progress.abort_active("stopped")

    assert progress.start([{"mod_id": "same", "name": "new"}])
    progress.set_pct("same", 10)
    resume.set()
    worker.join(timeout=2)

    state = progress.snapshot()
    assert state["active"] is True
    assert state["items"][0]["name"] == "new"
    assert state["items"][0]["pct"] == 10
    progress.finish()


def test_cancelled_chat_task_is_terminal_and_persists_boundary(monkeypatch):
    persisted = []
    monkeypatch.setattr(
        api.db,
        "update_session_messages",
        lambda session_id, messages: persisted.append((session_id, messages)),
    )
    event = threading.Event()
    task = {
        "session_id": "session-test",
        "pending_history": [{"role": "user", "content": "旧任务"}],
        "cancel_event": event,
        "done": False,
    }

    assert api._cancel_chat_task_locked(task, "用户点击了停止")

    assert event.is_set()
    assert task["done"] is True
    assert task["cancelled"] is True
    assert persisted[-1][0] == "session-test"
    assert persisted[-1][1][-1]["role"] == "assistant"
    assert "不会自动恢复" in persisted[-1][1][-1]["content"]
