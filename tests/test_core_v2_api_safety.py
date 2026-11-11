"""Public API failure paths with real temporary SQLite and no model/network."""
import json

import pytest
from fastapi.testclient import TestClient

from modagent import api, db
from modagent.config import Config
from modagent.orchestration.models import AgentMode, TaskSpec
from modagent.orchestration.runtime import AgentCoreRuntime
from modagent.orchestration import store


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setattr(db, "DB_FILE", str(tmp_path / "state.db"))
    db.init_db()
    monkeypatch.setattr(api, "cfg", Config(agent_core_v2="on"))
    monkeypatch.setattr(api, "_API_TOKEN", "fixture-token")
    monkeypatch.setattr(api, "_chat_tasks", {})
    monkeypatch.setattr(api, "agents", {})
    # No lifespan: never load the tester's real configuration or start checks.
    instance = TestClient(api.app, headers={"X-ModAgent-Token": "fixture-token"})
    yield instance
    instance.close()


def test_legacy_resume_rejected_before_history_or_worker_changes(client, monkeypatch):
    db.create_session("s", "fixture", "g")
    original = [{"role": "user", "content": "original selection"}]
    db.update_session_messages("s", original)
    spec = TaskSpec.create(session_id="s", game_id="g", intent=AgentMode.EXECUTE_PLAN,
                           user_goal="install", targets=[{"mod_id": "42"}])
    runtime = AgentCoreRuntime(spec, feature_mode="on")
    runtime.start()
    runtime.fail("interrupted")
    before = store.get_task(spec.task_id)
    monkeypatch.setattr(api, "Agent", lambda *a: pytest.fail("unsafe resume started an agent"))
    for path, body in [
        (f"/tasks/{spec.task_id}/resume", {}),
        ("/chat/stream", {"session_id": "s", "message": "继续", "resume_task_id": spec.task_id,
                           "selection_action": "confirm", "recommendation_selection": [{"mod_id": "999"}]}),
    ]:
        response = client.post(path, json=body)
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "plan_revalidation_required"
    assert json.loads(db.get_session("s")["messages"]) == original
    assert store.get_task(spec.task_id) == before
    assert not api._chat_tasks


def test_client_confirm_without_server_plan_grant_is_rejected(client, monkeypatch):
    db.create_session("s", "fixture", "")
    original = [{"role": "user", "content": "original"}]
    db.update_session_messages("s", original)
    monkeypatch.setattr(api, "Agent", lambda *a: pytest.fail("ungranted execution started an agent"))
    response = client.post("/chat/stream", json={
        "session_id": "s", "message": "确认安装",
        "selection_action": "confirm",
        "recommendation_selection": [{"selection_key": "nexus:42"}],
    })
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "plan_revision_missing"
    assert json.loads(db.get_session("s")["messages"]) == original
    assert not api._chat_tasks


def test_valid_server_plan_grant_replaces_client_metadata(client, monkeypatch):
    game_id = api.game_storage_id(api.cfg)
    db.create_session("s", "fixture", game_id)
    target = {
        "selection_key": "nexus:42", "source": "nexus", "source_id": "42",
        "canonical_tool_mod_id": "42", "name": "Trusted server name",
        "installable": True,
        "variants": [{"variant_id": "42:102", "file_id": "102", "name": "Large", "file_name": "large.zip"}],
    }
    plan = TaskSpec.create(
        session_id="s", game_id=game_id, intent=AgentMode.BUILD_PLAN,
        user_goal="plan", targets=[target],
    )
    runtime = AgentCoreRuntime(plan, feature_mode="on")
    runtime.start()
    runtime.record_plan_revision({"items": [target], "selected_keys": ["nexus:42"]})
    runtime.finalize_from_text("ready", waiting_confirmation=True)
    revision = store.get_plan_revision(plan.task_id)
    captured = {}

    class CapturingAgent:
        def __init__(self, cfg):
            self.history = []

        def chat_stream(self, message, **kwargs):
            captured["spec"] = kwargs["task_spec"]
            captured["selection"] = kwargs["recommendation_selection"]
            self.history = [{"role": "user", "content": message}, {"role": "assistant", "content": "captured"}]
            yield json.dumps({"chunk": "captured"}, ensure_ascii=False)
            yield json.dumps({"done": True})

    monkeypatch.setattr(api, "Agent", CapturingAgent)
    response = client.post("/chat/stream", json={
        "session_id": "s", "message": "确认安装",
        "selection_action": "confirm", "plan_task_id": plan.task_id,
        "plan_revision_id": revision.revision_id,
        "recommendation_selection": [{
            "selection_key": "nexus:42", "source": "nexus", "source_id": "42",
            "canonical_tool_mod_id": "42", "variant_id": "42:102",
            "selected_variant_id": "42:102", "file_id": "102", "name": "tampered client name",
        }],
    })
    assert response.status_code == 200
    assert captured["spec"].authorization["install"] is True
    assert captured["spec"].constraints["execution_grant_id"].startswith("grant_")
    assert captured["selection"][0]["name"] == "Trusted server name"


@pytest.mark.parametrize("feature", ["off", "shadow", "on"])
def test_unexpected_worker_exception_has_user_reply_and_preserves_request(client, monkeypatch, feature):
    api.cfg.agent_core_v2 = feature

    class FailingAgent:
        def __init__(self, cfg):
            self.history = []

        def chat_stream(self, *args, **kwargs):
            raise RuntimeError("private-path-or-provider-secret")
            yield  # generator, failure occurs during iteration

    monkeypatch.setattr(api, "Agent", FailingAgent)
    response = client.post("/chat/stream", json={"message": "发生了什么？"})
    assert response.status_code == 200
    events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
    assert any(event.get("chunk") and "中断" in event["chunk"] for event in events)
    assert "private-path-or-provider-secret" not in response.text
    sid = response.headers["X-ModAgent-Session"]
    history = json.loads(db.get_session(sid)["messages"])
    assert history[0] == {"role": "user", "content": "发生了什么？"}
    assert history[-1]["role"] == "assistant"
    if feature == "on":
        terminal = [event["task_event"] for event in events if event.get("task_event", {}).get("type") == "task_failed"]
        assert len(terminal) == 1
    if feature == "shadow":
        assert not any(event.get("task_event") for event in events), "shadow must not drive the UI"
