"""Reported plan -> confused follow-up, with no live model or game writes."""
import json
import pytest
from modagent.report_validator import validate_search_report, build_search_fallback
from modagent.orchestration.router import route_message
from modagent.orchestration.models import AgentMode, TaskSpec

@pytest.mark.parametrize('text', ['?何意味', '什么意思？', '？？？', '我没看懂', '所以现在是什么情况？', 'what does that mean?'])
def test_confused_followup_is_read_only_recorded_explanation(text):
    route = route_message(text)
    assert route.reason == 'recorded_process_status'
    assert not route.install_authorized and not route.destructive_authorized

@pytest.mark.parametrize('text', ['UI 是什么意思？', '何意味这个词是什么意思', '解释一下安装计划的原理'])
def test_named_concept_is_not_hijacked_to_task_status(text):
    assert route_message(text).reason != 'recorded_process_status'

@pytest.mark.parametrize('text', ['?何意味', '我没看懂', '什么意思？'])
def test_concept_followup_stays_conversational(text):
    history = [{'role':'user', 'content':'搜索 UI Mod'},
               {'role':'user', 'content':'UI 是什么意思？'},
               {'role':'assistant', 'content':'UI 是用户界面。'}]
    for _ in range(2):
        route = route_message(text, history=history)
        assert route.intent == AgentMode.CHAT_EXPLAIN and route.reason == 'conversation_clarification'
        history.extend([{'role':'user','content':text}, {'role':'assistant','content':'就是你看到的菜单和信息栏。'}])

@pytest.mark.parametrize('text', ['不代表全网没有相关 Mod。', 'Nexus 详情已查，下面说明安装计划。',
    '不能证明平台未收录、专区不存在或全网没有相关 Mod。', '没有查询全部来源。'])
def test_cautious_explanation_is_not_a_search_claim(text):
    assert validate_search_report(text, []).ok

@pytest.mark.parametrize('text', ['Nexus 已搜索。', '所有来源都翻了一遍，全网没有相关 Mod。',
    '不能证明全网没有。Nexus 确定没有专区。'])
def test_real_unsupported_claim_still_blocked(text):
    assert not validate_search_report(text, []).ok

def test_fallback_without_search_does_not_invent_empty_search():
    text = build_search_fallback([])
    assert '本轮搜索结果' not in text and '以上空结果' not in text
    assert validate_search_report(text, []).ok

def test_waiting_plan_followup_uses_task_not_model(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    from modagent import api, db
    from modagent.config import Config
    from modagent.orchestration.runtime import AgentCoreRuntime
    monkeypatch.setattr(db, 'DB_FILE', str(tmp_path / 'state.db')); db.init_db()
    monkeypatch.setattr(api, 'cfg', Config(agent_core_v2='on', game_slug='fixture'))
    monkeypatch.setattr(api, '_API_TOKEN', 'fixture-token')
    monkeypatch.setattr(api, '_chat_tasks', {})
    monkeypatch.setattr(api, 'agents', {})
    monkeypatch.setattr(api.Agent, 'chat_stream', lambda *a, **k: pytest.fail('No model/tools for this follow-up'))
    db.create_session('r11', 'test', 'fixture')
    spec = TaskSpec.create(session_id='r11', game_id='fixture', intent=AgentMode.BUILD_PLAN,
                           user_goal='为勾选项生成安装计划', targets=({'source':'nexus', 'mod_id':'1'},))
    run = AgentCoreRuntime(spec, feature_mode='on'); run.start()
    run.tool_started('get_installed', {}); run.tool_finished('get_installed', {}, '[]', True)
    run.wait_for_confirmation('核验结束')
    client = TestClient(api.app, headers={'X-ModAgent-Token':'fixture-token'})
    try:
        for message in ['?何意味', '我没看懂']:
            response = client.post('/chat/stream', json={'message':message,'session_id':'r11'})
            events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith('data: ')]
            text = ''.join(e.get('chunk','') for e in events)
            assert '等待确认' in text and '不恢复' in text
            assert '查看待确认清单' in text
            assert '本轮搜索结果' not in text
            assert not any('error' in e for e in events)
    finally:
        client.close()

def test_plan_without_targets_cannot_claim_ready(monkeypatch, tmp_path):
    from modagent import db
    from modagent.orchestration import store
    from modagent.orchestration.runtime import AgentCoreRuntime
    monkeypatch.setattr(db, 'DB_FILE', str(tmp_path / 'state.db')); db.init_db()
    spec = TaskSpec.create(session_id='empty', game_id='fixture', intent=AgentMode.BUILD_PLAN, user_goal='生成计划')
    run = AgentCoreRuntime(spec, feature_mode='on'); run.start()
    run.finalize_from_text('已生成计划', waiting_confirmation=True)
    task = store.get_task(spec.task_id)
    assert task['state'] == 'BLOCKED'
    assert '已生成计划' not in task['outcome']['summary']
