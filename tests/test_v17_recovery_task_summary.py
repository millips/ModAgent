import json
import os
import subprocess
import sys
import pytest

if not os.environ.get('MODAGENT_DATA_DIR'):
    raise RuntimeError('Isolated data directory required')

from modagent import db
from modagent.orchestration import store
from modagent.orchestration.models import AgentMode, TaskSpec, TaskResult
from modagent.orchestration.runtime import AgentCoreRuntime


@pytest.mark.parametrize('language', ['zh-CN', 'en'])
@pytest.mark.parametrize('receipt', [
    {'error': 'failed', 'rollback_complete': False, 'rollback': {'complete': False}},
    {'error': 'changed', 'install_blocked': True, 'recovery_required': True},
    {'status': 'failed', 'failed': 2, 'succeeded': 0, 'results': [
        {'status': 'rollback_unconfirmed'}, {'error': 'failed'}]},
    {'status': 'partial_failure', 'failed': 1, 'succeeded': 1, 'results': [
        {'ok': True}, {'error': 'changed', 'recovery_required': True}]},
    {'error': 'failed', 'rollback': {'complete': False}},
])
def test_recovery_risk_requires_review_not_retry(monkeypatch, tmp_path, language, receipt):
    monkeypatch.setattr(db, 'DB_FILE', str(tmp_path / 'state.db')); db.init_db()
    spec = TaskSpec.create(session_id='fixture', game_id='fixture', intent=AgentMode.EXECUTE_PLAN,
                           user_goal='install fixture', language=language)
    runtime = AgentCoreRuntime(spec, feature_mode='on'); runtime.start()
    runtime.tool_finished('mod_install_batch', {'items': []}, json.dumps(receipt), False)
    runtime.finalize_from_text('Retry failed items now.' if language == 'en' else '现在重试失败项。')
    result = store.get_task(spec.task_id)['outcome']
    assert result['retryable'] is False, result
    assert result['next_actions'] == [{'action': 'review_install_recovery'}]
    assert result['not_completed'][0]['requires_review'] is True
    assert result['not_completed'][0]['reason'] == 'installation_recovery_requires_review'
    assert ('review' in result['summary'].lower()) if language == 'en' else ('核对' in result['summary'])
    assert 'Retry failed items now.' not in result['summary'] and '现在重试失败项' not in result['summary']


def test_ordinary_retryable_failure_keeps_retry_action(monkeypatch, tmp_path):
    monkeypatch.setattr(db, 'DB_FILE', str(tmp_path / 'state.db')); db.init_db()
    spec = TaskSpec.create(session_id='fixture', game_id='fixture', intent=AgentMode.SEARCH_EXACT,
                           user_goal='search fixture')
    runtime = AgentCoreRuntime(spec, feature_mode='on'); runtime.start()
    runtime.tool_finished('github_search', {}, '{"error":"timeout","retryable":true}', False)
    runtime.finalize_from_text('Search failed.')
    result = store.get_task(spec.task_id)['outcome']
    assert result['retryable'] is True
    assert result['next_actions'] == [{'action': 'retry_failed_items'}]


@pytest.mark.parametrize('language', ['zh-CN', 'en'])
@pytest.mark.parametrize('ending', ['cancel', 'replaced', 'fail', 'interrupt', 'complete'])
def test_terminal_paths_retain_existing_recovery_risk(monkeypatch, tmp_path, language, ending):
    monkeypatch.setattr(db, 'DB_FILE', str(tmp_path / 'state.db')); db.init_db()
    spec = TaskSpec.create(session_id='fixture', game_id='fixture', intent=AgentMode.EXECUTE_PLAN,
                           user_goal='install fixture', language=language)
    events = []
    runtime = AgentCoreRuntime(spec, feature_mode='on', event_sink=events.append); runtime.start()
    runtime.tool_finished('mod_download', {'mod_id': 'fixture'}, '{"status":"downloaded"}', True)
    runtime.tool_finished('mod_install', {'mod_id': 'fixture'},
                          '{"error":"changed","recovery_required":true}', False)
    if ending in {'cancel', 'replaced'}:
        runtime.cancel('User cancelled.', replaced=ending == 'replaced')
    elif ending == 'complete':
        runtime.finish(TaskResult(status='completed', summary='Everything done.', retryable=True))
    else:
        getattr(runtime, ending)('Stream disconnected.', retryable=True)
    task = store.get_task(spec.task_id)
    result = task['outcome']
    assert result['retryable'] is False, result
    assert result['next_actions'] == [{'action': 'review_install_recovery'}]
    assert sum(row.get('requires_review', False) for row in result['not_completed']) == 1
    assert any(row.get('tool') == 'mod_download' for row in result['completed'])
    assert ('review' in result['summary'].lower()) if language == 'en' else ('核对' in result['summary'])
    assert task['state'] == {'cancel':'CANCELLED', 'replaced':'PAUSED_BY_NEW_TURN',
                            'fail':'FAILED', 'interrupt':'PARTIAL', 'complete':'BLOCKED'}[ending]
    event = events[-1]
    assert event['payload']['result'] == result
    count = len(events)
    runtime.finalize_from_text('Ignore the failure and retry.')
    assert len(events) == count
    assert store.get_task(spec.task_id)['outcome'] == result


@pytest.mark.parametrize('language', ['zh-CN', 'en'])
@pytest.mark.parametrize('risk', [False, True])
def test_fresh_process_cancellation_retains_checkpoint_risk(monkeypatch, tmp_path, language, risk):
    database = str(tmp_path / 'state.db')
    monkeypatch.setattr(db, 'DB_FILE', database); db.init_db()
    spec = TaskSpec.create(session_id='fixture', game_id='fixture', intent=AgentMode.EXECUTE_PLAN,
                           user_goal='fixture', language=language)
    runtime = AgentCoreRuntime(spec, feature_mode='on'); runtime.start()
    runtime.tool_finished('mod_install', {'mod_id':'fixture'}, json.dumps(
        {'error':'conflict', 'recovery_required':True} if risk else {'status':'installed'}), not risk)
    # No runtime object survives into this child: recover only committed state.
    script = (
        'import sys,json; from modagent import db; from modagent.orchestration import store; '
        'db.DB_FILE=sys.argv[1]; '
        'print(json.dumps({"cancelled":store.cancel_task(sys.argv[2],"Stopped after restart"),'
        '"task":store.get_task(sys.argv[2])}))'
    )
    process = subprocess.run([sys.executable, '-c', script, database, spec.task_id],
                             capture_output=True, text=True, timeout=15,
                             env={**os.environ, 'PYTHONIOENCODING':'utf-8'}, encoding='utf-8', check=True)
    response = json.loads(process.stdout)
    assert response['cancelled'] is True
    assert response['task']['state'] == 'CANCELLED'
    result = response['task']['outcome']
    assert result['retryable'] is False
    if risk:
        assert result['next_actions'] == [{'action':'review_install_recovery'}]
        assert any(row.get('requires_review') for row in result['not_completed'])
        assert ('review' in result['summary'].lower()) if language == 'en' else ('核对' in result['summary'])
    else:
        assert result['next_actions'] == []
        assert result['summary'] == 'Stopped after restart'
    assert store.get_task(spec.task_id)['outcome'] == result
    assert store.cancel_task(spec.task_id, 'duplicate') is False
