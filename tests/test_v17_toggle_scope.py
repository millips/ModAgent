"""Same Mod IDs in separate installations cannot share file actions or approval."""
import json
import os
import pytest

if not os.environ.get('MODAGENT_DATA_DIR'):
    raise RuntimeError('An isolated MODAGENT_DATA_DIR is required.')
from modagent import config, db, tools


@pytest.fixture
def installations(monkeypatch, tmp_path):
    monkeypatch.setattr(config, 'CONFIG_DIR', str(tmp_path))
    monkeypatch.setattr(config, 'CONFIG_FILE', str(tmp_path / 'config.json'))
    monkeypatch.setattr(db, 'DB_FILE', str(tmp_path / 'state.db'))
    db.init_db()
    monkeypatch.setattr(tools.user_config, 'preview_toggle_mod_configs', lambda *a: [])
    monkeypatch.setattr(tools.user_config, 'toggle_mod_configs', lambda *a, **k: {'complete':True,'changed':[],'failed':[]})
    items = []
    for label in ['A', 'B']:
        root = tmp_path / label; root.mkdir()
        payload = root / 'fixture.pak'; payload.write_bytes(label.encode())
        scope = config.make_game_instance_id(str(root))
        cfg = config.Config(game_root=str(root), game_slug='fixture', game_instance_id=scope)
        db.add_mod(db.InstalledMod(id='same-id',name=f'Mod {label}',version='1',snapshot_id='',
            game_slug=scope,files_installed=json.dumps([str(payload)])))
        items.append((cfg,payload))
    return items


def test_disable_preview_token_cannot_be_used_for_another_instance(installations):
    (a, pa), (b, pb) = installations
    config.save(a)
    preview = json.loads(tools.execute('mod_disable', {'mod_id':'same-id'}, a))
    config.save(b)
    result = json.loads(tools.execute('mod_disable', {'mod_id':'same-id', 'confirmed':True,
        'confirmation_token':preview['confirmation_token']}, b))
    assert result.get('error') == 'mod_disable_confirmation_invalid'
    assert pa.read_bytes() == b'A' and pb.read_bytes() == b'B'
    assert not pa.with_name(pa.name+'.disabled').exists()
    assert not pb.with_name(pb.name+'.disabled').exists()


@pytest.mark.parametrize('action', ['mod_disable', 'mod_enable'])
@pytest.mark.parametrize('with_dependency', [False, True])
def test_captured_task_changes_only_its_instance(installations, action, with_dependency):
    (a, pa), (b, pb) = installations
    extra = []
    if with_dependency:
        for cfg, payload in installations:
            child = payload.with_name('related.pak'); child.write_bytes(b'related')
            extra.append(child)
            db.add_mod(db.InstalledMod(id='related',name='Related',version='1',snapshot_id='',
                game_slug=cfg.game_instance_id, files_installed=json.dumps([str(child)]),
                dependencies=json.dumps(['same-id'] if action=='mod_disable' else [])))
            if action=='mod_enable':
                target = db.get_mod('same-id', cfg.game_instance_id)
                target.dependencies = json.dumps(['related'])
                db.update_mod(target)
    if action == 'mod_enable':
        pa.rename(pa.with_name(pa.name+'.disabled'))
        pb.rename(pb.with_name(pb.name+'.disabled'))
        for child in extra: child.rename(child.with_name(child.name+'.disabled'))
    config.save(b)
    args = {'mod_id':'same-id', 'confirmed':True} if action=='mod_enable' else {'mod_id':'same-id'}
    if action == 'mod_disable':
        preview = json.loads(tools.execute(action, args, a))
        assert preview['target']['name'] == 'Mod A'
        args.update(confirmed=True, confirmation_token=preview['confirmation_token'])
    result = json.loads(tools.execute(action, args, a))
    assert not result.get('error'), result
    assert result['disabled' if action=='mod_disable' else 'enabled'] == (2 if with_dependency else 1)
    if action == 'mod_disable':
        assert not pa.exists() and pa.with_name(pa.name+'.disabled').read_bytes() == b'A'
        assert pb.read_bytes() == b'B'
    else:
        assert pa.read_bytes() == b'A' and not pa.with_name(pa.name+'.disabled').exists()
        assert not pb.exists() and pb.with_name(pb.name+'.disabled').read_bytes() == b'B'
    if extra:
        assert extra[0].exists() is (action=='mod_enable')
        assert extra[1].exists() is (action=='mod_disable')
