"""Source discovery must recover after connectivity changes and stay root-scoped."""
import os
import pytest

if not os.environ.get('MODAGENT_DATA_DIR'):
    raise RuntimeError('Isolated data directory required')
from modagent import sources
from modagent.sources import thunderstore, gamebanana, steam_workshop
_real_find_game = gamebanana.find_game


@pytest.fixture(autouse=True)
def isolated_discovery(monkeypatch):
    sources._SRC_CACHE.clear()
    gamebanana._GAME_CACHE.clear()
    monkeypatch.setattr(gamebanana, 'find_game', lambda name: None)
    monkeypatch.setattr(thunderstore, 'find_community', lambda name: 'fixture')
    monkeypatch.setattr(steam_workshop, 'resolve_appid', lambda root: None)
    yield
    sources._SRC_CACHE.clear()


def test_failed_probe_is_retried_after_network_recovers(monkeypatch):
    attempts = []
    def probe(name):
        attempts.append(name)
        if len(attempts) == 1:
            raise OSError('offline')
        return 'fixture'
    monkeypatch.setattr(thunderstore, 'find_community', probe)
    first = sources.available_sources('Fixture', 'fixture', 'A:/Game')
    assert first['source_status']['thunderstore']['status'] == 'search_failed'
    second = sources.available_sources('Fixture', 'fixture', 'A:/Game')
    assert second['thunderstore'] == 'fixture'
    third = sources.available_sources('Fixture', 'fixture', 'A:/Game')
    assert third['thunderstore'] == 'fixture' and len(attempts) == 2


def test_local_workshop_identity_does_not_leak_between_installations(monkeypatch, tmp_path):
    root_a, root_b = str(tmp_path / 'A'), str(tmp_path / 'B')
    monkeypatch.setattr(steam_workshop, 'resolve_appid', lambda root: 100 if root == root_a else None)
    first = sources.available_sources('Fixture', 'fixture', root_a)
    second = sources.available_sources('Fixture', 'fixture', root_b)
    assert first['workshop'] == 100
    assert second['workshop'] is None


def test_gamebanana_transport_failure_is_not_a_missing_game(monkeypatch):
    monkeypatch.setattr(gamebanana, 'find_game', _real_find_game)
    calls = []
    def response(url):
        calls.append(url)
        if len(calls) == 1:
            raise OSError('PRIVATE proxy credential')
        return {'_aRecords': [{'_sName': 'Fixture', '_idRow': 123}]}
    monkeypatch.setattr(gamebanana, '_http_json', response)
    first = sources.available_sources('Fixture', 'fixture', 'A:/Game')
    assert first['source_status']['gamebanana']['status'] == 'search_failed'
    assert 'PRIVATE' not in str(first)
    second = sources.available_sources('Fixture', 'fixture', 'A:/Game')
    assert second['gamebanana'] == 123 and len(calls) == 2


def test_direct_gamebanana_tool_reports_discovery_failure(monkeypatch):
    import json
    from modagent import config, tools
    monkeypatch.setattr(gamebanana, 'find_game', _real_find_game)
    def fail(url):
        raise OSError('PRIVATE network detail')
    monkeypatch.setattr(gamebanana, '_http_json', fail)
    result = json.loads(tools.execute('gamebanana_search', {'query': 'skin'}, config.Config(game_name='Fixture', game_slug='fixture')))
    assert result['error_code'] == 'GAMEBANANA_DISCOVERY_FAILED'
    assert 'results' not in result and 'PRIVATE' not in str(result)
