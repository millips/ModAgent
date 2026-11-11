"""Actual quick-scan receipts remain compatible with strict renderer validation."""
import json
import os
from pathlib import Path
import subprocess

import pytest

if not os.environ.get('MODAGENT_DATA_DIR'):
    raise RuntimeError('An isolated MODAGENT_DATA_DIR is required.')

from modagent import api, db, scanner
from modagent.config import Config


@pytest.mark.parametrize('missing_directory', [False, True])
@pytest.mark.parametrize('packages', [0, 3, 501])
def test_actual_scan_success_and_repeat_match_renderer(monkeypatch, tmp_path, packages, missing_directory):
    monkeypatch.setattr(db, 'DB_FILE', str(tmp_path / 'state.db'))
    db.init_db()
    monkeypatch.setattr(scanner, '_scan_steam_workshop', lambda *_: [])
    monkeypatch.setattr(scanner.nexus, 'search',
                        lambda *a, **kw: pytest.fail('No external lookup allowed'))
    root = tmp_path / 'game'
    root.mkdir()
    for index in range(packages):
        directory = root / 'BepInEx' / 'plugins' / f'Fixture{index:04d}'
        directory.mkdir(parents=True)
        (directory / 'fixture.dll').write_bytes(b'fixture')
    instance = 'scan-contract-fixture'
    monkeypatch.setattr(api, 'cfg', Config(game_root=str(root),game_slug='fixture',
        game_instance_id=instance, manual_mod_dirs={instance: [str(tmp_path / 'PRIVATE_FIXTURE')]}
        if missing_directory else {}))
    receipts = []
    for iteration in range(2):
        data = json.loads(api.call_tool('scan_existing_mods', {})['result'])
        expected = packages if iteration == 0 else 0
        assert data['imported'] == expected
        assert data['identified_total'] == expected
        assert len(data['identified']) == min(expected, 500)
        assert data['truncated'] is (expected > 500)
        assert len(db.get_installed_mods(instance)) == packages
        assert len(data['missing_roots']) == int(missing_directory)
        receipts.append(data)
    if missing_directory:
        restored = tmp_path / 'PRIVATE_FIXTURE' / 'RestoredPackage'
        restored.mkdir(parents=True)
        restored_file = restored / 'restored.dll'
        restored_file.write_bytes(b'restored')
        data = json.loads(api.call_tool('scan_existing_mods', {})['result'])
        assert data['missing_roots'] == []
        assert data['imported'] == 1
        assert len(db.get_installed_mods(instance)) == packages + 1
        assert api.cfg.manual_mod_dirs[instance] == [str(tmp_path / 'PRIVATE_FIXTURE')]
        assert restored_file.read_bytes() == b'restored'
        receipts.append(data)
    script = '''
      import {checkScanReceipt} from './electron/scripts/test-scan-receipt.mjs';
      import {checkPartialScan} from './electron/scripts/test-scan-partial.mjs';
      let input=''; for await(const chunk of process.stdin) input+=chunk;
      for(const receipt of JSON.parse(input)) {
        if(receipt.missing_roots.length) {
          for(const lang of ['en','zh-CN']) await checkPartialScan(receipt,lang);
        } else await checkScanReceipt(receipt,true);
      }
      console.log('ACTUAL_SUCCESS_RECEIPTS_PASSED');
    '''
    checked = subprocess.run(['node','--input-type=module','-e',script],
        input=json.dumps(receipts),text=True,capture_output=True,timeout=20,
        cwd=Path(__file__).resolve().parents[1])
    assert checked.returncode == 0, checked.stdout + checked.stderr
    assert 'ACTUAL_SUCCESS_RECEIPTS_PASSED' in checked.stdout
