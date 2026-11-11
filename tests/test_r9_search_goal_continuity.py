import json
from types import SimpleNamespace
import pytest

from modagent.orchestration.router import route_message
from modagent.orchestration.models import AgentMode

GOAL = '推荐能在游戏内显示更多信息的 UI Mod，不要贴图、皮肤，只推荐两项'
HISTORY = [{'role': 'user', 'content': GOAL}, {'role': 'assistant', 'content': '已取得候选。'}]


@pytest.mark.parametrize('message', ['继续搜索', '再找找', 'search again', 'keep searching'])
def test_explicit_search_continuation_keeps_original_goal(message):
    route = route_message(message, history=HISTORY)
    assert route.intent in {AgentMode.SEARCH_EXACT, AgentMode.RECOMMEND_BROAD}
    assert GOAL in route.search_goal
    assert not route.install_authorized and not route.destructive_authorized


@pytest.mark.parametrize('message', ['继续', '？', '为什么没有找到', '不搜了'])
def test_plain_followup_is_not_search_permission(message):
    route = route_message(message, history=HISTORY)
    assert route.intent not in {AgentMode.SEARCH_EXACT, AgentMode.RECOMMEND_BROAD}
    assert not route.install_authorized


def test_continuation_cannot_reach_past_cancellation():
    route = route_message('继续搜索', history=HISTORY + [{'role': 'user', 'content': '不搜了'}])
    assert GOAL not in route.search_goal


def test_new_explicit_goal_does_not_inherit_old_constraints():
    route = route_message('推荐服装外观 mod', history=HISTORY)
    assert GOAL not in route.search_goal


def test_repeated_search_continuations_keep_goal_but_assistant_cannot_supply_it():
    route = route_message('继续搜索', history=HISTORY + [{'role': 'user', 'content': '再找找'}])
    assert GOAL in route.search_goal
    route = route_message('继续搜索', history=[{'role': 'assistant', 'content': GOAL}])
    assert route.intent == AgentMode.CHAT_EXPLAIN


@pytest.mark.parametrize('message', ['你刚才做了什么？', '为什么没找到？', '先停止搜索'])
def test_status_or_stop_breaks_search_continuation_chain(message):
    route = route_message('继续搜索', history=HISTORY + [{'role': 'user', 'content': message}])
    assert route.intent == AgentMode.CHAT_EXPLAIN


@pytest.mark.parametrize('message', [GOAL, '只要单人用的', '继续搜索', '只要单人用的”，再“继续搜索'])
@pytest.mark.parametrize('same_game', [True, False])
def test_actual_api_uses_same_goal_for_search_and_candidate_gate(monkeypatch, tmp_path, message, same_game):
    from fastapi.testclient import TestClient
    from modagent import api, db, agent as agent_module
    from modagent.agent import Agent
    from modagent.config import Config
    monkeypatch.setattr(db, 'DB_FILE', str(tmp_path / 'state.db'))
    db.init_db()
    monkeypatch.setattr(api, 'cfg', Config(agent_core_v2='on', game_name='Fixture Game', game_slug='fixture'))
    monkeypatch.setattr(api, '_API_TOKEN', 'fixture-token')
    monkeypatch.setattr(api, '_chat_tasks', {})
    monkeypatch.setattr(api, 'agents', {})
    monkeypatch.setattr(agent_module, 'refresh_local_inventory', lambda *a: None)
    monkeypatch.setattr(agent_module, 'ENABLE_REPORT_VALIDATION', False)
    monkeypatch.setattr(agent_module, 'ENABLE_STATE_CHECK', False)
    calls = []
    def execute(name, args, cfg):
        calls.append((name, args))
        assert name == 'mod_recommend'
        return json.dumps({'query': args['query'], 'sources_consulted': ['nexus'], 'recommendations': [
            {'mod_id': 1, 'name': 'Overlay', 'summary': 'An evidence overlay with timers.', '_detail_verified': True},
            {'mod_id': 2, 'name': 'Theme', 'summary': 'UI textures only.', '_detail_verified': True}]})
    monkeypatch.setattr(agent_module, 'execute', execute)
    class FixtureAgent(Agent):
        def _stream(self, messages, tools):
            return [SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content='收到。', tool_calls=None))])]
        def _localize_recommendation_set(self, payload):
            return payload
    monkeypatch.setattr(api, 'Agent', FixtureAgent)
    db.create_session('r9', 'fixture', 'fixture' if same_game else 'different-game')
    db.update_session_messages('r9', HISTORY)
    client = TestClient(api.app, headers={'X-ModAgent-Token': 'fixture-token'})
    try:
        response = client.post('/chat/stream', json={'message': message, 'session_id': 'r9'})
    finally:
        client.close()
    assert response.status_code == 200
    events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith('data: ')]
    tables = [e['recommendations'] for e in events if 'recommendations' in e]
    if not same_game and message != GOAL:
        assert not calls and not tables
        return
    assert len(calls) == 1 and len(tables) == 1, [(e.get('chunk'), e.get('error')) for e in events if 'chunk' in e or 'error' in e]
    assert GOAL in calls[0][1]['query']
    assert ' '.join(tables[0]['user_goal'].split()) == calls[0][1]['query']
    assert [row['mod_id'] for row in tables[0]['items']] == [1]
    assert tables[0]['requirements']['excluded'] == ['appearance']
