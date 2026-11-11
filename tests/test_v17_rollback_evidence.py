"""Inspectable real-file rollback evidence; no external accounts or games."""
import hashlib
import json
import os
from pathlib import Path

import pytest

if not os.environ.get('MODAGENT_DATA_DIR'):
    raise RuntimeError('Isolated data directory required')

from modagent import config, db, snapshot, tools, user_config


@pytest.mark.parametrize('deny_restore', [False, True])
def test_rollback_before_after_evidence(monkeypatch, tmp_path, deny_restore):
    monkeypatch.setattr(config, 'CONFIG_DIR', str(tmp_path / 'state'))
    monkeypatch.setattr(config, 'CONFIG_FILE', str(tmp_path / 'state/config.json'))
    monkeypatch.setattr(db, 'DB_FILE', str(tmp_path / 'state.db'))
    monkeypatch.setattr(snapshot, 'SNAPSHOTS_DIR', str(tmp_path / 'snapshots'))
    monkeypatch.setattr(snapshot, '_workshop_state', lambda *_: None)
    monkeypatch.setattr(user_config, 'capture_snapshot', lambda *_: [])
    monkeypatch.setattr(user_config, 'restore_snapshot', lambda *_: {'complete': True})
    db.init_db()
    root = tmp_path / 'game'
    mod = root / 'Pal/Content/Paks/~mods/fixture.pak'
    mod.parent.mkdir(parents=True)
    mod.write_bytes(b'BEFORE: original mod bytes\n')
    save = root / 'Pal/Saved/save.dat'
    save.parent.mkdir(parents=True)
    save.write_bytes(b'PLAYER SAVE: must never change\n')
    cfg = config.Config(game_root=str(root), game_slug='palworld', game_name='Palworld',
                        game_instance_id=config.make_game_instance_id(str(root)))
    config.save(cfg)

    def state():
        return {'files': {p.relative_to(root).as_posix(): {
            'text': p.read_text(), 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()
        } for p in sorted(root.rglob('*')) if p.is_file()},
            'inventory': sorted(m.id for m in db.get_installed_mods(cfg.game_instance_id))}

    before = state()
    sid = json.loads(tools.execute('snapshot_create', {}, cfg))['snapshot_id']
    # Controlled post-install state; this test exercises real snapshot rollback,
    # not archive installation or download services.
    mod.write_bytes(b'AFTER: replacement mod bytes\n')
    added = mod.with_name('new.pak')
    added.write_bytes(b'AFTER: newly added mod\n')
    db.add_mod(db.InstalledMod(id='fixture-new', name='Fixture', version='2',
        snapshot_id=sid, game_slug=cfg.game_instance_id,
        files_installed=json.dumps([str(mod), str(added)])))
    changed = state()
    gate = json.loads(tools.execute('snapshot_restore', {'snapshot_id': sid}, cfg))
    assert gate['requires_confirmation']
    assert state() == changed, 'Preview must not modify files or inventory'
    denied = json.loads(tools.execute('snapshot_restore', {
        'snapshot_id': sid, 'confirmed': True, 'confirmation_token': 'invalid'}, cfg))
    assert denied['error'] == 'rollback_confirmation_invalid'
    assert state() == changed
    copy = snapshot.shutil.copy2
    def copy_with_fault(src, dst, *args, **kwargs):
        if deny_restore and Path(dst) == mod:
            raise PermissionError(13, 'Injected restoration permission failure', str(dst))
        return copy(src, dst, *args, **kwargs)
    monkeypatch.setattr(snapshot.shutil, 'copy2', copy_with_fault)
    receipt = json.loads(tools.execute('snapshot_restore', {
        'snapshot_id': sid, 'confirmed': True,
        'confirmation_token': gate['confirmation_token']}, cfg))
    after = state()
    assert after['files']['Pal/Saved/save.dat'] == before['files']['Pal/Saved/save.dat']
    assert snapshot.snapshot_restore_preview(sid) is not None
    if deny_restore:
        assert receipt['complete'] is False and receipt['status'] == 'incomplete'
        assert receipt['pending_restore'] and receipt['failed']['restore']
        assert after['inventory'] == changed['inventory']
        assert mod.read_bytes() == b'AFTER: replacement mod bytes\n'
    else:
        assert receipt['complete'] is True
        assert after == before, 'All file bytes and inventory must equal baseline'
    evidence = {'case': 'injected_permission_failure' if deny_restore else 'success',
        'fixture': str(tmp_path), 'before': before, 'after_change': changed,
        'after_rollback': after, 'receipt': receipt}
    if deny_restore:
        monkeypatch.setattr(snapshot.shutil, 'copy2', copy)
        retry_gate = json.loads(tools.execute('snapshot_restore', {'snapshot_id': sid}, cfg))
        assert state() == after
        retry = json.loads(tools.execute('snapshot_restore', {
            'snapshot_id': sid, 'confirmed': True,
            'confirmation_token': retry_gate['confirmation_token']}, cfg))
        assert retry['complete'] is True
        assert state() == before
        evidence['after_fault_removed_and_reconfirmed'] = state()
        evidence['retry_receipt'] = retry
    (tmp_path / 'evidence.json').write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(evidence, ensure_ascii=False))
