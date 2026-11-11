import json
import os
import re
import pytest

if not os.environ.get('MODAGENT_DATA_DIR'):
    raise RuntimeError('Isolated data directory required')
from modagent.report_validator import build_search_fallback, _search_ledger


def history(tool, content):
    return [{'role': 'assistant', 'tool_calls': [{'id': 'call', 'function': {'name': tool}}]},
            {'role': 'tool', 'tool_call_id': 'call', 'content': content}]


@pytest.mark.parametrize('content', ['{broken', 'null', '"PRIVATE"'])
def test_unreadable_tool_receipt_is_not_a_successful_search(content):
    ledger = _search_ledger(history('github_search', content))
    assert 'github' in ledger['failed'] and 'github' not in ledger['consulted']


def test_explicit_results_empty_is_reported_as_empty():
    ledger = _search_ledger(history('github_search', '{"results": []}'))
    assert ledger['empty'] == {'github'}


@pytest.mark.parametrize('language', ['en', 'zh-CN'])
@pytest.mark.parametrize('has_search', [True, False])
def test_fallback_language_preserves_source_states(language, has_search):
    records = history('mod_recommend', json.dumps({
        'sources_attempted': ['github', 'nexus'], 'sources_consulted': ['nexus'],
        'sources_empty': ['nexus'], 'sources_failed': {'github': 'PRIVATE'},
        'sources_skipped': {'workshop': {}},
    })) if has_search else []
    result = build_search_fallback(records, language=language)
    assert 'PRIVATE' not in result
    if language == 'en':
        assert not re.search(r'[\u4e00-\u9fff]', result)
        if has_search:
            assert 'Nexus: searched; no matching results' in result
            assert 'GitHub: search failed' in result
            assert 'Steam Workshop: not searched' in result
            assert 'connection test' in result
        else:
            assert 'No new search records' in result
    else:
        assert '本轮' in result
