import json
import os
import pytest

if not os.environ.get('MODAGENT_DATA_DIR'):
    raise RuntimeError('Isolated data directory required')

from modagent import config, db, installer, snapshot, tools, user_config


@pytest.mark.parametrize('other_record', [False, True])
@pytest.mark.parametrize('shared', [False, True])
def test_uninstall_uses_captured_instance(monkeypatch, tmp_path, other_record, shared):
    monkeypatch.setattr(config, 'CONFIG_DIR', str(tmp_path / 'state'))
    monkeypatch.setattr(config, 'CONFIG_FILE', str(tmp_path / 'state/config.json'))
    monkeypatch.setattr(db, 'DB_FILE', str(tmp_path / 'state.db')); db.init_db()
    monkeypatch.setattr(snapshot, 'SNAPSHOTS_DIR', str(tmp_path / 'snapshots'))
    monkeypatch.setattr(installer, 'BACKUPS_DIR', str(tmp_path / 'backups'))
    monkeypatch.setattr(snapshot, '_workshop_state', lambda *_: None)
    monkeypatch.setattr(user_config, 'capture_snapshot', lambda *_: [])
    monkeypatch.setattr(user_config, 'uninstall_mod_configs', lambda *_: {'complete': True})
    configs, paths = [], []
    for label in ('A', 'B'):
        root = tmp_path / label
        marker = root / 'Pal/Binaries/Win64/Palworld-Win64-Shipping.exe'
        marker.parent.mkdir(parents=True); marker.write_bytes(b'marker')
        path = root / 'Pal/Content/Paks/~mods/fixture.pak'
        path.parent.mkdir(parents=True); path.write_bytes(b'original-' + label.encode())
        installer._backup_file(str(path), str(root), 'palworld')
        path.write_bytes(b'mod-' + label.encode())
        cfg = config.Config(game_root=str(root), game_slug='palworld', game_name='Palworld',
                            game_instance_id=config.make_game_instance_id(str(root)))
        configs.append(cfg); paths.append(path)
        if label == 'A' or other_record:
            db.add_mod(db.InstalledMod(id='same', name='Mod ' + label, version=label, snapshot_id='',
                game_slug=cfg.game_instance_id, files_installed=json.dumps([str(path)])))
    a, b = configs
    if shared:
        db.add_mod(db.InstalledMod(id='related', name='Related A', version='1', snapshot_id='',
            game_slug=a.game_instance_id, dependencies=json.dumps(['same']),
            files_installed=json.dumps([str(paths[0])])))
    config.save(b)
    preview = json.loads(tools.execute('mod_uninstall', {'mod_id':'same'}, a))
    assert preview.get('mod_name') == 'Mod A', preview
    assert preview['will_delete_sample'] == [str(paths[0])]
    assert preview['dependents'] == (['Related A'] if shared else [])
    assert not db.list_snapshots(a.game_instance_id)
    result = json.loads(tools.execute('mod_uninstall', {'mod_id':'same', 'confirmed':True}, a))
    assert result['status'] == 'completed', result
    assert paths[0].read_bytes() == (b'mod-A' if shared else b'original-A')
    assert result['kept_shared'] == int(shared)
    assert not db.get_mod('same', a.game_instance_id)
    assert bool(db.get_mod('related', a.game_instance_id)) == shared
    assert bool(db.get_mod('same', b.game_instance_id)) == other_record
    if other_record:
        assert db.get_mod('same', b.game_instance_id).version == 'B'
    assert paths[1].read_bytes() == b'mod-B'
    assert installer._backup_lookup(str(paths[1]), b.game_root, 'palworld')
    snaps = db.list_snapshots(a.game_instance_id)
    assert len(snaps) == 1 and snaps[0].id == result['snapshot_id']
    assert not db.list_snapshots(b.game_instance_id)
    assert config.load().game_instance_id == b.game_instance_id
