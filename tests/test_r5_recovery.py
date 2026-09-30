import json
import os
import subprocess
import sys
import pytest
from fastapi.testclient import TestClient
from modagent import api, db
from modagent.config import Config, make_game_instance_id
from modagent.orchestration import store
from modagent.orchestration.models import TaskSpec, TaskState, AgentMode
from modagent.orchestration.recovery import preview_recovery, RecoveryRejected


@pytest.fixture
def recovery(monkeypatch, tmp_path):
    monkeypatch.setattr(db, 'DB_FILE', str(tmp_path / 'state.db'))
    db.init_db()
    cfg = Config(game_root=str(tmp_path / 'game'), game_slug='fixture', agent_core_v2='on')
    db.create_session('recovery-session', 'test', 'fixture')
    spec = TaskSpec.create(session_id='recovery-session', game_id='fixture', intent=AgentMode.EXECUTE_PLAN,
        user_goal='安装已经选择的变体', targets=[{'source': 'nexus', 'mod_id': '42', 'file_id': '102', 'version': '1.0'}],
        constraints={'game_instance_id': make_game_instance_id(cfg.game_root)})
    store.create_task(spec, TaskState.PARTIAL)
    return cfg, spec, tmp_path


def test_recovery_preserves_selection_but_never_write_authorization(recovery):
    cfg, spec, _ = recovery
    result = preview_recovery(spec.task_id, cfg)
    assert result['recommendation_selection'][0]['file_id'] == '102'
    assert result['selection_action'] == 'plan'
    assert result['write_authorized'] is False


def test_recovery_rejects_another_game_install(recovery):
    cfg, spec, root = recovery
    cfg.game_root = str(root / 'other')
    with pytest.raises(RecoveryRejected, match='game_instance_changed'):
        preview_recovery(spec.task_id, cfg)


def test_actual_new_process_recovers_exact_targets(recovery):
    cfg, spec, root = recovery
    env = {**os.environ, 'MODAGENT_DATA_DIR': str(root), 'PYTHONIOENCODING': 'utf-8'}
    code = ('import json,sys; from modagent.config import Config; '
            'from modagent.orchestration.recovery import preview_recovery; '
            'print(json.dumps(preview_recovery(sys.argv[1],Config(game_root=sys.argv[2]))))')
    output = subprocess.run([sys.executable, '-c', code, spec.task_id, cfg.game_root],
                            env=env, capture_output=True, text=True, timeout=15, check=True)
    result = json.loads(output.stdout)
    assert result['recommendation_selection'] == spec.to_dict()['targets']
    assert result['write_authorized'] is False


def test_api_recovery_cannot_inject_new_targets_or_confirmation(monkeypatch, recovery):
    cfg, spec, _ = recovery
    calls = []
    class FakeAgent:
        def __init__(self, cfg):
            self.history = []
        def chat_stream(self, message, **kwargs):
            calls.append(kwargs)
            kwargs['core_runtime'].finalize_from_text('核验计划', waiting_confirmation=True)
            yield json.dumps({'chunk': '核验计划，不执行安装'})
            yield json.dumps({'done': True})
    monkeypatch.setattr(api, 'cfg', cfg)
    monkeypatch.setattr(api, 'Agent', FakeAgent)
    monkeypatch.setattr(api, '_chat_tasks', {})
    monkeypatch.setattr(api, '_API_TOKEN', '')
    client = TestClient(api.app)
    try:
        response = client.post('/chat/stream', json={
            'message': '确认安装其他东西', 'session_id': spec.session_id,
            'recovery_task_id': spec.task_id, 'selection_action': 'confirm',
            'recommendation_selection': [{'source': 'nexus', 'mod_id': '999'}]})
        assert response.status_code == 200
    finally:
        client.close()
    assert calls[0]['selection_action'] == 'plan'
    assert calls[0]['recommendation_selection'] == spec.to_dict()['targets']
    assert not calls[0]['task_spec'].authorization['install']
