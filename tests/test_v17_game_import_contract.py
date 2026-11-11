"""Manual import: real persistence/worker/inventory, renderer receipt contract."""
import json
import os
from pathlib import Path
import subprocess
import threading
import time

import pytest
from fastapi.testclient import TestClient

if not os.environ.get('MODAGENT_DATA_DIR'):
    raise RuntimeError('An isolated MODAGENT_DATA_DIR is required.')

from modagent import api, config, db, scanner


@pytest.mark.parametrize('packages,denied', [(0, False), (3, False), (3, True)])
def test_import_persists_and_real_worker_matches_renderer(monkeypatch, tmp_path, packages, denied):
    monkeypatch.setattr(db, 'DB_FILE', str(tmp_path / 'state.db'))
    monkeypatch.setattr(config, 'CONFIG_DIR', str(tmp_path))
    monkeypatch.setattr(config, 'CONFIG_FILE', str(tmp_path / 'config.json'))
    monkeypatch.setattr(api, 'cfg', config.Config())
    db.init_db()
    monkeypatch.setattr(scanner, '_scan_steam_workshop', lambda *_: [])
    monkeypatch.setattr(scanner.nexus, 'search', lambda *a, **k: pytest.fail('No external lookup allowed'))
    root = tmp_path / 'game'
    root.mkdir()
    exe = root / 'Fixture.exe'
    exe.write_bytes(b'synthetic marker; not a runnable game')
    files = [exe]
    for index in range(packages):
        package = root / 'BepInEx' / 'plugins' / f'Fixture{index}'
        package.mkdir(parents=True)
        payload = package / 'fixture.dll'
        payload.write_bytes(b'fixture')
        files.append(payload)
    before = {p: p.read_bytes() for p in files}
    release, finished = threading.Event(), threading.Event()
    original_worker = api._inventory_scan_worker
    def gated_worker(instance):
        try:
            if not release.wait(10):
                raise RuntimeError('fixture worker gate timed out')
            original_worker(instance)
        finally:
            finished.set()
    monkeypatch.setattr(api, '_inventory_scan_worker', gated_worker)
    original_scandir = os.scandir
    denied_root = root / 'BepInEx' / 'plugins' / 'Fixture0'
    def scandir(path):
        if denied and os.path.normcase(os.path.abspath(path)) == os.path.normcase(str(denied_root)):
            raise PermissionError('PRIVATE_FIXTURE')
        return original_scandir(path)
    monkeypatch.setattr(scanner.os, 'scandir', scandir)
    instance = None
    try:
        client = TestClient(api.app)
        response = client.post('/games/import', json={'game_name': 'Fixture', 'game_root': str(root),
            'executable': str(exe), 'game_slug': 'fixture'})
        assert response.status_code == 200, response.text
        imported = response.json()
        assert imported['saved'] is True
        instance = imported['game']['game_instance_id']
        assert imported['mod_scan']['status'] == 'running'
        assert imported['mod_scan']['game_instance_id'] == instance
        saved = json.loads((tmp_path / 'config.json').read_text(encoding='utf-8'))
        assert saved['game_instance_id'] == instance
        assert len(saved['manual_games']) == 1
        status = client.get('/status').json()
        assert status['game_instance_id'] == instance
        assert status['game_root'] == str(root)
        assert not db.get_installed_mods(instance)
        release.set()
        assert finished.wait(10), 'real background worker did not finish'
        state = client.get('/mods/scan-status', params={'game_instance_id': instance}).json()
        assert state['status'] == ('failed' if denied else 'completed'), state
        assert len(db.get_installed_mods(instance)) == (0 if denied else packages)
        receipts = [imported, {**imported, 'mod_scan': state}]
        if denied:
            assert state['error_code'] == 'SCAN_DIRECTORY_UNREADABLE'
            assert 'PRIVATE_FIXTURE' not in json.dumps(state)
            monkeypatch.setattr(scanner.os, 'scandir', original_scandir)
            finished.clear()
            api._queue_inventory_scan(str(root), 'fixture', game_instance_id=instance)
            assert finished.wait(10)
            state = client.get('/mods/scan-status', params={'game_instance_id': instance}).json()
            assert state['status'] == 'completed'
            assert state['imported'] == packages
            assert len(db.get_installed_mods(instance)) == packages
            receipts.append({**imported, 'mod_scan': state})
        assert before == {p: p.read_bytes() for p in files}
        script = '''
          import assert from 'node:assert/strict';
          import {gameImportFeedback} from './electron/src/components/gameImportFeedback.mjs';
          let input='';for await(const chunk of process.stdin)input+=chunk;
          for(const receipt of JSON.parse(input))for(const lang of ['en','zh-CN']){
            const feedback=gameImportFeedback(receipt,lang), scan=receipt.mod_scan;
            if(scan.status==='running')assert.equal(feedback.monitor,true);
            else if(scan.status==='failed'){
              assert.equal(feedback.kind,'warn');assert.match(feedback.message,/SCAN_DIRECTORY_UNREADABLE/);
            }else{
              assert.equal(feedback.kind,'success');assert.equal(feedback.monitor,false);
              assert.ok(feedback.message.includes(String(scan.imported)));
            }
            assert.doesNotMatch(feedback.message,/PRIVATE_FIXTURE|SCAN_STATUS_UNCONFIRMED/);
            if(lang==='en')assert.doesNotMatch(feedback.message,/[\\u4e00-\\u9fff]/);
          }
          console.log('REAL_IMPORT_RECEIPTS_PASSED');
        '''
        checked = subprocess.run(['node', '--input-type=module', '-e', script], input=json.dumps(receipts),
            text=True, capture_output=True, timeout=20, cwd=Path(__file__).resolve().parents[1])
        assert checked.returncode == 0, checked.stdout + checked.stderr
        assert 'REAL_IMPORT_RECEIPTS_PASSED' in checked.stdout
    finally:
        release.set()
        if instance:
            assert finished.wait(10), 'worker still running at teardown'
            with api._inventory_scan_jobs_lock:
                api._inventory_scan_jobs.pop(instance, None)


def test_invalid_directory_does_not_save_or_scan(monkeypatch, tmp_path):
    monkeypatch.setattr(config, 'CONFIG_DIR', str(tmp_path))
    monkeypatch.setattr(config, 'CONFIG_FILE', str(tmp_path / 'config.json'))
    original = config.Config(game_name='Original', game_root=str(tmp_path / 'original'))
    monkeypatch.setattr(api, 'cfg', original)
    monkeypatch.setattr(api, '_queue_inventory_scan', lambda *a, **k: pytest.fail('Rejected import queued a scan'))
    response = TestClient(api.app).post('/games/import', json={'game_name':'Invalid','game_root':str(tmp_path / 'missing')})
    assert response.status_code == 400
    assert api.cfg is original and api.cfg.game_name == 'Original'
    assert not (tmp_path / 'config.json').exists()
