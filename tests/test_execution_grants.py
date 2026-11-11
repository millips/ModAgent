import pytest

from modagent import db
from modagent.orchestration.authorization import (
    ExecutionGrantRejected,
    authorize_execution,
)
from modagent.orchestration.models import AgentMode, TaskSpec, TaskState
from modagent.orchestration.router import route_message
from modagent.orchestration.runtime import AgentCoreRuntime
from modagent.orchestration import store


@pytest.fixture
def isolated_db(monkeypatch, tmp_path):
    monkeypatch.setattr(db, "DB_FILE", str(tmp_path / "state.db"))
    db.init_db()


def make_waiting_plan():
    target = {
        "selection_key": "nexus:42", "source": "nexus", "source_id": "42",
        "canonical_tool_mod_id": "42", "name": "Fixture", "installable": True,
        "variants": [
            {"variant_id": "42:101", "file_id": "101", "name": "Small", "file_name": "small.zip", "version": "1"},
            {"variant_id": "42:102", "file_id": "102", "name": "Large", "file_name": "large.zip", "version": "2"},
        ],
    }
    spec = TaskSpec.create(
        session_id="session-a", game_id="game-a", intent=AgentMode.BUILD_PLAN,
        user_goal="build a plan", targets=[target],
    )
    events = []
    runtime = AgentCoreRuntime(spec, feature_mode="on", event_sink=events.append)
    runtime.start()
    runtime.record_plan_revision({"items": [target], "selected_keys": ["nexus:42"]})
    runtime.finalize_from_text("ready", waiting_confirmation=True)
    revision = store.get_plan_revision(spec.task_id)
    assert revision is not None
    assert store.get_task(spec.task_id)["state"] == TaskState.WAITING_CONFIRMATION.value
    assert events[-1]["payload"]["plan_revision"]["revision_id"] == revision.revision_id
    return spec, revision


def test_server_plan_normalizes_variant_and_consumes_once(isolated_db):
    spec, revision = make_waiting_plan()
    submitted = [{
        "selection_key": "nexus:42", "source": "nexus", "source_id": "42",
        "canonical_tool_mod_id": "42", "selected_variant_id": "42:102",
        "variant_id": "42:102", "file_id": "102", "name": "client text is not authoritative",
    }]
    grant = authorize_execution(
        plan_task_id=spec.task_id, plan_revision_id=revision.revision_id,
        session_id=spec.session_id, game_id=spec.game_id,
        submitted_targets=submitted,
    )
    target = dict(grant.targets[0])
    assert target["name"] == "Fixture"
    assert target["file_id"] == "102"
    assert target["file_name"] == "large.zip"
    with pytest.raises(ExecutionGrantRejected, match="already_consumed"):
        authorize_execution(
            plan_task_id=spec.task_id, plan_revision_id=revision.revision_id,
            session_id=spec.session_id, game_id=spec.game_id,
            submitted_targets=submitted,
        )


@pytest.mark.parametrize("change,code", [
    ({"selection_key": "nexus:999"}, "selection_not_in_plan"),
    ({"variant_id": "42:102", "selected_variant_id": "42:102", "file_id": "999"}, "variant_file_mismatch"),
])
def test_tampered_client_selection_is_rejected(isolated_db, change, code):
    spec, revision = make_waiting_plan()
    submitted = {
        "selection_key": "nexus:42", "source": "nexus", "source_id": "42",
        "canonical_tool_mod_id": "42", "variant_id": "42:101",
        "selected_variant_id": "42:101", "file_id": "101",
    }
    submitted.update(change)
    with pytest.raises(ExecutionGrantRejected, match=code):
        authorize_execution(
            plan_task_id=spec.task_id, plan_revision_id=revision.revision_id,
            session_id=spec.session_id, game_id=spec.game_id,
            submitted_targets=[submitted],
        )


def test_router_does_not_treat_client_confirm_as_authority():
    denied = route_message("confirm", selection_action="confirm", has_selection=True)
    assert denied.intent == AgentMode.EXECUTE_PLAN
    assert denied.install_authorized is False
    assert denied.read_only is True
    granted = route_message(
        "confirm", selection_action="confirm", has_selection=True,
        execution_granted=True,
    )
    assert granted.install_authorized is True
    assert granted.read_only is False
