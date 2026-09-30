"""Real filesystem/DB regressions. All content is synthetic and isolated."""
import json
import threading
import io
import os
import subprocess
import sys
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from modagent import db, installer, tools, task_control, downloader, snapshot
from modagent.config import Config
from modagent.orchestration.outcomes import ToolOutcome


@pytest.fixture
def env(monkeypatch, tmp_path):
    game = tmp_path / 'game'
    game.mkdir()
    monkeypatch.setattr(installer, 'BACKUPS_DIR', str(tmp_path / 'backups'))
    monkeypatch.setattr(db, 'DB_FILE', str(tmp_path / 'state.db'))
    db.init_db()
    # Only the snapshot transport is replaced in these focused failure tests.
    monkeypatch.setattr(tools.snapshot, 'snapshot_create', lambda *a, **kw: 'fixture-snapshot')
    monkeypatch.setattr(tools.user_config, 'uninstall_mod_configs',
                        lambda *a: {'complete': True, 'changed': [], 'failed': []})
    cfg = Config(game_root=str(game), game_slug='fixture')
    return game, cfg


def register(cfg, paths, mid='fixture'):
    db.add_mod(db.InstalledMod(id=mid, name=mid, version='1', snapshot_id='',
        files_installed=json.dumps([str(p) for p in paths]), game_slug=cfg.game_slug))


def uninstall(cfg, mid='fixture'):
    return json.loads(tools.execute('mod_uninstall', {'mod_id': mid, 'confirmed': True}, cfg))


def test_missing_mod_restores_original_instead_of_deleting_backup(env):
    game, cfg = env
    path = game / 'original.txt'
    path.write_bytes(b'original')
    installer._backup_file(str(path), str(game), cfg.game_slug)
    path.unlink()
    result = installer.uninstall_mod('fixture', str(game), [str(path)], cfg.game_slug)
    assert path.read_bytes() == b'original'
    assert result['restored_original'] == [str(path)]


def test_disabled_mod_is_actually_removed(env):
    game, cfg = env
    path = game / 'plugin.dll'
    path.write_bytes(b'fixture')
    register(cfg, [path])
    installer.disable_mod([str(path)], str(game))
    result = uninstall(cfg)
    assert not Path(str(path) + '.disabled').exists()
    assert not path.exists()
    assert db.get_mod('fixture', cfg.game_slug) is None
    assert result['status'] == 'completed'


def test_locked_file_keeps_management_record(monkeypatch, env):
    game, cfg = env
    path = game / 'locked.dll'
    path.write_bytes(b'fixture')
    register(cfg, [path])
    real_remove = installer.os.remove
    def locked(target, *args, **kwargs):
        if str(target) == str(path):
            raise PermissionError('fixture file locked')
        return real_remove(target, *args, **kwargs)
    monkeypatch.setattr(installer.os, 'remove', locked)
    result = uninstall(cfg)
    assert db.get_mod('fixture', cfg.game_slug) is not None
    assert path.read_bytes() == b'fixture'
    assert not ToolOutcome.from_legacy(result, legacy_ok=True).succeeded
    assert result['record_retained'] is True


def test_restore_failure_preserves_backup_and_record(monkeypatch, env):
    game, cfg = env
    path = game / 'original.txt'
    path.write_bytes(b'original')
    installer._backup_file(str(path), str(game), cfg.game_slug)
    path.write_bytes(b'modded')
    register(cfg, [path])
    real_copy = installer.shutil.copy2
    def fail_restore(src, dst, *args, **kwargs):
        if str(src).startswith(installer.BACKUPS_DIR):
            raise OSError('fixture restore failure')
        return real_copy(src, dst, *args, **kwargs)
    monkeypatch.setattr(installer.shutil, 'copy2', fail_restore)
    result = uninstall(cfg)
    assert db.get_mod('fixture', cfg.game_slug) is not None
    assert installer._backup_lookup(str(path), str(game), cfg.game_slug)
    assert not ToolOutcome.from_legacy(result, legacy_ok=True).succeeded


def test_external_cleanup_failure_retry_does_not_delete_restored_original(monkeypatch, env):
    game, cfg = env
    path = game / 'original.txt'
    path.write_bytes(b'original')
    installer._backup_file(str(path), str(game), cfg.game_slug)
    path.write_bytes(b'modded')
    register(cfg, [path])
    monkeypatch.setattr(tools.user_config, 'uninstall_mod_configs',
        lambda *a: {'complete': False, 'failed': [{'error': 'fixture locked config'}]})
    first = uninstall(cfg)
    assert path.read_bytes() == b'original'
    assert first['record_retained'] is True
    assert db.get_mod('fixture', cfg.game_slug) is not None
    monkeypatch.setattr(tools.user_config, 'uninstall_mod_configs',
        lambda *a: {'complete': True, 'changed': [], 'failed': []})
    second = uninstall(cfg)
    assert second['status'] == 'completed'
    assert path.read_bytes() == b'original'
    assert db.get_mod('fixture', cfg.game_slug) is None


