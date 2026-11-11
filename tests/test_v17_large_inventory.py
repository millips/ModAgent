"""Real file-tree scan/import checks; no game, account or remote service used."""
import json
import os
import time

import pytest

if not os.environ.get('MODAGENT_DATA_DIR'):
    raise RuntimeError('Set MODAGENT_DATA_DIR to an isolated directory first.')

from modagent import api, db, scanner


@pytest.mark.parametrize('failure_point', ['loader', 'package'])
def test_unreadable_loader_is_not_reported_complete(monkeypatch, tmp_path, failure_point):
    monkeypatch.setattr(db, 'DB_FILE', str(tmp_path / 'state.db'))
    db.init_db()
    monkeypatch.setattr(scanner, '_scan_steam_workshop', lambda *_: [])
    root = tmp_path / 'game'
    loader = root / 'BepInEx' / 'plugins'
    package = loader / 'Unreadable'
    package.mkdir(parents=True)
    payload = package / 'fixture.dll'
    payload.write_bytes(b'preserve')
    if failure_point == 'loader':
        original = os.listdir
        def denied(path):
            if os.path.normcase(os.path.abspath(path)) == os.path.normcase(str(loader)):
                raise PermissionError('fixture access denied')
            return original(path)
        monkeypatch.setattr(scanner.os, 'listdir', denied)
    else:
        original = os.scandir
        def denied(path):
            if os.path.normcase(os.path.abspath(path)) == os.path.normcase(str(package)):
                raise PermissionError('fixture access denied')
            return original(path)
        monkeypatch.setattr(scanner.os, 'scandir', denied)
    instance = 'unreadable-fixture'
    with api._inventory_scan_jobs_lock:
        api._inventory_scan_jobs[instance] = {
            'generation': 1, 'game_slug': 'fixture-large', 'status': 'running',
            'worker_alive': True, 'request': {'game_root': str(root),
                                            'game_slug': 'fixture-large'}}
    try:
        api._inventory_scan_worker(instance)
        state = api._inventory_scan_public_state(instance)
        assert state['status'] == 'failed', state
        assert 'error' in state
        assert not db.get_installed_mods(instance)
        assert payload.read_bytes() == b'preserve'
    finally:
        with api._inventory_scan_jobs_lock:
            api._inventory_scan_jobs.pop(instance, None)


def test_large_inventory_background_roundtrip(monkeypatch, tmp_path):
    monkeypatch.setattr(db, 'DB_FILE', str(tmp_path / 'state.db'))
    db.init_db()
    monkeypatch.setattr(scanner, '_scan_steam_workshop', lambda *_: [])
    monkeypatch.setattr(scanner.nexus, 'search',
                        lambda *a, **kw: pytest.fail('No remote lookup allowed'))
    root = tmp_path / 'game'
    expected = {}
    for package in range(250):
        folder = root / 'BepInEx' / 'plugins' / f'Author-Package{package:03d}-1.0.0'
        folder.mkdir(parents=True)
        for index in range(20):
            path = folder / f'asset{index:02d}.dll'
            path.write_bytes(f'{package}:{index}'.encode())
            expected[str(path)] = path.read_bytes()
    instance = 'large-inventory-fixture'
    timings = []
    try:
        for iteration in range(2):
            started = time.monotonic()
            state = api._queue_inventory_scan(str(root), 'fixture-large',
                                               game_instance_id=instance)
            queued_seconds = time.monotonic() - started
            assert queued_seconds < 1.0
            poll_seconds = []
            while state['status'] == 'running' and time.monotonic() - started < 60:
                before_poll = time.monotonic()
                state = api._inventory_scan_public_state(instance)
                poll_seconds.append(time.monotonic() - before_poll)
                time.sleep(0.01)
            assert state['status'] == 'completed', state
            assert max(poll_seconds, default=0) < 0.5
            assert state['detected'] == 250
            assert state['imported'] == (250 if iteration == 0 else 0)
            assert state['identified_count'] == (250 if iteration == 0 else 0)
            assert len(state['identified']) == (200 if iteration == 0 else 0)
            assert state['truncated'] is (iteration == 0)
            if iteration == 0:
                assert all(item['file_count'] == 20 for item in state['identified'])
            rows = db.get_installed_mods(instance)
            assert len(rows) == 250
            owned = [path for row in rows for path in json.loads(row.files_installed)]
            assert len(owned) == 5000
            assert set(owned) == set(expected)
            timings.append({'pass': iteration + 1, 'queue_seconds': queued_seconds,
                            'total_seconds': time.monotonic() - started,
                            'max_status_seconds': max(poll_seconds, default=0)})
        for path, content in expected.items():
            with open(path, 'rb') as handle:
                assert handle.read() == content
        print('LARGE_INVENTORY_METRICS ' + json.dumps(timings))
    finally:
        # Never remove the job or restore mocks while its worker is active.
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            with api._inventory_scan_jobs_lock:
                alive = api._inventory_scan_jobs.get(instance, {}).get('worker_alive')
            if not alive:
                break
            time.sleep(0.05)
        assert not alive, 'Scan worker did not finish within cleanup budget'
        with api._inventory_scan_jobs_lock:
            api._inventory_scan_jobs.pop(instance, None)
