import json
import os
import zipfile
import pytest

if not os.environ.get('MODAGENT_DATA_DIR'):
    raise RuntimeError('Isolated data directory required')

from modagent import config, db, downloader, installer, nexus, snapshot, tools, user_config


_UPDATE_CASES = [False, True, 'inventory_before', 'inventory_after', 'binding_before', 'binding_after',
    'rollback_before', 'rollback_after', 'unsafe_record', 'invalid_record', 'empty_record', 'typed_record',
    'remove_pending', 'remove_unsafe', 'remove_cancelled', 'remove_partial', 'shared_current', 'shared_other',
    'incoming_current', 'incoming_other', 'bad_archive', 'shared_relative', 'shared_corrupt', 'shared_typed', 'shared_late_corrupt',
    'old_edit_download', 'old_delete_download', 'old_disable_download', 'old_edit_snapshot', 'old_delete_snapshot', 'old_disable_snapshot',
    'snapshot_before', 'snapshot_after', 'snapshot_empty', 'snapshot_invalid', 'cache_before', 'cache_after', 'cache_receipt']
_SOURCE_CASES = ['main_error', 'main_invalid', 'download_error', 'download_invalid', 'download_missing',
    'thunderstore_error', 'thunderstore_invalid', 'main_tls', 'main_timeout', 'main_auth', 'main_rate',
    'main_redirect', 'download_tls']


@pytest.mark.parametrize('other_record,install_failure,source_fault',
    [(other, case, None) for other in [False, True] for case in _UPDATE_CASES]
    + [(False, False, fault) for fault in _SOURCE_CASES])