def test_partial_uninstall_can_be_rechecked_in_new_process(monkeypatch, env):
    game, cfg = env
    (game / 'FixtureGame.exe').write_bytes(b'never launched')
    (game / 'FixtureGame_Data').mkdir()
    (game / 'UnityPlayer.dll').write_bytes(b'synthetic marker')
    path = game / 'original.txt'
    path.write_bytes(b'original')
    installer._backup_file(str(path), str(game), cfg.game_slug)
    path.write_bytes(b'modded')
    register(cfg, [path])
    monkeypatch.setattr(tools.user_config, 'uninstall_mod_configs',
        lambda *a: {'complete': False, 'failed': [{'error': 'fixture locked config'}]})
    assert uninstall(cfg)['record_retained'] is True
    # Explicit user-equivalent retry in a new process, not automatic startup.
    code = ('import sys,json; from modagent import tools; from modagent.config import Config; '
            'cfg=Config(game_root=sys.argv[1],game_slug="fixture"); '
            'p=json.loads(tools.execute("mod_uninstall",{"mod_id":"fixture"},cfg)); '
            'assert p["requires_confirmation"]; '
            'print(tools.execute("mod_uninstall",{"mod_id":"fixture","confirmed":True},cfg))')
    process = subprocess.run([sys.executable, '-c', code, str(game)], capture_output=True,
        text=True, encoding='utf-8', timeout=15, check=True,
        env={**os.environ, 'MODAGENT_DATA_DIR': str(game.parent), 'PYTHONIOENCODING': 'utf-8'})
    assert json.loads(process.stdout)['status'] == 'completed'
    assert path.read_bytes() == b'original'
    assert db.get_mod('fixture', cfg.game_slug) is None


def test_cancel_between_files_keeps_remaining_files_and_record(monkeypatch, env):
    game, cfg = env
    paths = [game / name for name in ('a.dll', 'b.dll')]
    for path in paths:
        path.write_bytes(b'fixture')
    register(cfg, paths)
    cancelled = threading.Event()
    real_remove = installer.os.remove
    def stop_after_first(target, *a, **kw):
        result = real_remove(target, *a, **kw)
        if str(target) == str(paths[0]):
            cancelled.set()
        return result
    monkeypatch.setattr(installer.os, 'remove', stop_after_first)
    with task_control.bind(cancelled.is_set):
        result = uninstall(cfg)
    assert not paths[0].exists()
    assert paths[1].exists()
    assert db.get_mod('fixture', cfg.game_slug) is not None
    assert result['status'] == 'cancelled'


def test_unsafe_ledger_entry_retains_record_and_outside_file(env):
    game, cfg = env
    outside = game.parent / 'not-a-game-file.txt'
    outside.write_bytes(b'precious')
    register(cfg, [outside])
    result = uninstall(cfg)
    assert outside.read_bytes() == b'precious'
    assert db.get_mod('fixture', cfg.game_slug) is not None
    assert not ToolOutcome.from_legacy(result, legacy_ok=True).succeeded


def test_workshop_failure_keeps_subscription_record(monkeypatch, env):
    from modagent.sources import steam_workshop
    _, cfg = env
    register(cfg, [], mid='ws_123')
    monkeypatch.setattr(steam_workshop, 'resolve_appid', lambda root: '456')
    async def failed(*a):
        return {'ok': False}
    monkeypatch.setattr(steam_workshop, 'unsubscribe', failed)
    result = uninstall(cfg, 'ws_123')
    assert result['record_retained'] is True
    assert db.get_mod('ws_123', cfg.game_slug) is not None
    assert not ToolOutcome.from_legacy(result, legacy_ok=True).succeeded


def test_shared_files_survive_uninstall(env):
    game, cfg = env
    shared = game / 'shared.dll'
    shared.write_bytes(b'needed-by-another-mod')
    register(cfg, [shared])
    register(cfg, [shared], mid='other')
    result = uninstall(cfg)
    assert result['status'] == 'completed'
    assert result['kept_shared'] == 1
    assert shared.read_bytes() == b'needed-by-another-mod'
    assert db.get_mod('other', cfg.game_slug) is not None


def test_active_and_disabled_collision_is_not_guessed(env):
    game, cfg = env
    path = game / 'ambiguous.dll'
    path.write_bytes(b'one')
    Path(str(path) + '.disabled').write_bytes(b'two')
    register(cfg, [path])
    result = uninstall(cfg)
    assert result['record_retained'] is True
    assert path.read_bytes() == b'one'
    assert Path(str(path) + '.disabled').read_bytes() == b'two'


