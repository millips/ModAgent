"""User's reported conversation, not isolated keyword happy paths."""
import json
from types import SimpleNamespace

import pytest

from modagent import db
from modagent.orchestration.models import AgentMode, TaskSpec
from modagent.orchestration.router import route_message
from modagent.orchestration.runtime import AgentCoreRuntime
from modagent.orchestration import store


HISTORY = [
    {"role": "user", "content": "mod是什么"},
    {"role": "assistant", "content": "Mod 是游戏修改或扩展。"},
    {"role": "user", "content": "我害怕 不敢玩 新手什么都不懂 难度太大了 有没有帮我快速适应的方法"},
    {"role": "assistant", "content": "可以先练习，或者查找辅助学习、界面优化的 Mod。"},
    {"role": "user", "content": "帮我搜搜看 最适合我的mod 如何"},
    {"role": "assistant", "content": "你更想辅助学习，还是界面优化？"},
]


@pytest.mark.parametrize("message", ["帮我搜搜看 最适合我的mod 如何", "搜搜看有哪些 UI mod", "帮我搜一下新手mod", "look up some beginner mods"])
def test_colloquial_search_has_search_tools(message):
    assert route_message(message).intent in {AgentMode.SEARCH_EXACT, AgentMode.RECOMMEND_BROAD}


def test_refinement_continues_read_only_search():
    decision = route_message("辅助学习的 界面优化的", history=HISTORY)
    assert decision.intent in {AgentMode.SEARCH_EXACT, AgentMode.RECOMMEND_BROAD}
    assert not decision.install_authorized and not decision.destructive_authorized
    assert "辅助学习" in decision.search_goal and "界面优化" in decision.search_goal


@pytest.mark.parametrize("message", ["？", "你刚才做了什么？", "为什么没有结果？", "不用搜了", "先别搜索", "解释一下界面优化是什么意思", "今天先到这里", "确认安装"])
def test_interruption_does_not_resume_search_or_authorize_writes(message):
    decision = route_message(message, history=HISTORY)
    assert decision.intent not in {AgentMode.SEARCH_EXACT, AgentMode.RECOMMEND_BROAD}
    assert not decision.install_authorized and not decision.destructive_authorized


def test_no_search_history_no_automatic_search():
    assert route_message("辅助学习的 界面优化的", history=HISTORY[:2]).intent == AgentMode.CHAT_EXPLAIN


def test_do_not_recommend_still_allows_requested_update_check():
    assert route_message("只检查本机清单的更新，不要推荐新 Mod。").intent == AgentMode.UPDATE_INSTALLED


@pytest.fixture
def runtime(monkeypatch, tmp_path):
    monkeypatch.setattr(db, "DB_FILE", str(tmp_path / "state.db"))
    db.init_db()
    spec = TaskSpec.create(session_id="r4", game_id="fixture", intent=AgentMode.SEARCH_EXACT, user_goal="搜索界面优化")
    runtime = AgentCoreRuntime(spec, feature_mode="on")
    runtime.start()
    return runtime


def test_search_without_receipt_is_not_completed(runtime):
    runtime.finalize_from_text("请先告诉我更多偏好。")
    task = store.get_task(runtime.spec.task_id)
    assert task["state"] == "BLOCKED"
    assert "未" in task["outcome"]["summary"]


def test_real_empty_search_can_complete_without_fabricated_candidates(runtime):
    runtime.tool_started("nexus_search", {"query": "UI"})
    runtime.tool_finished("nexus_search", {"query": "UI"}, json.dumps({"status": "ok", "results": []}), True)
    runtime.finalize_from_text("本次没有匹配结果，不代表全网不存在。")
    assert store.get_task(runtime.spec.task_id)["state"] == "COMPLETED"


def test_details_only_do_not_prove_search_completed(runtime):
    runtime.tool_started("get_installed", {})
    runtime.tool_finished("get_installed", {}, '[]', True)
    runtime.finalize_from_text("可以去某平台找找。")
    assert store.get_task(runtime.spec.task_id)["state"] == "BLOCKED"


