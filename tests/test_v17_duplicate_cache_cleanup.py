import json
import os
import pytest

if not os.environ.get('MODAGENT_DATA_DIR'):
    raise RuntimeError('Isolated data directory required')

from modagent import config, db, downloader, installer, snapshot, tools


@pytest.mark.parametrize('operation', ['mod_download', 'batch_download', 'mod_install'])
@pytest.mark.parametrize('failure', ['before', 'after', 'receipt'])
def test_duplicate_skip_survives_cache_cleanup_failure(tmp_path, monkeypatch, operation, failure):
    monkeypatch.setattr(config, 'CONFIG_DIR', str(tmp_path / 'state'))
    monkeypatch.setattr(config, 'CONFIG_FILE', str(tmp_path / 'state/config.json'))
    monkeypatch.setattr(db, 'DB_FILE', str(tmp_path / 'state.db')); db.init_db()
    root = tmp_path / 'game'; root.mkdir()
    installed = root / 'fixture.pak'; installed.write_bytes(b'installed')
    archive = tmp_path / '42.zip'; archive.write_bytes(b'cached archive')
    cfg = config.Config(game_root=str(root), game_slug='palworld', game_id=123,
        game_instance_id=config.make_game_instance_id(str(root)), nexus_api_key='synthetic', tier=config.Tier.PRO)
    config.save(cfg)
    db.add_mod(db.InstalledMod(id='42', name='Fixture', version='1', snapshot_id='',
        files_installed=json.dumps([str(installed)]), game_slug=cfg.game_instance_id))
    db.upsert_mod_source_binding(cfg.game_instance_id, '42', 'nexus', '42',
        'https://www.nexusmods.com/palworld/mods/42', 1.0, 'user_confirmed', '1')
    monkeypatch.setattr(tools, '_refresh_local_inventory', lambda *_: {'detected':0})
    monkeypatch.setattr(downloader, 'find_cached_nexus_download', lambda *_: str(archive))
    def forbidden(*args, **kwargs):
        pytest.fail('Already installed must not download, snapshot or install again')
    monkeypatch.setattr(downloader, 'download_mod', forbidden)
    monkeypatch.setattr(installer, 'install_mod', forbidden)
    monkeypatch.setattr(snapshot, 'snapshot_create', forbidden)
    def fail_cleanup(*args):
        if failure == 'receipt':
            return {'removed':False, 'reason':'PRIVATE cache error'}
        if failure == 'after':
            archive.unlink()
        raise OSError('PRIVATE cache failure')
    monkeypatch.setattr(downloader, 'cleanup_installed_archive', fail_cleanup)
    args = {'mods':[{'mod_id':'42'}]} if operation == 'batch_download' else {'mod_id':'42', 'local_path':str(archive)}
    result = json.loads(tools.execute(operation, args, cfg))
    if operation == 'batch_download':
        assert result['status'] == 'completed' and not result['failed'], result
        assert not result['success'], 'No new downloads'
        assert len(result['skipped_installed']) == 1
        receipt = result['skipped_installed'][0]
    else:
        assert result['already_installed'] is True
        assert result['install_skipped' if operation == 'mod_install' else 'download_skipped'] is True
        receipt = result
    assert receipt['cache_cleanup']['status'] == 'unconfirmed'
    assert 'PRIVATE' not in json.dumps(result)
    assert installed.read_bytes() == b'installed'
    assert db.get_mod('42', cfg.game_instance_id).version == '1'
    assert len(db.get_installed_mods(cfg.game_instance_id)) == 1
    assert not db.list_snapshots(cfg.game_instance_id)
    assert archive.exists() == (failure != 'after')