def test_download_install_manage_restart_uninstall(monkeypatch, tmp_path):
    """Real localhost HTTP -> ZIP -> preview -> snapshot -> files -> new process.

    No model/source service is used; this verifies the execution chain, not
    search semantics, authorization via chat, or the actual game runtime.
    """
    game = tmp_path / 'game'
    game.mkdir()
    (game / 'FixtureGame.exe').write_bytes(b'not an executable; never launched')
    (game / 'FixtureGame_Data').mkdir()
    (game / 'UnityPlayer.dll').write_bytes(b'synthetic runtime marker')
    original = game / 'Data' / 'fixture.txt'
    original.parent.mkdir()
    original.write_bytes(b'original-data')
    untouched = game / 'user-save.dat'
    untouched.write_bytes(b'precious-save')
    monkeypatch.setattr(db, 'DB_FILE', str(tmp_path / 'state.db'))
    monkeypatch.setattr(installer, 'BACKUPS_DIR', str(tmp_path / 'backups'))
    monkeypatch.setattr(snapshot, 'SNAPSHOTS_DIR', str(tmp_path / 'snapshots'))
    monkeypatch.setattr(downloader, 'DOWNLOADS_DIR', str(tmp_path / 'downloads'))
    db.init_db()
    cfg = Config(game_root=str(game), game_slug='fixture')
    blob = io.BytesIO()
    with zipfile.ZipFile(blob, 'w') as archive:
        archive.writestr('fixture.txt', b'mod-data')
        archive.writestr('helper.txt', b'new-file')
    body = blob.getvalue()
    requests = []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def do_GET(self):
            requests.append(self.path)
            self.send_response(200)
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    cache = tmp_path / 'downloads' / 'fixture.zip'
    cache.parent.mkdir()
    try:
        downloader.download_file(f'http://127.0.0.1:{server.server_port}/fixture.zip', str(cache))
    finally:
        server.shutdown()
        server.server_close()
        worker.join(2)
    assert requests == ['/fixture.zip']
    assert cache.read_bytes() == body
    args = {'local_path': str(cache), 'mapping': {
        'fixture.txt': 'Data/fixture.txt', 'helper.txt': 'Data/helper.txt'},
        'require_verified_preflight': True}
    preview = json.loads(tools.execute('mod_install_custom', args, cfg))
    assert preview.get('requires_confirmation') is True, preview
    assert original.read_bytes() == b'original-data'
    assert not (game / 'Data' / 'helper.txt').exists()
    installed = json.loads(tools.execute('mod_install_custom', {
        **args, 'preflight_confirmed': True,
        'preflight_confirmation_token': preview['confirmation_token']}, cfg))
    assert installed['installed'] == 2, installed
    assert original.read_bytes() == b'mod-data'
    assert (game / 'Data' / 'helper.txt').read_bytes() == b'new-file'
    mods = db.get_installed_mods('fixture')
    assert len(mods) == 1
    mid = mods[0].id
    snapshot_dir = snapshot.find_snapshot_dir(installed['snapshot_id'])
    manifest = json.loads((Path(snapshot_dir) / 'manifest.json').read_text(encoding='utf-8'))
    assert 'Data/fixture.txt' in manifest['files']
    disabled_preview = json.loads(tools.execute('mod_disable', {'mod_id': mid}, cfg))
    disabled = json.loads(tools.execute('mod_disable', {'mod_id': mid, 'confirmed': True,
        'confirmation_token': disabled_preview['confirmation_token']}, cfg))
    assert disabled['verified'] is True
    assert not original.exists()
    assert Path(str(original) + '.disabled').read_bytes() == b'mod-data'
    enabled = json.loads(tools.execute('mod_enable', {'mod_id': mid, 'confirmed': True}, cfg))
    assert enabled.get('enabled') == 2, enabled
    assert original.read_bytes() == b'mod-data'
    # New process only reads persisted inventory; restart never resumes writes.
    code = ('import json; from modagent import db; '
            'print(json.dumps([m.id for m in db.get_installed_mods("fixture")]))')
    process = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True,
        timeout=15, check=True, env={**os.environ, 'MODAGENT_DATA_DIR': str(tmp_path)})
    assert json.loads(process.stdout) == [mid]
    assert original.read_bytes() == b'mod-data'
    removed = uninstall(cfg, mid)
    assert removed['status'] == 'completed', removed
    assert db.get_installed_mods('fixture') == []
    assert original.read_bytes() == b'original-data'
    assert not (game / 'Data' / 'helper.txt').exists()
    assert untouched.read_bytes() == b'precious-save'
