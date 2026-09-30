"""Safety regressions derived from the September audit, not happy-path counts.

All tools and model responses are stubs; fixtures use an isolated database.
"""
import json
from types import SimpleNamespace

import pytest

from modagent import agent as agent_module, db
from modagent.config import Config
from modagent.orchestration import store
from modagent.orchestration.models import AgentMode, TaskSpec, TaskState
from modagent.orchestration.router import route_message
from modagent.orchestration.runtime import AgentCoreRuntime


@pytest.fixture
def runtime_factory(monkeypatch, tmp_path):
    monkeypatch.setattr(db, "DB_FILE", str(tmp_path / "state.db"))
    db.init_db()

    def create(mode=AgentMode.SEARCH_EXACT, feature="on", **kwargs):
        spec = TaskSpec.create(session_id="audit", game_id="fixture",
                               intent=mode, user_goal="audit fixture", **kwargs)
        runtime = AgentCoreRuntime(spec, feature_mode=feature)
        runtime.start()
        return runtime
    return create


@pytest.mark.parametrize("message", [
    "不要帮我更新，我只是想知道全部更新是什么意思",
    "直接更新所有 mod", "确认安装", "按计划安装", "update all mods",
    '请解释这句话："确认安装"',
])
def test_a01_natural_language_never_grants_write_permission(message):
    decision = route_message(message, has_selection=True)
    assert not decision.install_authorized
    assert not decision.destructive_authorized


@pytest.mark.parametrize("message,intent", [
    ("不要帮我更新，我只是想知道全部更新是什么意思", AgentMode.CHAT_EXPLAIN),
    ("为什么检查更新会失败？先别更新", AgentMode.DIAGNOSE),
    ("分享码是什么意思？", AgentMode.CHAT_EXPLAIN),
])
def test_a01_explanation_and_diagnosis_precede_operation_keywords(message, intent):
    assert route_message(message).intent == intent


def test_a02_error_explanation_does_not_turn_failure_into_success(runtime_factory):
    runtime = runtime_factory()
    runtime.tool_finished("nexus_search", {"query": "Tifa"}, '{"error":"timeout"}', False)
    runtime.finalize_from_text("搜索失败，请稍后重试。")
    assert store.get_task(runtime.spec.task_id)["state"] == "FAILED"


def test_a02_no_text_or_evidence_is_not_completion(runtime_factory):
    runtime = runtime_factory()
    runtime.finalize_from_text("")
    assert store.get_task(runtime.spec.task_id)["state"] == "FAILED"


@pytest.mark.parametrize("payload", [
    {"status": "manual_action_required", "message": "please log in"},
    {"status": "partial_manual_action_required"},
    {"status": "preinstall_confirmation_required", "requires_confirmation": True},
    {"status": "failed", "error": "timeout"},
])
def test_a03_non_success_never_becomes_completed_effect(runtime_factory, payload):
    runtime = runtime_factory(AgentMode.EXECUTE_PLAN, authorization={"install": True})
    args = {"mod_id": "390", "file_id": "11"}
    # Even a mistaken legacy boolean cannot override the actual payload.
    runtime.tool_finished("mod_download", args, json.dumps(payload), True)
    runtime.finalize_from_text("请先登录或确认后重试。")
    assert runtime.completed_effect("mod_download", args) is None
    assert store.get_task(runtime.spec.task_id)["state"] != "COMPLETED"


def test_a04_stream_exception_cannot_be_finalized_as_completed(runtime_factory, monkeypatch):
    runtime = runtime_factory()
    agent = agent_module.Agent(Config())

    def broken_stream():
        yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(
            content="partial text", tool_calls=None))])
        raise TimeoutError("simulated SSE read timeout")

    monkeypatch.setattr(agent, "_stream", lambda *args: broken_stream())
    events = []
    try:
        events = list(agent.chat_stream("帮我找 Tifa", task_spec=runtime.spec,
                                       core_runtime=runtime, core_mode="on"))
    except TimeoutError:
        runtime.fail("API observed stream failure", retryable=True)
    task = store.get_task(runtime.spec.task_id)
    assert task["state"] == "FAILED"
    assert task["outcome"]["summary"]
    if events:
        assert any(json.loads(event).get("chunk") for event in events)


def test_a05_shadow_does_not_change_execution(runtime_factory, monkeypatch):
    runtime = runtime_factory(AgentMode.EXECUTE_PLAN, feature="shadow",
                              authorization={"install": True})
    agent = agent_module.Agent(Config())
    agent._core_runtime, agent._core_spec = runtime, runtime.spec
    calls = []

    def execute(name, args, cfg):
        calls.append(args)
        return '{"status":"completed"}'

    monkeypatch.setattr(agent_module, "execute", execute)
    for label in ("Tool One", "Tool Two"):
        result = json.loads(agent._exec("tool_extract", {
            "local_path": "fixture.zip", "display_name": label}))
        assert not result.get("reused_effect")
    assert len(calls) == 2
    assert runtime.completed_effect("tool_extract", {"local_path": "fixture.zip"}) is None
    assert not store.get_task(runtime.spec.task_id)["checkpoint"]