@pytest.mark.parametrize("consulted,failed,expected", [
    ([], {"github": "timeout"}, "FAILED"),
    (["nexus"], {"github": "timeout"}, "PARTIAL"),
    (["nexus"], {}, "COMPLETED"),
])
def test_aggregate_search_status_matches_source_receipts(runtime, consulted, failed, expected):
    result = {"sources_consulted": consulted, "sources_failed": failed, "recommendations": []}
    runtime.tool_started("mod_recommend", {"query": "UI"})
    runtime.tool_finished("mod_recommend", {"query": "UI"}, json.dumps(result), not bool(failed))
    runtime.finalize_from_text("搜索已经完成了。")
    assert store.get_task(runtime.spec.task_id)["state"] == expected


def test_reported_conversation_reaches_real_api_recommendation_event(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    from modagent import api, agent as agent_module
    from modagent.agent import Agent
    from modagent.config import Config
    monkeypatch.setattr(db, "DB_FILE", str(tmp_path / "flow.db"))
    db.init_db()
    monkeypatch.setattr(api, "cfg", Config(agent_core_v2="on", game_name="Fixture Game", game_slug="fixturegame"))
    monkeypatch.setattr(api, "_API_TOKEN", "fixture-token")
    monkeypatch.setattr(api, "_chat_tasks", {})
    monkeypatch.setattr(api, "agents", {})
    monkeypatch.setattr(agent_module, "refresh_local_inventory", lambda *a: None)
    monkeypatch.setattr(agent_module, "ENABLE_REPORT_VALIDATION", False)
    monkeypatch.setattr(agent_module, "ENABLE_STATE_CHECK", False)
    calls = []
    def execute(name, args, cfg):
        calls.append((name, args))
        assert name == "mod_recommend", "search must not perform a write"
        return json.dumps({"query": args["query"], "sources_consulted": ["nexus"], "recommendations": [{
            "mod_id": 42, "name": "Training UI Helper", "summary": "Training assistance and clearer UI for Fixture Game.",
            "url": "https://www.nexusmods.com/fixturegame/mods/42", "version": "1.0",
        }]})
    monkeypatch.setattr(agent_module, "execute", execute)
    class ProseOnlyAgent(Agent):
        def _stream(self, messages, tools):
            # Reproduce the original failure: the LLM keeps asking preference
            # questions, even though the task is explicitly a read-only search.
            return [SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(
                content="请先告诉我更多偏好。", tool_calls=None))])]
        def _localize_recommendation_set(self, payload):
            return payload
    monkeypatch.setattr(api, "Agent", ProseOnlyAgent)
    db.create_session("flow", "test", "fixturegame")
    db.update_session_messages("flow", HISTORY)
    client = TestClient(api.app, headers={"X-ModAgent-Token": "fixture-token"})
    try:
        response = client.post("/chat/stream", json={"message": "辅助学习的 界面优化的", "session_id": "flow"})
        assert response.status_code == 200
        events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
        assert len(calls) == 1, events
        assert "辅助学习" in calls[0][1]["query"] and "界面优化" in calls[0][1]["query"]
        recommendations = [e["recommendations"] for e in events if "recommendations" in e]
        assert len(recommendations) == 1, events
        assert "Training UI Helper" in json.dumps(recommendations)
        terminal = [e["task_event"] for e in events if e.get("task_event", {}).get("type") == "task_completed"]
        assert len(terminal) == 1, events
        response = client.post("/chat/stream", json={"message": "你刚才做了什么？", "session_id": "flow"})
        assert response.status_code == 200
        assert len(calls) == 1, "ordinary follow-up must not repeat the search"
        events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
        terminal = [e["task_event"] for e in events if e.get("task_event", {}).get("type") == "task_completed"]
        assert terminal[-1]["payload"]["presentation"]["show_card"] is False
    finally:
        client.close()
