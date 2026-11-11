"""Malformed search envelopes are failures, not evidence of zero matches."""
import os
import pytest

if not os.environ.get('MODAGENT_DATA_DIR'):
    raise RuntimeError('Isolated data directory required')
from modagent.sources import github, gamebanana


@pytest.mark.parametrize('adapter', ['github', 'gamebanana', 'discovery'])
@pytest.mark.parametrize('payload', [None, [], {}, {'message': 'PRIVATE gateway'}, 'PRIVATE html', 0])
def test_missing_record_list_is_not_empty_success(monkeypatch, adapter, payload):
    gamebanana._GAME_CACHE.clear()
    module = github if adapter == 'github' else gamebanana
    monkeypatch.setattr(module, '_http_json', lambda *a, **kw: payload)
    with pytest.raises(RuntimeError) as caught:
        if adapter == 'github':
            github.search('skin', 'Fixture')
        elif adapter == 'gamebanana':
            gamebanana.search(123, 'skin')
        else:
            gamebanana.find_game('Fixture')
    assert 'PRIVATE' not in str(caught.value)


@pytest.mark.parametrize('adapter', ['github', 'gamebanana', 'discovery'])
@pytest.mark.parametrize('records', [None, {}, '', [None], [1]])
def test_invalid_record_list_is_not_empty_success(monkeypatch, adapter, records):
    field = 'items' if adapter == 'github' else '_aRecords'
    test_missing_record_list_is_not_empty_success(monkeypatch, adapter, {field: records})


@pytest.mark.parametrize('adapter', ['github', 'gamebanana', 'discovery'])
def test_explicit_empty_list_is_valid(monkeypatch, adapter):
    module = github if adapter == 'github' else gamebanana
    field = 'items' if adapter == 'github' else '_aRecords'
    gamebanana._GAME_CACHE.clear()
    monkeypatch.setattr(module, '_http_json', lambda *a, **kw: {field: []})
    if adapter == 'github':
        assert github.search('skin', 'Fixture') == []
    elif adapter == 'gamebanana':
        assert gamebanana.search(123, 'skin') == []
    else:
        assert gamebanana.find_game('Fixture') is None


@pytest.mark.parametrize('failed_source', ['github', 'gamebanana'])
def test_aggregate_separates_failed_source_from_valid_empty_and_recovers(monkeypatch, failed_source):
    from modagent import sources, tools, config
    monkeypatch.setattr(sources, 'available_sources', lambda *a: {'gamebanana': 123})
    state = {'bad': True}
    monkeypatch.setattr(github, '_http_json', lambda *a, **kw:
                        {} if state['bad'] and failed_source == 'github' else {'items': []})
    monkeypatch.setattr(gamebanana, '_http_json', lambda *a, **kw:
                        {} if state['bad'] and failed_source == 'gamebanana' else {'_aRecords': []})
    cfg = config.Config(game_name='Fixture', game_slug='fixture')
    result = tools._recommend('skin', cfg)
    other = 'github' if failed_source == 'gamebanana' else 'gamebanana'
    assert failed_source in result['sources_failed']
    assert failed_source not in result['sources_empty']
    assert failed_source not in result['sources_consulted']
    assert result['sources_empty'] == [other]
    state['bad'] = False
    recovered = tools._recommend('skin', cfg)
    assert recovered['sources_failed'] == {}
    assert set(recovered['sources_empty']) == {'github', 'gamebanana'}
