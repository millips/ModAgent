import json
import os
import zipfile
import pytest

if not os.environ.get('MODAGENT_DATA_DIR'):
    raise RuntimeError('Isolated data directory required')

from modagent import config, db, downloader, installer, nexus, snapshot, tools, user_config


@pytest.mark.parametrize('source', ['nexus_id', 'nexus_name', 'thunderstore'])
@pytest.mark.parametrize('dependency_in_task', [False, True])
def test_source_dependency_gate_uses_task_instance(monkeypatch, tmp_path, source, dependency_in_task):
    monkeypatch.setattr(config, 'CONFIG_DIR', str(tmp_path / 'state'))
    monkeypatch.setattr(config, 'CONFIG_FILE', str(tmp_path / 'state/config.json'))
    monkeypatch.setattr(db, 'DB_FILE', str(tmp_path / 'state.db')); db.init_db()
    monkeypatch.setattr(snapshot, 'SNAPSHOTS_DIR', str(tmp_path / 'snapshots'))
    monkeypatch.setattr(installer, 'BACKUPS_DIR', str(tmp_path / 'backups'))
    monkeypatch.setattr(downloader, 'DOWNLOADS_DIR', str(tmp_path))
    monkeypatch.setattr(snapshot, '_workshop_state', lambda *_: None)
    monkeypatch.setattr(user_config, 'capture_snapshot', lambda *_: [])
    cfgs = []
    for label in ('A', 'B'):
        root = tmp_path / label
        exe = root / 'Pal/Binaries/Win64/Palworld-Win64-Shipping.exe'
        exe.parent.mkdir(parents=True); exe.write_bytes(b'marker')
        cfgs.append(config.Config(game_root=str(root), game_slug='palworld', game_name='Palworld',
                                 game_instance_id=config.make_game_instance_id(str(root))))
    task_cfg, current_cfg = cfgs
    config.save(current_cfg)
    dependency_cfg = task_cfg if dependency_in_task else current_cfg
    dep_file = tmp_path / ('A' if dependency_in_task else 'B') / 'dependency.pak'
    dep_file.write_bytes(b'dependency')
    db.add_mod(db.InstalledMod(id='900', name='Fixture Required Library', version='1.0.0', snapshot_id='',
        game_slug=dependency_cfg.game_instance_id, files_installed=json.dumps([str(dep_file)])))
    db.upsert_mod_source_binding(dependency_cfg.game_instance_id, '900',
        'thunderstore' if source == 'thunderstore' else 'nexus',
        'Fixture-RequiredLibrary' if source == 'thunderstore' else '900')
    label = '900' if source == 'nexus_id' else 'Fixture Required Library'
    remote_scopes = []
    def detail(mid, game, *args, **kwargs):
        remote_scopes.append(game)
        return {'name':'Target skin', 'dependencies':[label]}
    monkeypatch.setattr(nexus, 'get_detail', detail)
    monkeypatch.setattr(nexus, 'get_mod', lambda *a, **k: {'name':'Target skin'})
    package = tmp_path / 'target.zip'
    with zipfile.ZipFile(package, 'w') as archive:
        archive.writestr('target.pak', b'new-target')
    if source == 'thunderstore':
        downloader.remember_download_provenance(str(package), {
            'source':'thunderstore', 'source_key':'Fixture-Target',
            'source_url':'https://thunderstore.io/c/palworld/p/Fixture/Target/',
            'game_slug':'palworld', 'name':'Target skin', 'version':'1.0.0',
            'dependencies':['Fixture-RequiredLibrary-1.0.0'], 'detail_verified':True,
            'staleness':{'stale':False},
        })
        assert tools._download_source_provenance(str(package), 'palworld')['source'] == 'thunderstore'
    result = json.loads(tools.execute('mod_install', {'mod_id':'target' if source == 'thunderstore' else '42',
        'local_path':str(package), 'require_verified_preflight':True}, task_cfg))
    target = tmp_path / 'A/Pal/Content/Paks/~mods/target.pak'
    if dependency_in_task:
        assert result.get('files_installed'), result
        assert target.read_bytes() == b'new-target'
        assert len(db.list_snapshots(task_cfg.game_instance_id)) == 1
    else:
        assert result.get('status') == 'dependency_blocked', result
        assert result.get('missing_dependencies')
        assert not target.exists()
        assert not db.list_snapshots(task_cfg.game_instance_id)
        assert not db.get_mod('target' if source == 'thunderstore' else '42', task_cfg.game_instance_id)
    assert dep_file.read_bytes() == b'dependency'
    assert not (tmp_path / 'B/Pal/Content/Paks/~mods/target.pak').exists()
    assert not db.list_snapshots(current_cfg.game_instance_id)
    assert config.load().game_instance_id == current_cfg.game_instance_id
    if source != 'thunderstore':
        assert remote_scopes and set(remote_scopes) == {'palworld'}
