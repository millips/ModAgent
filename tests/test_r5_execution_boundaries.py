import json
import threading
import time
import zipfile
import pytest

from modagent import agent as agent_module, installer, task_control
from modagent.agent import Agent
from modagent.config import Config
from modagent.sources.github import _filter_game_mod_results
from modagent.recommendation_ui import normalize_recommendations


def test_timeout_reaches_running_worker(monkeypatch):
    stopped = threading.Event()
    wrote = []
    def slow_tool(*args):
        try:
            for _ in range(200):
                task_control.raise_if_cancelled()
                time.sleep(.005)
            wrote.append(True)
            return '{}'
        finally:
            stopped.set()
    monkeypatch.setattr(agent_module, 'execute', slow_tool)
    monkeypatch.setattr(agent_module, 'TOOL_TIMEOUT_S', .03)
    result = json.loads(Agent(Config())._exec('get_installed', {}))
    assert result['status'] == 'interrupted'
    assert stopped.wait(1)
    assert not wrote


def test_cancellation_check_failure_is_closed():
    def broken():
        raise RuntimeError('authority unavailable')
    with task_control.bind(broken):
        with pytest.raises(task_control.TaskCancelled):
            task_control.raise_if_cancelled()


def test_cancelled_queued_writer_never_enters(tmp_path):
    entered = threading.Event()
    cancelled = threading.Event()
    did_write = []
    def queued():
        with task_control.bind(cancelled.is_set):
            entered.set()
            try:
                with task_control.game_write_scope(str(tmp_path)):
                    did_write.append(True)
            except task_control.TaskCancelled:
                pass
    with task_control.game_write_scope(str(tmp_path)):
        worker = threading.Thread(target=queued)
        worker.start()
        assert entered.wait(1)
        cancelled.set()
        worker.join(1)
    assert not worker.is_alive()
    assert not did_write


def test_cancel_mid_install_restores_originals(monkeypatch, tmp_path):
    game = tmp_path / 'game'
    game.mkdir()
    source = tmp_path / 'source'
    source.mkdir()
    monkeypatch.setattr(installer, 'BACKUPS_DIR', str(tmp_path / 'backups'))
    operations = []
    for name in ('a.txt', 'b.txt'):
        (game / name).write_text('original-' + name)
        (source / name).write_text('new-' + name)
        operations.append({'src': str(source / name), 'dest': str(game / name)})
    cancelled = threading.Event()
    replace = installer.os.replace
    def cancel_after_first_commit(src, dest):
        replace(src, dest)
        if str(dest) == str(game / 'a.txt') and 'stage' in str(src):
            cancelled.set()
    monkeypatch.setattr(installer.os, 'replace', cancel_after_first_commit)
    with task_control.bind(cancelled.is_set):
        with pytest.raises(task_control.TaskCancelled):
            installer._commit_files_transactionally(operations, str(game), 'fixture')
    assert (game / 'a.txt').read_text() == 'original-a.txt'
    assert (game / 'b.txt').read_text() == 'original-b.txt'
    assert not list(game.glob('.modagent-transaction-*'))


def test_owner_name_is_not_current_game_evidence():
    rows = [{'name': 'Unbended', 'full_name': 'Demonologist/Unbended',
             'summary': 'A Zanzarah mod plugin.'}]
    assert _filter_game_mod_results(rows, 'mod', 'Demonologist') == []


def test_framework_impersonator_is_not_official():
    rows = [{'name': 'BepInEx', 'full_name': 'unrelated/BepInEx', 'summary': 'plugin loader'}]
    assert _filter_game_mod_results(rows, 'BepInEx', 'Demonologist') == []


def test_exact_framework_search_does_not_recommend_dependent_mods():
    rows = [
        {'name': 'SMAPI', 'full_name': 'Pathoschild/SMAPI', 'summary': 'The modding API for Stardew Valley.'},
        {'name': 'UI', 'full_name': 'someone/UI', 'summary': 'A SMAPI mod for Stardew Valley.'},
    ]
    found = _filter_game_mod_results(rows, 'SMAPI', 'Stardew Valley')
    assert [row['full_name'] for row in found] == ['Pathoschild/SMAPI']


@pytest.mark.parametrize('row', [
    {'name': 'Training UI', 'summary': 'Not a real downloadable Mod.'},
    {'name': 'Training UI', 'summary': '这不是可下载的模组。'},
    {'name': 'Training UI', 'candidate_valid': False},
    {'name': 'Training UI', 'url': 'https://www.nexusmods.com/othergame/mods/42'},
])
def test_all_candidate_paths_reject_invalid_evidence(row):
    result = normalize_recommendations({'recommendations': [row]}, game_slug='fixturegame')
    assert result['items'] == []
    assert len(result['rejected_candidates']) == 1


def test_unverified_is_not_invalid():
    result = normalize_recommendations({'recommendations': [
        {'mod_id': 42, 'name': 'Training UI', 'summary': 'Adds a clearer UI.'}]})
    assert len(result['items']) == 1
    assert not result['items'][0]['detail_verified']


@pytest.mark.parametrize('members', [
    {'BepInExPack/BepInEx/core/BepInEx.dll': b'loader', 'BepInExPack/winhttp.dll': b'proxy', 'manifest.json': b'{}'},
    {'Minimap.dll': b'plugin', 'README.md': b'description'},
    {'plugins/Helper.dll': b'plugin', 'config/Helper.cfg': b'settings'},
])
def test_bepinex_conflict_preview_matches_actual_placement(monkeypatch, tmp_path, members):
    archive = tmp_path / 'ts_Fixture_Package_1.0.0.zip'
    with zipfile.ZipFile(archive, 'w') as bundle:
        for name, content in members.items():
            bundle.writestr(name, content)
    game = tmp_path / 'game'
    game.mkdir()
    monkeypatch.setattr(installer, 'BACKUPS_DIR', str(tmp_path / 'backups'))
    monkeypatch.setattr(installer, '_get_installed_files_map', lambda slug: {})
    preview = installer.conflict_check(str(archive), str(game), 'repo')
    assert preview['safe_to_install']
    assert not list(game.iterdir()), 'preview must not write game files'
    result = installer.install_mod(str(archive), str(game), 'repo')
    actual = {entry['dest'] for entry in result['installed']}
    assert set(preview['planned_files']) == actual
    monkeypatch.setattr(installer, '_get_installed_files_map', lambda slug: {path: 'Existing Mod' for path in actual})
    conflict = installer.conflict_check(str(archive), str(game), 'repo')
    assert not conflict['safe_to_install']
    assert len(conflict['conflicts']) == len(actual)
