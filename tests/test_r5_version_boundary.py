import json
from types import SimpleNamespace

import pytest

from modagent import agent as agent_module, downloader, tools
from modagent.agent import Agent
from modagent.config import Config
from modagent.sources import thunderstore


def test_thunderstore_version_change_stops_before_download(monkeypatch):
    monkeypatch.setattr(thunderstore, '_http_json', lambda url: {
        'latest': {'version_number': '2.0.0', 'download_url': 'https://example.invalid/new.zip'}})
    downloads = []
    monkeypatch.setattr(downloader, 'download_file', lambda *a, **k: downloads.append(a))
    with pytest.raises(downloader.DownloadFailure) as captured:
        thunderstore.download('https://thunderstore.io/c/repo/p/dig/Minimap/', 'repo', expected_version='1.1.3')
    assert captured.value.failure_kind == 'selected_version_changed'
    assert not downloads


def test_selected_version_overrides_model_download_argument(monkeypatch):
    url = 'https://thunderstore.io/c/repo/p/dig/Minimap/'
    instance = Agent(Config())
    instance._selection_action = 'confirm'
    instance._selection_allowed_source_urls = {url}
    instance._selection_confirm_rows = instance._normalize_selection_rows([
        {'source': 'thunderstore', 'source_id': 'dig-Minimap', 'source_url': url, 'version': '1.1.3'}])
    calls = []
    def fake_execute(name, args, cfg):
        calls.append(args)
        return json.dumps({'error': 'fixture_no_network'})
    monkeypatch.setattr(agent_module, 'execute', fake_execute)
    instance._exec('download_from_url', {'url': url, 'expected_version': '2.0.0'})
    assert calls[0]['expected_version'] == '1.1.3'


def test_installed_different_version_not_reported_as_complete(monkeypatch, tmp_path):
    monkeypatch.setattr(tools, '_refresh_local_inventory', lambda cfg: {})
    monkeypatch.setattr(tools, '_installed_duplicate', lambda *a: SimpleNamespace(version='2.0.0'))
    cfg = Config(game_root=str(tmp_path), game_slug='repo')
    result = json.loads(tools.execute('download_from_url', {
        'url': 'https://thunderstore.io/c/repo/p/dig/Minimap/', 'expected_version': '1.1.3'}, cfg))
    assert result['error'] == 'installed_version_differs'
    assert not result.get('already_installed')


def test_github_changed_tag_stops_before_download(monkeypatch, tmp_path):
    monkeypatch.setattr(tools, '_refresh_local_inventory', lambda cfg: {})
    monkeypatch.setattr(tools, '_installed_duplicate', lambda *a: None)
    monkeypatch.setattr(tools, '_resolve_github_release_url', lambda url: {
        'url': 'https://github.com/fixture/tool/releases/download/v2/tool.zip', 'version': 'v2'})
    cfg = Config(game_root=str(tmp_path), game_slug='fixture')
    result = json.loads(tools.execute('download_from_url', {
        'url': 'https://github.com/fixture/tool', 'expected_version': 'v1'}, cfg))
    assert result['error'] == 'selected_version_changed'
    assert result['download_skipped']
