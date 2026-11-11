"""A shared snapshot rollback must invalidate earlier batch successes."""
import json
import os
import zipfile

import pytest

if not os.environ.get('MODAGENT_DATA_DIR'):
    raise RuntimeError('Isolated data directory required')

from modagent import config, db, installer, snapshot, tools, user_config


@pytest.mark.parametrize('cleanup_failure', [False, True])
@pytest.mark.parametrize('restore_mode', ['complete', 'incomplete', 'raise_before', 'raise_after'])
@pytest.mark.parametrize('already_installed', [False, True])
def test_batch_stops_and_reconciles_after_shared_rollback(monkeypatch, tmp_path, cleanup_failure, restore_mode, already_installed):
    incomplete_restore = restore_mode != 'complete'
    monkeypatch.setattr(db, 'DB_FILE', str(tmp_path / 'state.db'))
    db.init_db()
    monkeypatch.setattr(snapshot, 'SNAPSHOTS_DIR', str(tmp_path / 'snapshots'))
    monkeypatch.setattr(installer, 'BACKUPS_DIR', str(tmp_path / 'backups'))
    monkeypatch.setattr(snapshot, '_workshop_state', lambda *_: None)
    monkeypatch.setattr(user_config, 'capture_snapshot', lambda *_: [])
    monkeypatch.setattr(user_config, 'restore_snapshot', lambda *_: {'complete': restore_mode != 'incomplete'})
    real_restore = snapshot.snapshot_restore
    if restore_mode.startswith('raise_'):
        def broken_restore(sid):
            if restore_mode == 'raise_after':
                real_restore(sid)
            raise RuntimeError('private snapshot failure')
        monkeypatch.setattr(snapshot, 'snapshot_restore', broken_restore)
    root = tmp_path / 'game'
    marker = root / 'Pal/Binaries/Win64/Palworld-Win64-Shipping.exe'
    marker.parent.mkdir(parents=True)
    marker.write_bytes(b'marker')
    mod_dir = root / 'Pal/Content/Paks/~mods'
    mod_dir.mkdir(parents=True)
    cfg = config.Config(game_root=str(root), game_slug='palworld', game_name='Palworld',
                        game_instance_id=config.make_game_instance_id(str(root)))
    items = []
    for mid in ('first', 'second', 'third'):
        (mod_dir / (mid + '.pak')).write_bytes(b'original-' + mid.encode())
        package = tmp_path / (mid + '.zip')
        with zipfile.ZipFile(package, 'w') as archive:
            archive.writestr(mid + '.pak', b'installed-' + mid.encode())
        items.append({'mod_id': mid, 'local_path': str(package)})
    if already_installed:
        db.add_mod(db.InstalledMod(id='first', name='Existing first', version='original',
            snapshot_id='previous', game_slug=cfg.game_instance_id,
            files_installed=json.dumps([str(mod_dir / 'first.pak')])))
    original_add, original_remove = db.add_mod, db.remove_mod
    attempted = []

    def register(mod):
        attempted.append(mod.id)
        if mod.id == 'second':
            raise RuntimeError('injected registration failure')
        return original_add(mod)

    def remove(mid, *args, **kwargs):
        if cleanup_failure and mid == 'first':
            raise RuntimeError('private cleanup failure')
        return original_remove(mid, *args, **kwargs)

    monkeypatch.setattr(db, 'add_mod', register)
    monkeypatch.setattr(db, 'remove_mod', remove)
    result = json.loads(tools.execute('mod_install_batch', {'items': items}, cfg))
    assert attempted == (['second'] if already_installed else ['first', 'second']), result
    assert result['succeeded'] == int(already_installed) and result['failed'] == 3 - int(already_installed), result
    assert result['all_selected_installed'] is False
    assert result['results'][0]['ok'] == already_installed
    expected_status = ('already_installed' if already_installed else
        'rollback_unconfirmed' if incomplete_restore or cleanup_failure else 'rolled_back')
    assert result['results'][0]['status'] == expected_status
    assert result['results'][1]['rollback']['complete'] == (not incomplete_restore)
    if incomplete_restore:
        assert '已恢复安装前快照' not in result['results'][1]['error']
    if restore_mode.startswith('raise_'):
        assert result['results'][1]['rollback']['error_code'] == 'INSTALL_ROLLBACK_FAILED'
    assert result['results'][2]['status'] == 'not_attempted'
    assert result['batch_stopped'] is True
    for mid in ('first', 'second', 'third'):
        changed = restore_mode == 'raise_before' and (mid == 'second' or (mid == 'first' and not already_installed))
        assert (mod_dir / (mid + '.pak')).read_bytes() == (b'installed-' if changed else b'original-') + mid.encode()
    assert bool(db.get_mod('first', cfg.game_instance_id)) == (already_installed or incomplete_restore or cleanup_failure)
    if already_installed:
        assert db.get_mod('first', cfg.game_instance_id).version == 'original'
    assert not db.get_mod('third', cfg.game_instance_id)
    assert len(db.list_snapshots(cfg.game_instance_id)) == 1
    assert 'private cleanup failure' not in json.dumps(result)
    assert 'private snapshot failure' not in json.dumps(result)
