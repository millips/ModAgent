"""The public automatic install path must preserve transaction conflict state."""
import json
import os
import zipfile
import pytest

if not os.environ.get('MODAGENT_DATA_DIR'):
    raise RuntimeError('Isolated data directory required')

from modagent import config, db, downloader, installer, nexus, snapshot, tools, user_config


@pytest.mark.parametrize('mode', ['install', 'batch', 'update'])
@pytest.mark.parametrize('change', ['target', 'edit', 'delete'])
def test_automatic_install_preserves_external_changes(monkeypatch, tmp_path, mode, change):
    batch = mode == 'batch'
    monkeypatch.setattr(db, 'DB_FILE', str(tmp_path / 'state.db')); db.init_db()
    monkeypatch.setattr(snapshot, 'SNAPSHOTS_DIR', str(tmp_path / 'snapshots'))
    monkeypatch.setattr(installer, 'BACKUPS_DIR', str(tmp_path / 'backups'))
    monkeypatch.setattr(snapshot, '_workshop_state', lambda *_: None)
    monkeypatch.setattr(user_config, 'capture_snapshot', lambda *_: [])
    monkeypatch.setattr(user_config, 'restore_snapshot', lambda *_: {'complete': True})
    root = tmp_path / 'game'
    marker = root / 'Pal/Binaries/Win64/Palworld-Win64-Shipping.exe'
    marker.parent.mkdir(parents=True); marker.write_bytes(b'marker')
    mod_dir = root / 'Pal/Content/Paks/~mods'; mod_dir.mkdir(parents=True)
    first, second = mod_dir / 'a.pak', mod_dir / 'b.pak'
    first.write_bytes(b'old-a'); second.write_bytes(b'old-b')
    cfg = config.Config(game_root=str(root), game_slug='palworld', game_name='Palworld',
                        game_instance_id=config.make_game_instance_id(str(root)))
    package = tmp_path / 'fixture.zip'
    with zipfile.ZipFile(package, 'w') as archive:
        archive.writestr('a.pak', b'new-a'); archive.writestr('b.pak', b'new-b')
    if mode == 'update':
        for path in (first, second):
            installer._backup_file(str(path), str(root), 'palworld')
        db.add_mod(db.InstalledMod(id='42', name='Existing', version='1.0', snapshot_id='',
            game_slug=cfg.game_instance_id, files_installed=json.dumps([str(first), str(second)])))
        monkeypatch.setattr(nexus, 'get_main_file', lambda *a, **k: {'file_id':99, 'version':'2.0'})
        monkeypatch.setattr(nexus, 'get_mod', lambda *a, **k: {'dependencies':[]})
        async def download(**kwargs):
            return {'local_path':str(package)}
        monkeypatch.setattr(downloader, 'download_mod', download)
    items = []
    for mid in ('earlier', 'later'):
        path = tmp_path / (mid + '.zip')
        with zipfile.ZipFile(path, 'w') as archive:
            archive.writestr(mid + '.pak', mid.encode())
        items.append({'mod_id': mid, 'local_path': str(path)})
    real_copy, real_replace = installer.shutil.copy2, installer.os.replace
    mutations = []
    def copy(source, target, *args, **kwargs):
        result = real_copy(source, target, *args, **kwargs)
        if change == 'target' and os.path.basename(source) == 'a.pak' and os.path.basename(os.path.dirname(target)) == 'stage':
            second.write_bytes(b'user-change'); mutations.append(1)
        return result
    def replace(source, target):
        if change != 'target' and os.path.basename(os.path.dirname(source)) == 'stage' and str(target) == str(second):
            assert first.read_bytes() == b'new-a'
            if change == 'edit':
                first.write_bytes(b'user-edit')
            else:
                first.unlink()
            mutations.append(1)
            raise PermissionError('PRIVATE second commit failure')
        return real_replace(source, target)
    monkeypatch.setattr(installer.shutil, 'copy2', copy)
    monkeypatch.setattr(installer.os, 'replace', replace)
    args = {'mod_id': 'fixture', 'local_path': str(package)}
    receipt = json.loads(tools.execute('mod_update' if mode == 'update' else 'mod_install_batch' if batch else 'mod_install',
        {'mod_id':'42'} if mode == 'update' else {'items': [items[0], args, items[1]]} if batch else args, cfg))
    assert mutations
    assert second.read_bytes() == (b'user-change' if change == 'target' else b'old-b')
    if change == 'delete':
        assert not first.exists()
    else:
        assert first.read_bytes() == (b'old-a' if change == 'target' else b'user-edit')
    error = receipt['results'][1] if batch else receipt
    assert error['error_code'] == ('INSTALL_TARGET_CHANGED' if change == 'target' else 'INSTALL_ROLLBACK_INCOMPLETE')
    assert error['snapshot_restore_skipped'] is True
    assert error['recovery_required'] is True
    assert 'PRIVATE' not in json.dumps(receipt)
    assert not db.get_mod('fixture', cfg.game_instance_id)
    if mode == 'update':
        assert db.get_mod('42', cfg.game_instance_id).version == '1.0'
        assert package.exists()
    if change != 'target':
        from pathlib import Path
        recovery = Path(error['recovery_dir'])
        assert (recovery / 'rollback/0').read_bytes() == b'old-a'
        assert error['recovery_files']
    if batch:
        assert receipt['batch_stopped'] is True
        assert receipt['succeeded'] == 1
        assert receipt['results'][0]['ok'] is True
        assert receipt['results'][2]['status'] == 'not_attempted'
        assert (mod_dir / 'earlier.pak').read_bytes() == b'earlier'
        assert not (mod_dir / 'later.pak').exists()
        assert db.get_mod('earlier', cfg.game_instance_id)
