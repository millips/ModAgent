"""Real SQLite trigger failures must roll back and close write connections."""
import os
import sqlite3
import pytest

if not os.environ.get('MODAGENT_DATA_DIR'):
    raise RuntimeError('An isolated MODAGENT_DATA_DIR is required.')

from modagent import db


@pytest.mark.parametrize('action',['install','uninstall','snapshot_restore'])
def test_sql_failure_releases_writer_and_preserves_inventory(monkeypatch,tmp_path,action):
    database=tmp_path/'state.db'
    monkeypatch.setattr(db,'DB_FILE',str(database))
    db.init_db()
    db.add_mod(db.InstalledMod(id='existing',name='Original',version='1',snapshot_id='',game_slug='fixture'))
    db.upsert_mod_source_binding('fixture','existing','github','fixture/original',
                                'https://github.com/fixture/original',confidence=1)
    with sqlite3.connect(database) as setup:
        setup.execute("CREATE TRIGGER reject_fixture_log BEFORE INSERT ON operation_log "
                      f"WHEN NEW.action='{action}' BEGIN SELECT RAISE(ABORT,'fixture log failure'); END")
    setup.close()
    original_get_conn=db.get_conn
    held=[]
    def tracked():
        conn=original_get_conn(); held.append(conn); return conn
    monkeypatch.setattr(db,'get_conn',tracked)
    def mutate():
        if action=='install':
            db.add_mod(db.InstalledMod(id='existing',name='Replacement',version='2',snapshot_id='',game_slug='fixture'))
        elif action=='uninstall':db.remove_mod('existing','fixture')
        else:db.log_operation('snapshot_restore',{'snapshot_id':'fixture'})
    try:
        with pytest.raises(sqlite3.IntegrityError,match='fixture log failure'):
            mutate()
        assert held
        with pytest.raises(sqlite3.ProgrammingError,match='closed'):
            held[-1].execute('SELECT 1')
        # A second connection can immediately acquire the write lock after failure.
        with sqlite3.connect(database,timeout=0.1) as probe:
            probe.execute('BEGIN IMMEDIATE')
            assert probe.execute("SELECT name FROM installed_mods WHERE id='existing'").fetchone()==('Original',)
            assert probe.execute("SELECT COUNT(*) FROM mod_source_bindings WHERE mod_id='existing'").fetchone()==(1,)
            probe.execute('DROP TRIGGER reject_fixture_log')
        probe.close()
        mutate()
        if action=='uninstall':
            assert db.get_mod('existing','fixture') is None
        elif action=='install':
            assert db.get_mod('existing','fixture').name=='Replacement'
        else:
            assert db.get_operation_log(1)[0]['action']=='snapshot_restore'
    finally:
        for conn in held:conn.close()


def test_source_binding_failure_releases_connection_and_keeps_old_binding(monkeypatch, tmp_path):
    database = tmp_path / 'binding.db'
    monkeypatch.setattr(db, 'DB_FILE', str(database))
    db.init_db()
    db.upsert_mod_source_binding('fixture', 'local', 'nexus', '123')
    with sqlite3.connect(database) as setup:
        setup.execute("CREATE TRIGGER reject_binding BEFORE INSERT ON mod_source_bindings "
                      "BEGIN SELECT RAISE(ABORT,'fixture binding failure'); END")
    setup.close()
    original = db.get_conn
    held = []
    def tracked():
        conn = original(); held.append(conn); return conn
    monkeypatch.setattr(db, 'get_conn', tracked)
    try:
        with pytest.raises(sqlite3.IntegrityError, match='fixture binding failure'):
            db.upsert_mod_source_binding('fixture', 'local', 'nexus', '456')
        with pytest.raises(sqlite3.ProgrammingError, match='closed'):
            held[-1].execute('SELECT 1')
        with sqlite3.connect(database, timeout=0.1) as probe:
            probe.execute('BEGIN IMMEDIATE')
            assert probe.execute('SELECT source_key FROM mod_source_bindings').fetchone() == ('123',)
            probe.execute('DROP TRIGGER reject_binding')
        probe.close()
        db.upsert_mod_source_binding('fixture', 'local', 'nexus', '456')
        assert db.get_mod_source_binding('local', 'fixture')['source_key'] == '456'
    finally:
        for conn in held: conn.close()
