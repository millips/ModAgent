"""Registry commit failure must not leave an unreported configuration write."""
import os
from pathlib import Path
import pytest

if not os.environ.get('MODAGENT_DATA_DIR'):
    raise RuntimeError('Isolated MODAGENT_DATA_DIR required')
from modagent import user_config


@pytest.mark.parametrize('registry_failure', [True, False])
def test_tool_keeps_actual_write_outcome_when_audit_log_fails(monkeypatch, tmp_path, registry_failure):
    import json
    from modagent import config, db, tools
    monkeypatch.setattr(user_config, 'CONFIG_DIR', str(tmp_path / 'state'))
    monkeypatch.setattr(user_config, 'root_for', lambda location: tmp_path / 'docs')
    target = tmp_path / 'docs' / 'settings.ini'
    target.parent.mkdir()
    target.write_bytes(b'[Old]\r\nx=1\r\n')
    calls = []
    def fail_audit(*args, **kwargs):
        calls.append(args)
        raise OSError('PRIVATE audit failure')
    monkeypatch.setattr(db, 'log_operation', fail_audit)
    if registry_failure:
        def fail_registry(*args):
            raise PermissionError('PRIVATE registry failure')
        monkeypatch.setattr(user_config, '_save_registry', fail_registry)
    result = json.loads(tools.execute('game_config_write', {
        'location': 'documents', 'relative_path': 'settings.ini',
        'content': '[New]\ny=2', 'mod_id': 'one',
    }, config.Config(game_slug='fixture', game_root=str(tmp_path))))
    assert result['written'] is (not registry_failure)
    assert result['verified'] is (not registry_failure)
    assert result['receipt_saved'] is False
    assert result['warning_code'] == 'CONFIG_WRITE_RECEIPT_NOT_SAVED'
    assert result['complete'] is False and len(calls) == 1
    assert 'PRIVATE' not in str(result)
    if registry_failure:
        assert result['rolled_back'] is True
        assert result['error_code'] == 'EXTERNAL_CONFIG_REGISTRY_SAVE_FAILED'
        assert target.read_bytes() == b'[Old]\r\nx=1\r\n'
    else:
        assert b'[New]' in target.read_bytes()
        assert user_config._load_registry()[0]['owners']['one']['sections'] == ['new']


@pytest.mark.parametrize('existed', [True, False])
@pytest.mark.parametrize('conflict', [True, False])
def test_registry_save_failure_restores_only_our_write(monkeypatch, tmp_path, existed, conflict):
    monkeypatch.setattr(user_config, 'CONFIG_DIR', str(tmp_path / 'state'))
    monkeypatch.setattr(user_config, 'root_for', lambda location: tmp_path / 'docs')
    target = tmp_path / 'docs' / 'settings.ini'
    target.parent.mkdir()
    original = b'\xef\xbb\xbf[Old]\r\nx=1\r\n'
    if existed:
        target.write_bytes(original)
    real_save = user_config._save_registry
    def fail(items):
        if conflict:
            target.write_bytes(b'[Other]\ny=3\n')
        raise PermissionError('PRIVATE registry commit failure')
    monkeypatch.setattr(user_config, '_save_registry', fail)
    result = user_config.write_config('documents', 'settings.ini', '[New]\ny=2', game_slug='fixture', mod_id='one')
    assert result['error_code'] == 'EXTERNAL_CONFIG_REGISTRY_SAVE_FAILED'
    assert result['written'] is False and result['verified'] is False
    assert result['rolled_back'] is (not conflict)
    assert 'PRIVATE' not in str(result)
    assert not (tmp_path / 'state' / 'external-config-registry.json').exists()
    if conflict:
        assert target.read_bytes() == b'[Other]\ny=3\n'
    elif existed:
        assert target.read_bytes() == original
    else:
        assert not target.exists()
    monkeypatch.setattr(user_config, '_save_registry', real_save)
    retry = user_config.write_config('documents', 'settings.ini', '[New]\ny=2', game_slug='fixture', mod_id='one')
    assert retry['written'] and retry['verified']
    assert user_config._load_registry()[0]['owners']['one']['sections'] == ['new']


@pytest.mark.parametrize('published', [True, False])
def test_uncertain_commit_or_failed_restore_is_not_reported_as_rollback(monkeypatch, tmp_path, published):
    monkeypatch.setattr(user_config, 'CONFIG_DIR', str(tmp_path / 'state'))
    monkeypatch.setattr(user_config, 'root_for', lambda location: tmp_path / 'docs')
    target = tmp_path / 'docs' / 'settings.ini'
    target.parent.mkdir()
    original = b'[Old]\r\nx=1\r\n'
    target.write_bytes(original)
    real_save = user_config._save_registry
    real_write = user_config._atomic_write_bytes
    def fail_save(items):
        if published:
            real_save(items)
        raise OSError('PRIVATE commit acknowledgement lost')
    def fail_restore(path, value):
        if value == original:
            raise PermissionError('PRIVATE cannot restore')
        real_write(path, value)
    monkeypatch.setattr(user_config, '_save_registry', fail_save)
    monkeypatch.setattr(user_config, '_atomic_write_bytes', fail_restore)
    result = user_config.write_config('documents', 'settings.ini', '[New]\ny=2', game_slug='fixture', mod_id='one')
    assert result['written'] is False and result['rolled_back'] is False
    assert result['state_unconfirmed'] is True and 'PRIVATE' not in str(result)
    assert b'[New]' in target.read_bytes()
    assert Path(result['backup_path']).read_bytes() == original
    assert bool(user_config._load_registry()) is published
