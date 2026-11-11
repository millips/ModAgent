import itertools
import json
import os
import pytest
if not os.environ.get('MODAGENT_DATA_DIR'):
    raise RuntimeError('Isolated data directory required')
from modagent.report_validator import _search_ledger, build_search_fallback


@pytest.mark.parametrize('aggregate', [False, True])
@pytest.mark.parametrize('order', list(itertools.permutations(['found', 'empty', 'failed'])))
def test_found_results_survive_empty_and_failed_queries_in_any_order(aggregate, order):
    records = []
    for index, status in enumerate(order):
        tool = 'mod_recommend' if aggregate else 'github_search'
        if aggregate:
            payload = {'sources_attempted': ['github'],
                       'sources_consulted': [] if status == 'failed' else ['github'],
                       'sources_empty': ['github'] if status == 'empty' else [],
                       'sources_failed': {'github': 'PRIVATE'} if status == 'failed' else {}}
        else:
            payload = {'error': 'PRIVATE'} if status == 'failed' else {'results': [{'name': 'Fixture'}] if status == 'found' else []}
        records.extend([{'role': 'assistant', 'tool_calls': [{'id': str(index), 'function': {'name': tool}}]},
                        {'role': 'tool', 'tool_call_id': str(index), 'content': json.dumps(payload)}])
    ledger = _search_ledger(records)
    assert ledger['consulted'] == {'github'} and ledger['failed'] == {'github'}
    assert 'github' not in ledger['empty']
    for language in ['en', 'zh-CN']:
        report = build_search_fallback(records, language=language)
        assert 'PRIVATE' not in report
        if language == 'en':
            assert 'some queries failed' in report
            assert 'GitHub: searched; no matching results' not in report
        else:
            assert '部分查询失败' in report
            assert 'GitHub：已查询，本次未搜到' not in report
