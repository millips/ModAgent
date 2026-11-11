"""Incomplete trees must fail without importing partial inventory; retry recovers."""
import json
import os
from pathlib import Path
import subprocess

import pytest

if not os.environ.get('MODAGENT_DATA_DIR'):
    raise RuntimeError('An isolated MODAGENT_DATA_DIR is required.')

from modagent import api, db, scanner
from modagent.config import Config


def test_quick_scan_read_error_matches_renderer(monkeypatch, tmp_path):
    monkeypatch.setattr(db, 'DB_FILE', str(tmp_path / 'state.db'))
    db.init_db()
    root = tmp_path / 'game'
    package = root / 'BepInEx' / 'plugins' / 'Fixture'
    package.mkdir(parents=True)
    payload = package / 'fixture.dll'
    payload.write_bytes(b'preserve')
    instance = 'quick-scan-fixture'
    monkeypatch.setattr(api, 'cfg', Config(game_root=str(root), game_slug='fixture',
                                         game_instance_id=instance))
    original = os.scandir
    def denied(path):
        if os.path.normcase(os.path.abspath(path)) == os.path.normcase(str(package)):
            raise PermissionError('PRIVATE_FIXTURE')
        return original(path)
    monkeypatch.setattr(scanner.os, 'scandir', denied)
    envelope = api.call_tool('scan_existing_mods', {})
    result = json.loads(envelope['result'])
    assert result['status'] == 'failed'
    assert result['error_code'] == 'SCAN_DIRECTORY_UNREADABLE'
    assert 'PRIVATE_FIXTURE' not in envelope['result']
    assert not db.get_installed_mods(instance)
    assert payload.read_bytes() == b'preserve'
    script = '''
      import {checkScanReadError} from './electron/scripts/test-scan-read-error.mjs';
      let input = ''; for await (const chunk of process.stdin) input += chunk;
      for (const lang of ['zh-CN','en']) await checkScanReadError(JSON.parse(input),lang);
      console.log('ACTUAL_SCAN_RECEIPT_RENDERED');
    '''
    checked = subprocess.run(['node','--input-type=module','-e',script],
        input=json.dumps(result), text=True, capture_output=True, timeout=20,
        cwd=Path(__file__).resolve().parents[1])
    assert checked.returncode == 0, checked.stdout + checked.stderr
    assert 'ACTUAL_SCAN_RECEIPT_RENDERED' in checked.stdout


@pytest.mark.parametrize('layout', ['external-root', 'external-child', 'flat', 'overlay', 'stardew'])
def test_read_failure_preserves_inventory_and_retry_recovers(monkeypatch, tmp_path, layout):
    monkeypatch.setattr(db, 'DB_FILE', str(tmp_path / 'state.db'))
    db.init_db()
    monkeypatch.setattr(scanner, '_scan_steam_workshop', lambda *_: [])
    monkeypatch.setattr(scanner.nexus, 'search',
                        lambda *a, **kw: pytest.fail('No network lookup allowed'))
    root = tmp_path / 'game'
    healthy = root / 'BepInEx' / 'plugins' / 'Healthy' / 'healthy.dll'
    healthy.parent.mkdir(parents=True)
    healthy.write_bytes(b'healthy')
    extra = []
    slug = 'fixture-large'
    if layout.startswith('external'):
        external = tmp_path / 'manager-library'
        package = external / 'Package'
        extra = [str(external)]
        filename = 'fixture.dll'
        denied_root = external if layout == 'external-root' else package / 'nested'
    elif layout == 'flat':
        slug = 'skyrimspecialedition'
        package = root / 'Data'
        filename = 'fixture.esp'
        denied_root = package / 'nested'
    elif layout == 'overlay':
        slug = 'streetfighter6'
        package = root / 'natives'
        filename = 'fixture.tex.143230113'
        denied_root = package / 'nested'
    else:
        slug = 'stardewvalley'
        package = root / 'Mods' / 'ManifestPackage'
        filename = 'fixture.dll'
        denied_root = package / 'nested'
    package.mkdir(parents=True, exist_ok=True)
    denied_root.mkdir(parents=True, exist_ok=True)
    visible = package / filename
    visible.write_bytes(b'visible')
    hidden = denied_root / ('hidden-' + filename)
    hidden.write_bytes(b'hidden')
    if layout == 'stardew':
        (package / 'manifest.json').write_text(json.dumps({
            'Name': 'Manifest package', 'UniqueID': 'Fixture.Manifest', 'Version': '1.0'
        }), encoding='utf-8')
    instance = 'scan-read-fixture'
    db.add_mod(db.InstalledMod(id='existing', name='Existing', version='1',
                              snapshot_id='', game_slug=instance))
    original_scandir = os.scandir
    def denied(path):
        if os.path.normcase(os.path.abspath(path)) == os.path.normcase(str(denied_root)):
            raise PermissionError('private-fixture-path-denied')
        return original_scandir(path)
    def run_worker():
        with api._inventory_scan_jobs_lock:
            api._inventory_scan_jobs[instance] = {
                'generation': 1, 'game_slug': slug, 'status': 'running',
                'worker_alive': True, 'request': {'game_root': str(root),
                    'game_slug': slug, 'extra_roots': extra}}
        api._inventory_scan_worker(instance)
        return api._inventory_scan_public_state(instance)
    try:
        monkeypatch.setattr(scanner.os, 'scandir', denied)
        state = run_worker()
        assert state['status'] == 'failed', state
        assert state['error_code'] == 'SCAN_DIRECTORY_UNREADABLE'
        assert 'private-fixture' not in state['error']
        assert 'permissions' in state['error']
        failed_state = state
        assert [row.id for row in db.get_installed_mods(instance)] == ['existing']
        monkeypatch.setattr(scanner.os, 'scandir', original_scandir)
        state = run_worker()
        assert state['status'] == 'completed', state
        assert state['imported'] >= 1
        rows = db.get_installed_mods(instance)
        owned = {p for row in rows for p in json.loads(row.files_installed or '[]')}
        assert str(healthy) in owned
        if layout != 'overlay':
            assert str(visible) in owned and str(hidden) in owned
        else:
            assert state['unidentified_count'] >= 1
        assert visible.read_bytes() == b'visible'
        assert hidden.read_bytes() == b'hidden'
        extra.append(str(tmp_path / 'PRIVATE_FIXTURE_missing'))
        partial_state = run_worker()
        assert partial_state['status'] == 'completed'
        assert len(partial_state['missing_roots']) == 1
        assert partial_state['imported'] == 0
        script = '''
          import {checkBackgroundReceipt} from './electron/scripts/test-inventory-feedback.mjs';
          let input=''; for await(const chunk of process.stdin) input+=chunk;
          for(const data of JSON.parse(input))for(const lang of ['en','zh-CN'])
            await checkBackgroundReceipt(data,lang);
          console.log('ACTUAL_BACKGROUND_RECEIPTS_PASSED');
        '''
        checked = subprocess.run(['node','--input-type=module','-e',script],
            input=json.dumps([failed_state,state,partial_state]),text=True,capture_output=True,timeout=20,
            cwd=Path(__file__).resolve().parents[1])
        assert checked.returncode == 0, checked.stdout + checked.stderr
        assert 'ACTUAL_BACKGROUND_RECEIPTS_PASSED' in checked.stdout
    finally:
        with api._inventory_scan_jobs_lock:
            api._inventory_scan_jobs.pop(instance, None)
