"""Installation consent must identify the game instance and actual archive bytes."""
import json
import os
import zipfile
import pytest
if not os.environ.get('MODAGENT_DATA_DIR'):
    raise RuntimeError('Isolated data directory required')
from modagent import db, tools, snapshot, installer, user_config
from modagent.config import Config


@pytest.mark.parametrize('change', ['root', 'archive', 'target', 'snapshot'])
def test_preflight_consent_cannot_be_reused_for_a_changed_target(monkeypatch, tmp_path, change):
    monkeypatch.setattr(db, 'DB_FILE', str(tmp_path / 'state.db')); db.init_db()
    monkeypatch.setattr(snapshot, 'SNAPSHOTS_DIR', str(tmp_path / 'snapshots'))
    monkeypatch.setattr(installer, 'BACKUPS_DIR', str(tmp_path / 'backups'))
    monkeypatch.setattr(snapshot, '_workshop_state', lambda *_: None)
    monkeypatch.setattr(user_config, 'capture_snapshot', lambda *a: [])
    roots = [tmp_path / 'A', tmp_path / 'B']
    relative = 'Pal/Content/Localization/Game/fixture.locres'
    for root in roots:
        exe = root / 'Pal/Binaries/Win64/Palworld-Win64-Shipping.exe'
        exe.parent.mkdir(parents=True); exe.write_bytes(b'fixture marker')
        target = root / relative; target.parent.mkdir(parents=True); target.write_bytes(b'original')
    package = tmp_path / 'fixture.zip'
    def write_package(value):
        with zipfile.ZipFile(package, 'w', compression=zipfile.ZIP_STORED) as archive:
            info = zipfile.ZipInfo('fixture.locres', date_time=(2026, 1, 1, 0, 0, 0))
            archive.writestr(info, value)
    write_package(b'new-one')
    cfg = Config(game_root=str(roots[0]), game_slug='palworld', game_name='Palworld')
    args = {'local_path': str(package), 'mapping': {'fixture.locres': relative}, 'require_verified_preflight': True}
    preview = json.loads(tools.execute('mod_install_custom', args, cfg))
    assert preview['status'] == 'preinstall_confirmation_required'
    real_snapshot_create = snapshot.snapshot_create
    if change == 'root':
        cfg.game_root = str(roots[1])
    elif change == 'archive':
        before = package.stat()
        write_package(b'new-two')
        assert package.stat().st_size == before.st_size
        os.utime(package, ns=(before.st_atime_ns, before.st_mtime_ns))
    elif change == 'target':
        target = roots[0] / relative
        before = target.stat()
        target.write_bytes(b'useredit')
        assert target.stat().st_size == before.st_size
        os.utime(target, ns=(before.st_atime_ns, before.st_mtime_ns))
    else:
        def snapshot_then_edit(*args, **kwargs):
            result = real_snapshot_create(*args, **kwargs)
            (roots[0] / relative).write_bytes(b'useredit')
            return result
        monkeypatch.setattr(snapshot, 'snapshot_create', snapshot_then_edit)
    rejected = json.loads(tools.execute('mod_install_custom', {**args, 'preflight_confirmed': True,
        'preflight_confirmation_token': preview['confirmation_token']}, cfg))
    if change == 'snapshot':
        assert rejected.get('error_code') == 'INSTALL_TARGET_CHANGED', rejected
        assert rejected['errors'] and not rejected.get('installed')
    else:
        assert rejected.get('status') == 'preinstall_confirmation_invalid', rejected
    assert (roots[0] / relative).read_bytes() == (b'useredit' if change in ('target', 'snapshot') else b'original')
    assert (roots[1] / relative).read_bytes() == b'original'
    assert not db.get_installed_mods('palworld')
    assert len(db.list_snapshots('palworld')) == int(change == 'snapshot')
    monkeypatch.setattr(snapshot, 'snapshot_create', real_snapshot_create)
    fresh = json.loads(tools.execute('mod_install_custom', args, cfg))
    installed = json.loads(tools.execute('mod_install_custom', {**args, 'preflight_confirmed': True,
        'preflight_confirmation_token': fresh['confirmation_token']}, cfg))
    assert installed['installed'] == 1
    chosen = roots[1] if change == 'root' else roots[0]
    assert (chosen / relative).read_bytes() == (b'new-two' if change == 'archive' else b'new-one')
    assert (roots[0 if change == 'root' else 1] / relative).read_bytes() == b'original'


def test_unreadable_target_is_not_treated_as_missing(monkeypatch, tmp_path):
    import builtins
    root = tmp_path / 'game'; root.mkdir()
    target = root / 'settings.ini'; target.write_bytes(b'preserve')
    real_open = builtins.open
    def denied(path, *args, **kwargs):
        if os.fspath(path) == str(target):
            raise PermissionError('PRIVATE target access error')
        return real_open(path, *args, **kwargs)
    monkeypatch.setattr(builtins, 'open', denied)
    with pytest.raises(RuntimeError) as caught:
        installer._preflight_file_state(str(target), str(root))
    assert 'PRIVATE' not in str(caught.value)
    monkeypatch.setattr(builtins, 'open', real_open)
    assert target.read_bytes() == b'preserve'
    assert installer._preflight_file_state(str(target), str(root))['exists'] is True
