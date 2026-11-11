"""Real local snapshot lifecycle checked by the renderer's receipt validators."""
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

if not os.environ.get('MODAGENT_DATA_DIR'):
    raise RuntimeError('Set MODAGENT_DATA_DIR to a fresh isolated test directory before importing ModAgent.')

from modagent import api, db, snapshot, tools, user_config
from modagent.config import Config


@pytest.mark.parametrize('replace_file', [False, True])
def test_real_snapshot_lifecycle_matches_renderer(monkeypatch, tmp_path, replace_file):
    node = shutil.which('node')
    assert node, 'Node is required to verify the actual renderer contract'
    monkeypatch.setattr(db, 'DB_FILE', str(tmp_path / 'state.db'))
    monkeypatch.setattr(snapshot, 'SNAPSHOTS_DIR', str(tmp_path / 'snapshots'))
    # Exclude Steam and personal Documents/AppData. File snapshots remain real.
    monkeypatch.setattr(snapshot, '_workshop_state', lambda root: None)
    monkeypatch.setattr(user_config, 'capture_snapshot', lambda *a: {})
    monkeypatch.setattr(user_config, 'preview_snapshot', lambda *a: {'action_count': 0})
    monkeypatch.setattr(user_config, 'restore_snapshot', lambda *a: {'complete': True})
    db.init_db()
    game = tmp_path / 'game'
    plugins = game / 'BepInEx' / 'plugins'
    plugins.mkdir(parents=True)
    original = plugins / 'fixture.dll'
    original.write_bytes(b'original fixture content')
    save = game / 'personal-save.txt'
    save.write_bytes(b'preserve this save')
    cfg = Config(game_root=str(game), game_slug='contract-fixture')
    sid = json.loads(tools.execute('snapshot_create', {'trigger_mod_name': 'Contract test'}, cfg))['snapshot_id']
    rows = api.list_snapshots()
    usage = api.snapshot_storage()
    assert len(rows) == 1 and rows[0]['id'] == sid
    old_stat = original.stat()
    if replace_file:
        original.unlink()
    original.write_bytes(b'changed! fixture content')
    # Equal size and timestamp must not hide changed bytes from restore planning.
    assert original.stat().st_size == old_stat.st_size
    os.utime(original, (old_stat.st_atime, old_stat.st_mtime))
    added = plugins / 'new.dll'
    added.write_bytes(b'added after snapshot')
    preview = api.preview_snapshot_restore(sid)
    assert preview['to_delete_count'] == 1
    assert preview['to_restore_count'] == 1
    assert original.read_bytes() == b'changed! fixture content' and added.exists()
    receipt = json.loads(tools.execute('snapshot_restore', {
        'snapshot_id': sid, 'confirmed': True, 'confirmation_token': preview['confirmation_token'],
    }, cfg))
    assert receipt['complete'] is True, receipt
    assert original.read_bytes() == b'original fixture content'
    assert not added.exists()
    assert save.read_bytes() == b'preserve this save'
    replay = json.loads(tools.execute('snapshot_restore', {
        'snapshot_id': sid, 'confirmed': True, 'confirmation_token': preview['confirmation_token'],
    }, cfg))
    assert replay.get('error') == 'rollback_confirmation_invalid'
    script = """
import assert from 'node:assert/strict';
import {validateSnapshotList, validSnapshotStorage} from './electron/src/components/snapshotList.mjs';
import {validateSnapshotReceipt} from './electron/src/components/snapshotReceipt.mjs';
import {validateSnapshotPreview} from './electron/src/components/snapshotPreview.mjs';
let input=''; for await(const chunk of process.stdin)input+=chunk;
const data=JSON.parse(input);
validateSnapshotList(data.rows);
assert.equal(validSnapshotStorage(data.usage),true);
validateSnapshotReceipt(data.receipt,data.sid);
validateSnapshotPreview(data.preview,data.sid);
assert.equal(data.receipt.complete,true);
console.log('REAL SNAPSHOT FRONTEND CONTRACT PASSED');
"""
    checked = subprocess.run([node, '--input-type=module', '-e', script],
        input=json.dumps({'sid': sid, 'rows': rows, 'usage': usage, 'receipt': receipt, 'preview': preview}),
        text=True, capture_output=True, cwd=Path(__file__).resolve().parents[1], timeout=20)
    assert checked.returncode == 0, checked.stdout + checked.stderr
    assert 'REAL SNAPSHOT FRONTEND CONTRACT PASSED' in checked.stdout