def test_a06_cancel_rejects_late_tool_events_and_checkpoints(runtime_factory):
    runtime = runtime_factory()
    runtime.cancel("user cancelled")
    before = store.list_events(runtime.spec.task_id)
    runtime.tool_finished("nexus_search", {"query": "late"}, '{"items":[]}', True)
    runtime.tool_started("nexus_search", {"query": "too late"})
    assert store.list_events(runtime.spec.task_id) == before
    assert not store.get_task(runtime.spec.task_id)["checkpoint"]


def test_positive_partial_and_explanation_remain_reachable(runtime_factory):
    runtime = runtime_factory()
    runtime.tool_finished("nexus_search", {}, '{"items":[]}', True)
    runtime.tool_finished("github_search", {}, '{"error":"timeout"}', False)
    runtime.finalize_from_text("Nexus 无结果，GitHub 超时。")
    assert store.get_task(runtime.spec.task_id)["state"] == "PARTIAL"
    explanation = runtime_factory(AgentMode.CHAT_EXPLAIN)
    explanation.finalize_from_text("Mod 是游戏的扩展内容。")
    assert explanation.state == TaskState.COMPLETED


@pytest.mark.parametrize("feature", ["off", "shadow", "on"])
@pytest.mark.parametrize("message", [
    "不要安装这个 mod", "Do not install this mod", "？",
    "为什么检查更新会失败？先别更新", '解释一下“确认安装”是什么意思',
])
def test_a07_common_entry_denies_question_and_negation_writes(runtime_factory, monkeypatch, feature, message):
    agent = agent_module.Agent(Config(dev_mode=True))
    agent._current_user_msg = message
    if feature != "off":
        runtime = runtime_factory(AgentMode.EXECUTE_PLAN, feature=feature,
                                  authorization={"install": True})
        agent._core_runtime, agent._core_spec = runtime, runtime.spec
    monkeypatch.setattr(agent_module, "execute", lambda *a: pytest.fail("unauthorized tool ran"))
    result = json.loads(agent._exec("mod_install", {"mod_id": "42", "confirmed": True}))
    assert result["error"] == "execution_confirmation_required"


def test_a05_shadow_storage_failure_cannot_block_real_tool(runtime_factory, monkeypatch):
    runtime = runtime_factory(AgentMode.EXECUTE_PLAN, feature="shadow")
    agent = agent_module.Agent(Config())
    agent._core_runtime, agent._core_spec = runtime, runtime.spec
    monkeypatch.setattr(store, "append_event", lambda *a: (_ for _ in ()).throw(OSError("disk full")))
    monkeypatch.setattr(agent_module, "execute", lambda *a: '{"status":"completed"}')
    assert json.loads(agent._exec("tool_extract", {"local_path": "fixture.zip"}))["status"] == "completed"


def test_a08_files_and_batches_do_not_share_effect_key(runtime_factory):
    runtime = runtime_factory(AgentMode.EXECUTE_PLAN)
    assert runtime.idempotency_key("mod_download", {"mod_id": "390", "file_id": "11"}) != runtime.idempotency_key("mod_download", {"mod_id": "390", "file_id": "12"})
    assert runtime.idempotency_key("batch_download", {"mods": [{"mod_id": "1"}]}) != runtime.idempotency_key("batch_download", {"mods": [{"mod_id": "2"}]})


def test_a02_model_install_claim_without_tool_evidence_is_blocked(runtime_factory):
    runtime = runtime_factory(AgentMode.EXECUTE_PLAN)
    runtime.finalize_from_text("所有 Mod 安装成功。")
    result = store.get_task(runtime.spec.task_id)["outcome"]
    assert result["status"] == "blocked"
    assert "没有取得" in result["summary"]


def test_a03_failed_batch_does_not_enter_success_ledger(runtime_factory):
    runtime = runtime_factory(AgentMode.EXECUTE_PLAN)
    args = {"mods": [{"mod_id": "1"}, {"mod_id": "2"}]}
    runtime.tool_finished("batch_download", args, '{"status":"completed","failed":1}', True)
    assert runtime.completed_effect("batch_download", args) is None


def test_a09_task_spec_is_deeply_immutable_and_round_trips():
    selected = [{"mod_id": "390", "components": [{"file_id": "11"}]}]
    constraints = {"allowed": ["read"]}
    spec = TaskSpec.create(session_id="s", game_id="g", intent=AgentMode.BUILD_PLAN,
                           user_goal="plan", targets=selected, constraints=constraints)
    selected[0]["components"][0]["file_id"] = "999"
    constraints["allowed"].append("write")
    assert spec.targets[0]["components"][0]["file_id"] == "11"
    assert spec.constraints["allowed"] == ("read",)
    with pytest.raises(TypeError):
        spec.authorization["install"] = True
    with pytest.raises(TypeError):
        spec.targets[0]["components"][0]["file_id"] = "999"
    restored = TaskSpec.from_dict(json.loads(json.dumps(spec.to_dict())))
    assert restored == spec
    with pytest.raises(TypeError):
        restored.constraints["allowed"] = ("write",)
