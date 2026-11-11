"""Exercise both Agent reply loops with an offline, persistently wrong model."""
import json
import os
from types import SimpleNamespace as NS
import pytest

if not os.environ.get('MODAGENT_DATA_DIR'):
    raise RuntimeError('Isolated data directory required')
from modagent import agent as module
from modagent.config import Config


@pytest.mark.parametrize('streaming', [True, False])
@pytest.mark.parametrize('language', ['en', 'zh-CN'])
@pytest.mark.parametrize('with_candidates', [False, True])
def test_agent_uses_localized_fallback_after_failed_corrections(monkeypatch, streaming, language, with_candidates):
    monkeypatch.setattr(module, 'build_prompt', lambda cfg: 'Offline test')
    monkeypatch.setattr(module, 'build_tools_definitions', lambda tier: [
        {'type': 'function', 'function': {'name': 'github_search'}}])
    monkeypatch.setattr(module, 'ENABLE_REPORT_VALIDATION', True)
    monkeypatch.setattr(module, 'ENABLE_STATE_CHECK', False)
    monkeypatch.setattr(module, 'MAX_ROUNDS', 6)
    if with_candidates:
        # Presentation-composition fixture, not a source-discovery assertion.
        monkeypatch.setattr(module, 'recommendations_from_tool_evidence', lambda *a, **kw: {
            'items': [{'name': 'Fixture skin', 'content': 'Adds a cosmetic skin.', 'source': 'nexus',
                       'mod_id': 123, 'selection_key': 'nexus:123', 'detail_verified': True}],
        })
        monkeypatch.setattr(module.Agent, '_localize_recommendation_set', lambda self, data: data)
    calls = []
    responses = []
    wrong = 'Nexus was searched.' if language == 'en' else 'Nexus 已搜索。'

    class OfflineAgent(module.Agent):
        @property
        def client(self):
            return NS(chat=NS(completions=NS(create=self.complete)))

        def answer(self):
            responses.append(1)
            if len(responses) == 1:
                call = NS(index=0, id='search', function=NS(name='github_search', arguments='{"query":"skin"}'))
                return NS(content=None, tool_calls=[call])
            return NS(content=wrong, tool_calls=None)

        def complete(self, **kwargs):
            return NS(choices=[NS(message=self.answer())])

        def _stream(self, messages, tools):
            return [NS(choices=[NS(delta=self.answer())])]

        def _exec(self, name, args):
            calls.append(name)
            assert name == 'github_search'
            return json.dumps({'error': 'PRIVATE network failure'})

    instance = OfflineAgent(Config(language=language, game_slug='fixture', game_name='Fixture'))
    if streaming:
        events = [json.loads(value) for value in instance.chat_stream('Search for skin mods')]
        text = ''.join(event.get('chunk', '') for event in events)
        assert any(event.get('done') for event in events)
    else:
        text = instance.chat('Search for skin mods')
    assert calls == ['github_search'] and len(responses) == 4
    assert wrong not in text and 'PRIVATE' not in text
    assert ('GitHub: search failed' if language == 'en' else 'GitHub：查询失败') in text
    if with_candidates and streaming:
        assert 'Fixture skin' in text
        assert text.count('GitHub: search failed' if language == 'en' else 'GitHub：查询失败') == 1
        if language == 'en':
            assert 'Found 1 candidates' in text and '找到了' not in text
    assert instance.history[-1]['content'] == text
