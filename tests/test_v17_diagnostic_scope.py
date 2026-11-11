"""A task's diagnostic inventory stays with its captured installation identity."""
import json
import os
import zipfile
import pytest

if not os.environ.get('MODAGENT_DATA_DIR'):
    raise RuntimeError('An isolated MODAGENT_DATA_DIR is required.')

from modagent import config, db, tools


@pytest.mark.parametrize('export', [False, True])
def test_diagnostic_uses_task_instance_after_current_game_changes(monkeypatch, tmp_path, export):
    monkeypatch.setattr(config, 'CONFIG_DIR', str(tmp_path))
    monkeypatch.setattr(config, 'CONFIG_FILE', str(tmp_path / 'config.json'))
    monkeypatch.setattr(db, 'DB_FILE', str(tmp_path / 'state.db'))
    db.init_db()
    roots = [tmp_path / 'installation-a', tmp_path / 'installation-b']
    for root in roots: root.mkdir()
    scopes = [config.make_game_instance_id(str(root)) for root in roots]
    for scope, title in zip(scopes, ['Task A mod', 'Current B mod']):
        db.add_mod(db.InstalledMod(id='same-id', name=title, version='1', snapshot_id='', game_slug=scope))
        db.upsert_mod_source_binding(scope, 'same-id', 'nexus', '123' if scope == scopes[0] else '456')
    task_cfg = config.Config(game_slug='fixture', game_instance_id=scopes[0], game_root=str(roots[0]))
    config.save(config.Config(game_slug='fixture', game_instance_id=scopes[1], game_root=str(roots[1])))
    seen = {}
    def diagnose(root, slug, mods, *args, **kwargs):
        seen.update(root=root, slug=slug, names=[m.name for m in mods])
        return {'fixture':True}
    def strategy(report, mods, bindings):
        seen['bindings'] = bindings
        return {}
    monkeypatch.setattr(tools.game_diagnostics, 'game_diagnose', diagnose)
    def export_bundle(root, slug, cfg, mods, *args, **kwargs):
        return diagnose(root, slug, mods)
    monkeypatch.setattr(tools.game_diagnostics, 'export_diag_bundle', export_bundle)
    from modagent import diagnostic_impact
    monkeypatch.setattr(diagnostic_impact, 'build_diagnostic_strategy', strategy)
    result = json.loads(tools.execute('game_diagnose', {'export':export}, task_cfg))
    assert result['fixture'] is True
    assert seen['root'] == str(roots[0]) and seen['slug'] == 'fixture'
    assert seen['names'] == ['Task A mod']
    if not export: assert seen['bindings']['same-id']['source_key'] == '123'
    assert config.load().game_instance_id == scopes[1]


@pytest.mark.parametrize('secret', ['fixture-private-credential-12345', 'fixture-私密-"quoted"\\path\nkey'])
def test_real_tool_report_and_export_remove_configured_secrets(monkeypatch, tmp_path, secret):
    monkeypatch.setattr(config, 'CONFIG_DIR', str(tmp_path))
    monkeypatch.setattr(config, 'CONFIG_FILE', str(tmp_path / 'config.json'))
    monkeypatch.setattr(db, 'DB_FILE', str(tmp_path / 'state.db'))
    monkeypatch.setattr(tools.game_diagnostics, 'CONFIG_DIR', str(tmp_path))
    db.init_db()
    root = tmp_path / 'game'
    log = root / 'BepInEx' / 'LogOutput.log'
    log.parent.mkdir(parents=True)
    log.write_text('[Error : FixtureMod] NullReferenceException in FixtureMod.Run()\n'
                   + 'Request credential=' + secret, encoding='utf-8')
    original = log.read_bytes()
    scope = config.make_game_instance_id(str(root))
    cfg = config.Config(game_root=str(root), game_slug='fixture', game_instance_id=scope,
                        llm_api_key=secret)
    db.add_mod(db.InstalledMod(id='fixture-mod', name='FixtureMod', version='1',
        snapshot_id='', game_slug=scope, files_installed=json.dumps([str(root / 'FixtureMod.dll')])))
    db.log_operation('fixture', {'detail':'Request credential=' + secret})
    report = json.loads(tools.execute('game_diagnose', {}, cfg))
    assert report['frameworks'] == ['BepInEx']
    assert report['findings'][0]['error_count'] >= 1
    assert any(m['name']=='FixtureMod' for m in report['findings'][0]['attributed_mods'])
    exported = json.loads(tools.execute('game_diagnose', {'export':True}, cfg))
    bundle = tmp_path / 'diagnostics' / os.path.basename(exported['bundle'])
    assert bundle.is_file() and bundle.stat().st_size == exported['size_bytes']
    with zipfile.ZipFile(bundle) as archive:
        assert set(exported['contains']) == set(archive.namelist())
        texts = {name:archive.read(name).decode('utf-8') for name in archive.namelist()}
    manifest = json.loads(texts['manifest.json'])
    operations = json.loads(texts['operation_log.json'])
    for operation in operations:
        assert secret not in json.dumps(json.loads(operation['details']), ensure_ascii=False)
    assert manifest['installed_mods'][0]['name'] == 'FixtureMod'
    assert manifest['config_redacted']['llm_api_key'] == '***REDACTED***'
    for name, text in texts.items(): assert secret not in text, name
    assert log.read_bytes() == original


def test_unreadable_log_is_not_reported_as_clean_or_exported(monkeypatch, tmp_path):
    root = tmp_path / 'game'
    bad = root / 'BepInEx' / 'LogOutput.log'
    good = root / 'MelonLoader' / 'Latest.log'
    for path in [bad, good]:
        path.parent.mkdir(parents=True)
        path.write_text('[Error] fixture error', encoding='utf-8')
    original_open = open
    def guarded_open(path, *args, **kwargs):
        if os.path.normcase(os.path.abspath(path)) == os.path.normcase(str(bad)):
            raise PermissionError('PRIVATE_FIXTURE')
        return original_open(path, *args, **kwargs)
    monkeypatch.setattr('builtins.open', guarded_open)
    report = tools.game_diagnostics.game_diagnose(str(root), 'fixture', [])
    assert report.get('complete') is False
    assert report['read_errors'][0]['error_code'] == 'DIAGNOSTIC_LOG_UNREADABLE'
    assert [f['framework'] for f in report['findings']] == ['MelonLoader']
    assert report['findings'][0]['error_count'] == 1
    assert 'PRIVATE_FIXTURE' not in json.dumps(report)
    output = tmp_path / 'exports'
    result = tools.game_diagnostics.export_diag_bundle(str(root), 'fixture', out_dir=str(output))
    assert result.get('error_code') == 'DIAGNOSTIC_LOG_UNREADABLE'
    assert not result.get('bundle')
    assert not list(output.iterdir())
    monkeypatch.setattr('builtins.open', original_open)
    recovered = tools.game_diagnostics.game_diagnose(str(root), 'fixture', [])
    assert recovered['complete'] is True and not recovered['read_errors']
    assert len(recovered['findings']) == 2
