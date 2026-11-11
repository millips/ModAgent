import pytest
from modagent.orchestration.router import route_message
from modagent.orchestration.models import AgentMode
from modagent.recommendation_fit import assess_goal, compile_goal

GOAL = '推荐能在游戏内显示更多信息的 UI Mod，不要贴图、皮肤，只推荐两项'

@pytest.mark.parametrize('text', [GOAL, '推荐 UI mod，不要皮肤，只推荐两项',
    'Recommend UI mods, no skins, recommend two options'])
def test_exclusions_are_not_cancellation(text):
    r = route_message(text)
    assert r.intent in {AgentMode.SEARCH_EXACT, AgentMode.RECOMMEND_BROAD}
    assert not r.install_authorized

@pytest.mark.parametrize('text', ['不要推荐，先停下', '先别搜索', '停止搜索', '别再找了',
    'do not search', 'stop searching', 'cancel search'])
def test_real_stop_still_stops(text):
    assert route_message(text).intent == AgentMode.CHAT_EXPLAIN

@pytest.mark.parametrize('text', ['只要单人用的”，再“继续搜索', '只要单人用的，再继续搜索',
    '继续搜索，只要单人用的', '只要单人用的', 'single player only, keep searching'])
def test_compound_refinement_keeps_goal(text):
    r = route_message(text, history=[{'role':'user','content':GOAL}])
    assert GOAL in r.search_goal
    assert not r.install_authorized and not r.destructive_authorized

@pytest.mark.parametrize('text,count', [('只推荐两项',2),('数量为两项',2),('推荐三个',3),
    ('推荐 2 项',2),('推荐十二款',12),('recommend two options',2)])
def test_quantities(text,count):
    assert compile_goal('UI mod，'+text).requested_count == count
    assert compile_goal('UI mod，'+text).exhaustive

@pytest.mark.parametrize('description', [
    'Alter Other Stats (temporary): Armor, Carry Capacity, Crit Chance and Damage, Health, etc. A user interface that provides gameplay, cheat and utility features to be executed by a press of a button.',
    'Edit stats and health from a UI panel.', '修改角色属性和生命值的界面。'])
def test_editing_stats_is_not_information_display(description):
    assert assess_goal({'description':description}, GOAL)['status'] != 'matched'

@pytest.mark.parametrize('description', ['Displays health and armor stats in the HUD.',
    'An evidence overlay with timers.', '在界面中显示角色属性和生命值。'])
def test_display_evidence_still_reachable(description):
    assert assess_goal({'description':description}, GOAL)['status'] == 'matched'

def test_search_terminal_counts_matching_results_not_calls(monkeypatch, tmp_path):
    from modagent import db
    from modagent.orchestration import AgentCoreRuntime, TaskSpec
    from modagent.orchestration import store
    monkeypatch.setattr(db, 'DB_FILE', str(tmp_path / 'state.db'))
    db.init_db()
    spec = TaskSpec.create(session_id='test', game_id='fixture', intent=AgentMode.RECOMMEND_BROAD, user_goal=GOAL)
    run = AgentCoreRuntime(spec, feature_mode='on'); run.start()
    run.tool_started('mod_recommend', {})
    run.tool_finished('mod_recommend', {}, '{}', True)
    run.tool_blocked('mod_recommend', '搜索查询次数已达本轮上限')
    run.record_search_result({'items':[{'goal_fit':{'status':'unconfirmed'}}], 'requirements':{'requested_count':2}})
    run.finalize_from_text('模型说已经完成')
    task = store.get_task(spec.task_id)
    assert task['outcome']['status'] == 'partial'
    assert '0 个具有需求匹配证据' in task['outcome']['summary']
    assert '2 项' in task['outcome']['summary']
    assert task['outcome']['not_completed']

def test_process_question_uses_persisted_events_not_model(monkeypatch, tmp_path):
    import json
    from fastapi.testclient import TestClient
    from modagent import api, db
    from modagent.config import Config
    from modagent.orchestration import AgentCoreRuntime, TaskSpec
    monkeypatch.setattr(db, 'DB_FILE', str(tmp_path / 'state.db')); db.init_db()
    monkeypatch.setattr(api, 'cfg', Config(agent_core_v2='on', game_slug='fixture'))
    monkeypatch.setattr(api, '_API_TOKEN', 'fixture-token')
    monkeypatch.setattr(api, '_chat_tasks', {})
    monkeypatch.setattr(api, 'agents', {})
    def forbidden(*args, **kwargs):
        raise AssertionError('Status question must not call a model or tools')
    monkeypatch.setattr(api.Agent, 'chat_stream', forbidden)
    db.create_session('r10', 'test', 'fixture')
    spec = TaskSpec.create(session_id='r10', game_id='fixture', intent=AgentMode.SEARCH_EXACT, user_goal=GOAL)
    previous = AgentCoreRuntime(spec, feature_mode='on'); previous.start()
    previous.tool_started('mod_recommend', {})
    previous.cancel('用户停止')
    client = TestClient(api.app, headers={'X-ModAgent-Token':'fixture-token'})
    try:
        response = client.post('/chat/stream', json={'message':'刚才发生了什么？','session_id':'r10'})
    finally:
        client.close()
    events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith('data: ')]
    text = ''.join(e.get('chunk','') for e in events)
    assert '启动了 1 个搜索步骤' in text
    assert '不能据此保证所有在途操作都已退出' in text
    assert '不恢复搜索' in text
    assert not any('error' in e for e in events)
