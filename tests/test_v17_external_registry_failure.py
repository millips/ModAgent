"""An unreadable ownership registry must not silently become an empty registry."""
import json
import os
from pathlib import Path
import pytest

if not os.environ.get('MODAGENT_DATA_DIR'):
    raise RuntimeError('An isolated MODAGENT_DATA_DIR is required.')
from modagent import config, db, tools, user_config


@pytest.mark.parametrize('raw', ['{broken', '{}', '[null]'])
def test_bad_registry_blocks_config_write_before_target_changes(monkeypatch, tmp_path, raw):
    monkeypatch.setattr(user_config, 'CONFIG_DIR', str(tmp_path))
    registry = tmp_path / 'external-config-registry.json'; registry.write_text(raw, encoding='utf-8')
    target = tmp_path / 'settings.ini'; target.write_text('[Old]\nx=1\n', encoding='utf-8')
    monkeypatch.setattr(user_config, 'resolve_target', lambda *a: (tmp_path, target))
    with pytest.raises(user_config.ExternalConfigRegistryUnreadable):
        user_config.write_config('documents', 'settings.ini', '[New]\ny=2', game_slug='fixture', mod_id='one')
    assert target.read_text(encoding='utf-8') == '[Old]\nx=1\n'
    assert registry.read_text(encoding='utf-8') == raw


def test_bad_registry_blocks_enable_before_file_changes(monkeypatch, tmp_path):
    monkeypatch.setattr(user_config, 'CONFIG_DIR', str(tmp_path))
    monkeypatch.setattr(db, 'DB_FILE', str(tmp_path / 'state.db'))
    db.init_db()
    root = tmp_path / 'game'; root.mkdir()
    original = root / 'fixture.pak'
    disabled = root / 'fixture.pak.disabled'; disabled.write_bytes(b'preserve')
    db.add_mod(db.InstalledMod(id='fixture',name='Fixture',version='1',snapshot_id='',
        game_slug='fixture', files_installed=json.dumps([str(original)])))
    registry = tmp_path / 'external-config-registry.json'; registry.write_text('{broken', encoding='utf-8')
    result = json.loads(tools.execute('mod_enable', {'mod_id':'fixture'}, config.Config(game_root=str(root),game_slug='fixture')))
    assert result.get('error_code') == 'EXTERNAL_CONFIG_REGISTRY_UNREADABLE'
    assert not original.exists() and disabled.read_bytes() == b'preserve'
    assert registry.read_text(encoding='utf-8') == '{broken'
    registry.write_text('[]', encoding='utf-8')
    recovered = json.loads(tools.execute('mod_enable', {'mod_id':'fixture'}, config.Config(game_root=str(root),game_slug='fixture')))
    assert recovered['enabled'] == 1 and original.read_bytes() == b'preserve'


@pytest.mark.parametrize('unreadable', [True, False])
def test_external_exception_restores_game_files_without_claiming_config_recovery(monkeypatch, tmp_path, unreadable):
    from types import SimpleNamespace
    root = tmp_path / 'game'; root.mkdir()
    original = root / 'fixture.pak'
    disabled = root / 'fixture.pak.disabled'; disabled.write_bytes(b'preserve')
    mod = SimpleNamespace(id='fixture', name='Fixture', files_installed=json.dumps([str(original)]))
    monkeypatch.setattr(user_config, 'preview_toggle_mod_configs', lambda *a: [])
    calls = []
    def fail(*a, **kw):
        calls.append(kw['enabling'])
        assert original.read_bytes() == b'preserve'
        if unreadable:
            raise user_config.ExternalConfigRegistryUnreadable()
        raise PermissionError('PRIVATE registry write error')
    monkeypatch.setattr(user_config, 'toggle_mod_configs', fail)
    result = tools._execute_toggle_plan([mod], True, 'fixture', str(root))
    assert result['error_code'] == 'EXTERNAL_CONFIG_TOGGLE_UNCONFIRMED'
    assert result['external_configs']['complete'] is False
    assert not original.exists() and disabled.read_bytes() == b'preserve'
    assert calls == [True]  # Unknown external state must not be blindly inverted.
    assert 'PRIVATE' not in json.dumps(result)