def test_update_keeps_captured_instance_and_source(monkeypatch, tmp_path, other_record, install_failure, source_fault):
    monkeypatch.setattr(config, 'CONFIG_DIR', str(tmp_path / 'state'))
    monkeypatch.setattr(config, 'CONFIG_FILE', str(tmp_path / 'state/config.json'))
    monkeypatch.setattr(db, 'DB_FILE', str(tmp_path / 'state.db')); db.init_db()
    monkeypatch.setattr(snapshot, 'SNAPSHOTS_DIR', str(tmp_path / 'snapshots'))
    monkeypatch.setattr(installer, 'BACKUPS_DIR', str(tmp_path / 'backups'))
    monkeypatch.setattr(snapshot, '_workshop_state', lambda *_: None)
    monkeypatch.setattr(user_config, 'capture_snapshot', lambda *_: [])
    monkeypatch.setattr(user_config, 'restore_snapshot', lambda *_: {'complete':True})
    monkeypatch.setattr(user_config, 'uninstall_mod_configs', lambda *_: {'complete':True})
    configs, paths = [], []
    for label in ('A', 'B'):
        root = tmp_path / label
        marker = root / 'Pal/Binaries/Win64/Palworld-Win64-Shipping.exe'
        marker.parent.mkdir(parents=True); marker.write_bytes(b'marker')
        path = root / 'Pal/Content/Paks/~mods/fixture.pak'
        path.parent.mkdir(parents=True); path.write_bytes(b'original-' + label.encode())
        installer._backup_file(str(path), str(root), 'palworld')
        path.write_bytes(label.encode())
        cfg = config.Config(game_root=str(root), game_slug='palworld', game_name='Palworld',
                            game_instance_id=config.make_game_instance_id(str(root)))
        configs.append(cfg); paths.append(path)
        if label == 'A' or other_record:
            db.add_mod(db.InstalledMod(id='42', name='Skin ' + label, version=label, snapshot_id='',
                game_slug=cfg.game_instance_id, files_installed=json.dumps([str(path)])))
            key = '101' if label == 'A' else '202'
            db.upsert_mod_source_binding(cfg.game_instance_id, '42', 'nexus', key,
                'https://www.nexusmods.com/palworld/mods/' + key, 1.0, 'user_confirmed', label)
    a, b = configs
    config.save(b)
    snapshot_failure = isinstance(install_failure, str) and install_failure.startswith('snapshot_')
    if snapshot_failure:
        create_snapshot = snapshot.snapshot_create
        def bad_snapshot(*args, **kwargs):
            if install_failure == 'snapshot_empty':
                return ''
            if install_failure == 'snapshot_invalid':
                return {'id':'PRIVATE'}
            if install_failure == 'snapshot_after':
                create_snapshot(*args, **kwargs)
            raise OSError('PRIVATE backup failure')
        monkeypatch.setattr(snapshot, 'snapshot_create', bad_snapshot)
    old_change = isinstance(install_failure, str) and install_failure.startswith('old_')
    def change_old_file():
        if '_edit_' in install_failure:
            paths[0].write_bytes(b'external-edit')
        elif '_delete_' in install_failure:
            paths[0].unlink()
        else:
            paths[0].rename(str(paths[0]) + '.disabled')
    if old_change and install_failure.endswith('_snapshot'):
        actual_snapshot = snapshot.snapshot_create
        def snapshot_then_change(*args, **kwargs):
            sid = actual_snapshot(*args, **kwargs)
            change_old_file()
            return sid
        monkeypatch.setattr(snapshot, 'snapshot_create', snapshot_then_change)
    if source_fault and source_fault.startswith('thunderstore'):
        from modagent.sources import thunderstore
        db.upsert_mod_source_binding(a.game_instance_id, '42', 'thunderstore', 'Team-Fixture',
            'https://thunderstore.io/c/palworld/p/Team/Fixture/', 1.0, 'user_confirmed', 'A')
        def fail_thunderstore(*args, **kwargs):
            if source_fault == 'thunderstore_invalid':
                return []
            raise RuntimeError('PRIVATE token=secret')
        monkeypatch.setattr(thunderstore, 'download', fail_thunderstore)
    ownership_case = install_failure in ('shared_relative', 'shared_corrupt', 'shared_typed', 'shared_late_corrupt')
    def add_owner_record():
        records = {
            'shared_relative':json.dumps([os.path.relpath(paths[0], a.game_root)]),
            'shared_corrupt':'PRIVATE broken JSON',
            'shared_typed':json.dumps([{'path':str(paths[0])}]),
            'shared_late_corrupt':'PRIVATE broken JSON',
        }
        db.add_mod(db.InstalledMod(id='related', name='Other owner', version='1', snapshot_id='',
            game_slug=a.game_instance_id, files_installed=records[install_failure]))
    if ownership_case and install_failure != 'shared_late_corrupt':
        add_owner_record()
    incoming = install_failure in ('incoming_current', 'incoming_other')
    if incoming:
        owner = a if install_failure == 'incoming_current' else b
        collision = paths[0 if owner is a else 1].with_name('collision.pak')
        collision.write_bytes(b'other-mod')
        db.add_mod(db.InstalledMod(id='related', name='Other owner', version='1', snapshot_id='',
            game_slug=owner.game_instance_id, files_installed=json.dumps([str(collision)])))
    if install_failure in ('shared_current', 'shared_other'):
        owner = a if install_failure == 'shared_current' else b
        owned_path = paths[0] if owner is a else paths[1]
        db.add_mod(db.InstalledMod(id='related', name='Shared dependency', version='1', snapshot_id='',
            game_slug=owner.game_instance_id, files_installed=json.dumps([str(owned_path)])))
    invalid_record = install_failure in ('unsafe_record', 'invalid_record', 'empty_record', 'typed_record')
    if invalid_record:
        row = db.get_mod('42', a.game_instance_id)
        row.files_installed = {
            'unsafe_record': json.dumps([str(paths[0]), str(paths[1])]),
            'invalid_record': '{broken', 'empty_record': '[]',
            'typed_record': json.dumps([str(paths[0]), {'path':str(paths[0])}]),
        }[install_failure]
        db.update_mod(row)
    package = tmp_path / 'new.zip'
    with zipfile.ZipFile(package, 'w') as archive:
        archive.writestr('fixture.pak', b'new-A')
        if incoming:
            archive.writestr('collision.pak', b'new-collision')
    if install_failure == 'bad_archive':
        package.write_bytes(b'PRIVATE invalid zip')
    requested = []
    def main_file(mid, game, *_):
        requested.append((mid, game))
        import ssl
        import urllib.error
        if source_fault == 'main_tls':
            raise urllib.error.URLError(ssl.SSLCertVerificationError('PRIVATE certificate detail'))
        if source_fault == 'main_timeout':
            raise TimeoutError('PRIVATE timeout detail')
        if source_fault in ('main_auth', 'main_rate', 'main_redirect'):
            code = {'main_auth':403, 'main_rate':429, 'main_redirect':302}[source_fault]
            raise urllib.error.HTTPError('https://example.invalid/PRIVATE', code, 'PRIVATE', {}, None)
        if source_fault == 'main_error':
            raise RuntimeError('PRIVATE token=secret')
        if source_fault == 'main_invalid':
            return ['PRIVATE']
        return {'file_id':99, 'version':'2.0'}
    async def download(**kwargs):
        requested.append((kwargs['mod_id'], kwargs['game_slug']))
        if old_change and install_failure.endswith('_download'):
            change_old_file()
        if source_fault == 'download_tls':
            import ssl
            raise ssl.SSLCertVerificationError('PRIVATE certificate detail')
        if source_fault == 'download_error':
            raise RuntimeError('PRIVATE token=secret')
        if source_fault == 'download_invalid':
            return {'local_path':['PRIVATE']}
        if source_fault == 'download_missing':
            return {'local_path':str(tmp_path / 'missing.zip')}
        if install_failure == 'shared_late_corrupt':
            add_owner_record()
        return {'local_path':str(package)}
    monkeypatch.setattr(nexus, 'get_main_file', main_file)
    monkeypatch.setattr(nexus, 'get_mod', lambda *a, **k: {'dependencies':[]})
    monkeypatch.setattr(downloader, 'download_mod', download)
    bookkeeping_failure = isinstance(install_failure, str) and install_failure.startswith(('inventory', 'binding'))
    cache_failure = isinstance(install_failure, str) and install_failure.startswith('cache_')
    if cache_failure:
        def bad_cleanup(*args):
            if install_failure == 'cache_receipt':
                return {'removed':False, 'reason':'PRIVATE cleanup detail'}
            if install_failure == 'cache_after':
                package.unlink()
            raise OSError('PRIVATE cleanup failure')
        monkeypatch.setattr(downloader, 'cleanup_installed_archive', bad_cleanup)
    rollback_failure = isinstance(install_failure, str) and install_failure.startswith('rollback')
    if rollback_failure:
        actual_restore = snapshot.snapshot_restore
        def fail_restore(sid):
            if install_failure == 'rollback_after':
                actual_restore(sid)
            raise RuntimeError('PRIVATE rollback failure')
        monkeypatch.setattr(snapshot, 'snapshot_restore', fail_restore)
    if bookkeeping_failure:
        monkeypatch.setattr(downloader, 'cleanup_installed_archive',
                            lambda *_: pytest.fail('Unconfirmed registration must not clean the archive'))
        operation = 'update_mod' if install_failure.startswith('inventory') else 'upsert_mod_source_binding'
        original_write = getattr(db, operation)
        def fail_write(*args, **kwargs):
            if install_failure.endswith('after'):
                original_write(*args, **kwargs)
            raise RuntimeError('PRIVATE bookkeeping failure')
        monkeypatch.setattr(db, operation, fail_write)
    if install_failure is True or rollback_failure:
        def fail(*args, **kwargs):
            raise RuntimeError('fixture invalid archive')
        monkeypatch.setattr(installer, 'install_mod', fail)
    removal_incomplete = isinstance(install_failure, str) and install_failure.startswith('remove_')
    if removal_incomplete:
        actual_remove = installer.uninstall_mod
        def incomplete_remove(*args, **kwargs):
            receipt = actual_remove(*args, **kwargs)
            # An external editor changes the file after removal. An incomplete
            # receipt must neither install over it nor restore a whole snapshot.
            paths[0].write_bytes(b'external-edit')
            if install_failure == 'remove_pending':
                receipt['pending'] = [str(paths[0])]
            elif install_failure == 'remove_unsafe':
                receipt['blocked_unsafe'] = [{'file':str(paths[0]), 'reason':'PRIVATE'}]
            elif install_failure == 'remove_partial':
                receipt['status'] = 'partial'
            else:
                receipt['status'] = 'cancelled'
            return receipt
        monkeypatch.setattr(installer, 'uninstall_mod', incomplete_remove)
    result = json.loads(tools.execute('mod_update', {'mod_id':'42'}, a))
    if snapshot_failure:
        assert result.get('error_code') == 'UPDATE_SNAPSHOT_FAILED', result
        assert result['write_performed'] is False and result['retryable'] is False
        assert result['snapshot_unconfirmed'] is True
        assert paths[0].read_bytes() == b'A' and paths[1].read_bytes() == b'B'
        assert db.get_mod('42', a.game_instance_id).version == 'A'
        assert len(db.list_snapshots(a.game_instance_id)) == int(install_failure == 'snapshot_after')
        assert not db.list_snapshots(b.game_instance_id)
        assert package.exists()
        assert 'PRIVATE' not in json.dumps(result)
        return
    if old_change:
        assert result.get('error_code') == 'UPDATE_OLD_FILES_UNCONFIRMED', result
        assert result['write_performed'] is False and result['retryable'] is False
        assert db.get_mod('42', a.game_instance_id).version == 'A'
        assert paths[1].read_bytes() == b'B'
        if '_edit_' in install_failure:
            assert paths[0].read_bytes() == b'external-edit'
        else:
            assert not paths[0].exists()
            if '_disable_' in install_failure:
                assert paths[0].with_name(paths[0].name + '.disabled').read_bytes() == b'A'
        assert len(db.list_snapshots(a.game_instance_id)) == int(install_failure.endswith('_snapshot'))
        assert not db.list_snapshots(b.game_instance_id)
        assert package.exists()
        return
    if source_fault:
        kinds = {'main_tls':'tls_error', 'main_timeout':'timeout', 'main_auth':'access_denied',
            'main_rate':'rate_limited', 'main_redirect':'redirect_blocked', 'download_tls':'tls_error'}
        if source_fault in kinds:
            assert result.get('failure_kind') == kinds[source_fault], result
        expected = 'UPDATE_SOURCE_FAILED' if source_fault.startswith('main_') else 'UPDATE_DOWNLOAD_FAILED'
        assert result.get('error_code') == expected, result
        assert result['write_performed'] is False
        assert paths[0].read_bytes() == b'A' and paths[1].read_bytes() == b'B'
        assert db.get_mod('42', a.game_instance_id).version == 'A'
        assert not db.list_snapshots(a.game_instance_id)
        assert 'PRIVATE' not in json.dumps(result) and 'token=secret' not in json.dumps(result)
        return
    if ownership_case:
        expected_code = 'UPDATE_SHARED_FILES' if install_failure == 'shared_relative' else 'UPDATE_OWNERSHIP_UNCONFIRMED'
        assert result.get('error_code') == expected_code, result
        assert result['write_performed'] is False and result['retryable'] is False
        assert bool(requested) == (install_failure == 'shared_late_corrupt')
        assert paths[0].read_bytes() == b'A' and paths[1].read_bytes() == b'B'
        assert db.get_mod('42', a.game_instance_id).version == 'A'
        assert not db.list_snapshots(a.game_instance_id)
        assert not db.list_snapshots(b.game_instance_id)
        assert 'PRIVATE' not in json.dumps(result)
        return
    if install_failure == 'bad_archive':
        assert result.get('error_code') == 'UPDATE_PREVIEW_FAILED', result
        assert result['write_performed'] is False and result['retryable'] is False
        assert paths[0].read_bytes() == b'A' and paths[1].read_bytes() == b'B'
        assert db.get_mod('42', a.game_instance_id).version == 'A'
        assert not db.list_snapshots(a.game_instance_id)
        assert 'PRIVATE' not in json.dumps(result)
        return
    if incoming:
        assert requested == [(101, 'palworld'), (101, 'palworld')]
        assert collision.read_bytes() == b'other-mod'
        assert db.get_mod('related', owner.game_instance_id).version == '1'
        assert paths[1].read_bytes() == b'B'
        if owner is a:
            assert result.get('error_code') == 'UPDATE_TARGET_OWNED', result
            assert result['write_performed'] is False and result['retryable'] is False
            assert paths[0].read_bytes() == b'A'
            assert db.get_mod('42', a.game_instance_id).version == 'A'
            assert not db.list_snapshots(a.game_instance_id)
        else:
            assert result['updated'] == 'Skin A'
            assert paths[0].read_bytes() == b'new-A'
            assert paths[0].with_name('collision.pak').read_bytes() == b'new-collision'
        return
    if install_failure == 'shared_current':
        assert result.get('error_code') == 'UPDATE_SHARED_FILES', result
        assert result['write_performed'] is False and result['retryable'] is False
        assert not requested, 'Shared ownership must be checked before downloading'
        assert paths[0].read_bytes() == b'A' and paths[1].read_bytes() == b'B'
        assert db.get_mod('42', a.game_instance_id).version == 'A'
        assert db.get_mod('related', a.game_instance_id).version == '1'
        assert not db.list_snapshots(a.game_instance_id)
        assert not db.list_snapshots(b.game_instance_id)
        return
    if removal_incomplete:
        assert result.get('error_code') == 'UPDATE_REMOVAL_INCOMPLETE', result
        assert result['recovery_required'] and result['snapshot_restore_skipped']
        assert result['retryable'] is False
        assert paths[0].read_bytes() == b'external-edit'
        assert paths[1].read_bytes() == b'B'
        assert db.get_mod('42', a.game_instance_id).version == 'A'
        assert package.exists()
        assert len(db.list_snapshots(a.game_instance_id)) == 1
        assert not db.list_snapshots(b.game_instance_id)
        assert 'PRIVATE' not in json.dumps(result)
        from modagent.orchestration.outcomes import ToolOutcome
        assert ToolOutcome.from_legacy(result, legacy_ok=False).requires_review
        return
    if invalid_record:
        assert result.get('error_code') == 'UPDATE_UNSAFE_RECORD', result
        assert result['write_performed'] is False
        assert result['retryable'] is False
        assert not requested
        assert paths[0].read_bytes() == b'A' and paths[1].read_bytes() == b'B'
        assert db.get_mod('42', a.game_instance_id).version == 'A'
        assert not db.list_snapshots(a.game_instance_id)
        assert not db.list_snapshots(b.game_instance_id)
        return
    assert requested == [(101, 'palworld'), (101, 'palworld')], result
    if cache_failure:
        assert result.get('warning_code') == 'UPDATE_CACHE_CLEANUP_UNCONFIRMED', result
        assert result['updated'] == 'Skin A' and result['version'] == '2.0'
        assert result['cache_cleanup']['status'] == 'unconfirmed'
        assert package.exists() == (install_failure != 'cache_after')
        assert 'PRIVATE' not in json.dumps(result)
    if bookkeeping_failure:
        assert result['error_code'] == 'UPDATE_INVENTORY_UNCONFIRMED', result
        assert result['recovery_required'] is True
        assert result['write_performed'] is True
        assert result.get('updated') is None
        assert result['files_installed'] == [str(paths[0])]
        assert package.exists(), 'Retain the package while registration is unconfirmed'
        assert 'PRIVATE' not in json.dumps(result)
    elif rollback_failure:
        assert result['restored_previous'] is False, result
        assert result['rollback']['complete'] is False
        assert result['recovery_required'] is True
        assert result['retryable'] is False
        assert 'PRIVATE' not in json.dumps(result)
        from modagent.orchestration.outcomes import ToolOutcome
        assert ToolOutcome.from_legacy(result, legacy_ok=False).requires_review
    elif install_failure is True:
        assert result['restored_previous'] is True, result
    else:
        assert result['updated'] == 'Skin A' and result['version'] == '2.0', result
    expected = (b'original-A' if install_failure == 'rollback_before' else
                b'A' if install_failure is True or rollback_failure else b'new-A')
    assert paths[0].read_bytes() == expected
    assert paths[1].read_bytes() == b'B'
    from pathlib import Path
    for cfg, path, label in zip(configs, paths, ('A', 'B')):
        backup = installer._backup_lookup(str(path), cfg.game_root, 'palworld')
        assert backup, 'Update must retain the original required by a later uninstall'
        assert Path(backup).read_bytes() == b'original-' + label.encode()
    assert db.get_mod('42', a.game_instance_id).version == ('A' if install_failure is True or rollback_failure or install_failure == 'inventory_before' else '2.0')
    assert bool(db.get_mod('42', b.game_instance_id)) == other_record
    if other_record:
        assert db.get_mod('42', b.game_instance_id).version == 'B'
        assert db.get_mod_source_binding('42', b.game_instance_id)['source_key'] == '202'
    assert db.get_mod_source_binding('42', a.game_instance_id)['source_key'] == '101'
    assert len(db.list_snapshots(a.game_instance_id)) == 1
    assert not db.list_snapshots(b.game_instance_id)
    assert config.load().game_instance_id == b.game_instance_id
    # Both the updated version and the rolled-back old version must still be
    # uninstallable back to the pre-Mod original, not merely to the old Mod.
    removed = json.loads(tools.execute('mod_uninstall', {'mod_id':'42', 'confirmed':True}, a))
    assert removed['status'] == 'completed', removed
    assert paths[0].read_bytes() == b'original-A'
    assert not db.get_mod('42', a.game_instance_id)
    assert paths[1].read_bytes() == b'B'
    assert bool(db.get_mod('42', b.game_instance_id)) == other_record
