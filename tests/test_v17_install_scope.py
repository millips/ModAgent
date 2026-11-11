import json
import os
import zipfile
import pytest
if not os.environ.get('MODAGENT_DATA_DIR'):
    raise RuntimeError('Isolated data directory required')
from modagent import config, db, tools, snapshot, installer, user_config, downloader


@pytest.mark.parametrize('other_record', [False, True])
@pytest.mark.parametrize('registration_failure,cleanup_failure', [(False,None),(True,None),(False,'before'),(False,'after'),(False,'receipt')])
@pytest.mark.parametrize('mode', ['custom', 'automatic', 'batch'])
def test_install_uses_captured_instance_not_current_settings(monkeypatch, tmp_path, other_record, registration_failure, cleanup_failure, mode):
    automatic = mode != 'custom'
    monkeypatch.setattr(config, 'CONFIG_DIR', str(tmp_path / 'state'))
    monkeypatch.setattr(config, 'CONFIG_FILE', str(tmp_path / 'state/config.json'))
    monkeypatch.setattr(db, 'DB_FILE', str(tmp_path / 'db.sqlite')); db.init_db()
    monkeypatch.setattr(snapshot, 'SNAPSHOTS_DIR', str(tmp_path / 'snapshots'))
    monkeypatch.setattr(installer, 'BACKUPS_DIR', str(tmp_path / 'backups'))
    monkeypatch.setattr(downloader, 'DOWNLOADS_DIR', str(tmp_path))
    monkeypatch.setattr(snapshot, '_workshop_state', lambda *a: None)
    monkeypatch.setattr(user_config, 'capture_snapshot', lambda *a: [])
    cfgs = []
    relative = 'Pal/Content/Paks/~mods/fixture.pak' if automatic else 'Pal/Content/Localization/Game/fixture.locres'
    member = 'fixture.pak' if automatic else 'fixture.locres'
    mod_id = 'fixture' if automatic else 'custom_fixture'
    for label in ['A', 'B']:
        root = tmp_path / label
        exe = root / 'Pal/Binaries/Win64/Palworld-Win64-Shipping.exe'
        exe.parent.mkdir(parents=True); exe.write_bytes(b'fixture marker')
        target = root / relative; target.parent.mkdir(parents=True); target.write_bytes(label.encode())
        cfgs.append(config.Config(game_root=str(root), game_slug='palworld', game_name='Palworld',
                                  game_instance_id=config.make_game_instance_id(str(root))))
    a, b = cfgs
    if other_record:
        db.add_mod(db.InstalledMod(id=mod_id, name='B original', version='B', snapshot_id='',
            game_slug=b.game_instance_id, files_installed=json.dumps([str(tmp_path / 'B' / relative)])))
    config.save(b)
    package = tmp_path / 'fixture.zip'
    with zipfile.ZipFile(package, 'w') as archive:
        archive.writestr(member, b'new-A')
    downloader.remember_download_provenance(str(package), {
        'source': 'github', 'source_key': 'fixture/skin', 'source_url': 'https://github.com/fixture/skin',
        'game_slug': 'palworld', 'name': 'Fixture skin', 'version': '1.0',
    })
    args = {'local_path':str(package), 'mapping': {member:relative}, 'require_verified_preflight': True}
    if cleanup_failure:
        def fail_cleanup(*args):
            if cleanup_failure == 'receipt':
                return {'removed':False, 'reason':'PRIVATE cache detail'}
            if cleanup_failure == 'after':
                package.unlink()
            raise OSError('PRIVATE cleanup exception')
        monkeypatch.setattr(downloader, 'cleanup_installed_archive', fail_cleanup)
    if not automatic:
        preview = json.loads(tools.execute('mod_install_custom', args, a))
        assert preview['status'] == 'preinstall_confirmation_required'
    if registration_failure:
        def fail_registration(mod):
            raise RuntimeError('fixture inventory failure')
        monkeypatch.setattr(db, 'add_mod', fail_registration)
    if mode == 'batch':
        result = json.loads(tools.execute('mod_install_batch', {
            'items': [{'local_path': str(package), 'mod_id': mod_id}],
        }, a))
    elif automatic:
        result = json.loads(tools.execute('mod_install', {'local_path':str(package), 'mod_id':mod_id}, a))
    else:
        result = json.loads(tools.execute('mod_install_custom', {**args, 'preflight_confirmed':True,
            'preflight_confirmation_token':preview['confirmation_token']}, a))
    if cleanup_failure:
        receipt = result['results'][0] if mode == 'batch' else result
        assert receipt.get('cache_cleanup', {}).get('status') == 'unconfirmed', result
        assert 'PRIVATE' not in json.dumps(result)
        assert package.exists() == (cleanup_failure != 'after')
    if mode == 'batch':
        assert result['succeeded'] == int(not registration_failure), result
        assert result['failed'] == int(registration_failure), result
        assert result['all_selected_installed'] == (not registration_failure), result
        assert len(result['results']) == 1
    elif registration_failure:
        assert result.get('error') and result['rollback_complete'], result
    else:
        assert len(result['files_installed']) == 1, result
    assert (tmp_path / 'A' / relative).read_bytes() == (b'A' if registration_failure else b'new-A')
    assert (tmp_path / 'B' / relative).read_bytes() == b'B'
    assert len(db.get_installed_mods(a.game_instance_id)) == int(not registration_failure)
    b_rows = db.get_installed_mods(b.game_instance_id)
    assert len(b_rows) == int(other_record)
    if other_record:
        assert b_rows[0].name == 'B original' and b_rows[0].version == 'B'
    if not automatic:
        assert relative in db.get_custom_domain_files(a.game_instance_id)
    assert not db.get_custom_domain_files(b.game_instance_id)
    rows = db.list_snapshots(a.game_instance_id)
    assert len(rows) == 1 and rows[0].id == result['snapshot_id']
    assert not db.list_snapshots(b.game_instance_id)
    bindings = db.get_mod_source_bindings(a.game_instance_id)
    assert len(bindings) == int(not registration_failure)
    if not registration_failure:
        assert bindings[0]['source_key'] == 'fixture/skin'
    assert not db.get_mod_source_bindings(b.game_instance_id)
    manifest = json.loads((tmp_path / 'snapshots' / a.game_instance_id / result['snapshot_id'] / 'manifest.json').read_text(encoding='utf-8'))
    assert manifest['game_instance_id'] == a.game_instance_id
    assert config.load().game_instance_id == b.game_instance_id