def test_incremental_snapshot_preserves_changed_bytes(monkeypatch, tmp_path):
    monkeypatch.setattr(db, 'DB_FILE', str(tmp_path / 'state.db'))
    monkeypatch.setattr(snapshot, 'SNAPSHOTS_DIR', str(tmp_path / 'snapshots'))
    monkeypatch.setattr(snapshot, '_workshop_state', lambda root: None)
    monkeypatch.setattr(user_config, 'capture_snapshot', lambda *a: {})
    db.init_db()
    game = tmp_path / 'game'
    relative = Path('BepInEx/plugins/fixture.dll')
    managed = game / relative
    managed.parent.mkdir(parents=True)
    managed.write_bytes(b'old contents')
    first = snapshot.snapshot_create(str(game), 'incremental', trigger_mod_name='first')
    stamp = managed.stat()
    managed.write_bytes(b'new contents')
    os.utime(managed, (stamp.st_atime, stamp.st_mtime))
    second = snapshot.snapshot_create(str(game), 'incremental', trigger_mod_name='second')
    assert first != second
    first_file = Path(snapshot.find_snapshot_dir(first, 'incremental')) / relative
    second_file = Path(snapshot.find_snapshot_dir(second, 'incremental')) / relative
    assert first_file.read_bytes() == b'old contents'
    assert second_file.read_bytes() == b'new contents', 'Incremental snapshot linked stale bytes'
    third = snapshot.snapshot_create(str(game), 'incremental', trigger_mod_name='third')
    third_file = Path(snapshot.find_snapshot_dir(third, 'incremental')) / relative
    assert third_file.read_bytes() == b'new contents'
    assert second_file.stat().st_ino == third_file.stat().st_ino, 'Identical files should still deduplicate on this filesystem'


def test_workshop_unavailable_blocks_before_file_changes(monkeypatch, tmp_path):
    monkeypatch.setattr(db, 'DB_FILE', str(tmp_path / 'state.db'))
    monkeypatch.setattr(snapshot, 'SNAPSHOTS_DIR', str(tmp_path / 'snapshots'))
    monkeypatch.setattr(snapshot, '_workshop_state', lambda root: {'appid': '123', 'ids': ['456']})
    monkeypatch.setattr(user_config, 'capture_snapshot', lambda *a: {})
    monkeypatch.setattr(user_config, 'preview_snapshot', lambda *a: {'action_count': 0})
    monkeypatch.setattr(user_config, 'restore_snapshot', lambda *a: pytest.fail('Must not modify external configurations'))
    db.init_db()
    game = tmp_path / 'game'
    managed = game / 'BepInEx/plugins/test.dll'
    managed.parent.mkdir(parents=True)
    managed.write_bytes(b'original')
    sid = snapshot.snapshot_create(str(game), 'workshop-fixture')
    managed.write_bytes(b'changed')
    added = managed.with_name('added.dll')
    added.write_bytes(b'preserve until preview is known')
    def unavailable(*args):
        raise PermissionError('private-path-must-not-leak')
    monkeypatch.setattr(snapshot, '_workshop_diff', unavailable)
    preview = api.preview_snapshot_restore(sid)
    assert preview['workshop']['preview_unavailable'] is True
    assert 'private-path' not in json.dumps(preview)
    with pytest.raises(RuntimeError, match='^SNAPSHOT_WORKSHOP_PREVIEW_UNAVAILABLE$'):
        snapshot.snapshot_restore(sid)
    assert managed.read_bytes() == b'changed'
    assert added.read_bytes() == b'preserve until preview is known'
