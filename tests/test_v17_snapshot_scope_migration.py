import os
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault("MODAGENT_DATA_DIR", tempfile.mkdtemp(prefix="modagent-scope-test-"))
from modagent import snapshot
from modagent import db


@pytest.fixture
def store(monkeypatch, tmp_path):
    monkeypatch.setattr(snapshot, "SNAPSHOTS_DIR", str(tmp_path))
    for name in ("first", "second"):
        directory = tmp_path / "legacy" / name
        directory.mkdir(parents=True)
        (directory / "data.bin").write_bytes(name.encode())
    return tmp_path


def test_second_move_failure_restores_first(monkeypatch, store):
    rename = os.rename
    calls = []
    def fail_second(source, target):
        calls.append((source,target))
        if len(calls) == 2:
            raise PermissionError("injected locked folder")
        return rename(source,target)
    monkeypatch.setattr(snapshot.os,"rename",fail_second)
    with pytest.raises(PermissionError):
        snapshot.migrate_game_scope("legacy","instance")
    for name in ("first","second"):
        assert (store / "legacy" / name / "data.bin").read_bytes() == name.encode()
    assert list((store / "instance").iterdir()) == []


def test_success_and_existing_destination_preserved(store):
    target = store / "instance" / "first"
    target.mkdir(parents=True)
    (target / "data.bin").write_bytes(b"existing")
    snapshot.migrate_game_scope("legacy","instance")
    assert (target / "data.bin").read_bytes() == b"existing"
    assert (store / "legacy" / "first" / "data.bin").read_bytes() == b"first"
    assert (store / "instance" / "second" / "data.bin").read_bytes() == b"second"


def test_rollback_failure_is_explicit_and_preserves_bytes(monkeypatch, store):
    rename = os.rename
    calls = 0
    def fail_after_first(source,target):
        nonlocal calls
        calls += 1
        if calls > 1:
            raise PermissionError("injected")
        return rename(source,target)
    monkeypatch.setattr(snapshot.os,"rename",fail_after_first)
    with pytest.raises(RuntimeError,match="SNAPSHOT_SCOPE_RECOVERY_REQUIRED"):
        snapshot.migrate_game_scope("legacy","instance")
    assert sorted(p.read_bytes() for p in store.rglob("data.bin")) == [b"first",b"second"]


@pytest.mark.parametrize("scope",["..","../outside","C:\\outside","a/b"])
def test_path_scope_rejected(store,scope):
    with pytest.raises(ValueError):
        snapshot.migrate_game_scope("legacy",scope)
    assert len(list((store / "legacy").iterdir())) == 2


@pytest.mark.parametrize("fail_move", [False, True])
def test_database_commit_waits_for_snapshot_moves(monkeypatch, store, fail_move):
    monkeypatch.setattr(db,"DB_FILE",str(store / "state.db"))
    db.init_db()
    conn=db.get_conn()
    conn.execute("INSERT INTO sessions (id,title,game_slug) VALUES (?,?,?)",("fixture-session","Fixture","legacy"))
    conn.commit()
    conn.close()
    rename=os.rename
    calls=0
    def move(source,target):
        nonlocal calls
        calls+=1
        if fail_move and calls==2:
            raise PermissionError("injected move failure")
        return rename(source,target)
    monkeypatch.setattr(snapshot.os,"rename",move)
    migrate=lambda: db.migrate_game_scope("legacy","instance",before_commit=lambda:snapshot.migrate_game_scope("legacy","instance"))
    if fail_move:
        with pytest.raises(PermissionError):
            migrate()
    else:
        migrate()
    conn=db.get_conn()
    actual=conn.execute("SELECT game_slug FROM sessions WHERE id=?",("fixture-session",)).fetchone()[0]
    conn.close()
    expected="legacy" if fail_move else "instance"
    assert actual==expected
    for name in ("first","second"):
        assert (store / expected / name / "data.bin").read_bytes()==name.encode()


@pytest.mark.parametrize("fail_undo", [False, True])
def test_database_commit_failure_undoes_directory_move(monkeypatch, store, fail_undo):
    monkeypatch.setattr(db,"DB_FILE",str(store / "state.db"))
    db.init_db()
    connect=db.get_conn
    conn=connect()
    conn.execute("INSERT INTO sessions (id,title,game_slug) VALUES (?,?,?)",("fixture-session","Fixture","legacy"))
    conn.commit()
    conn.close()
    class FailCommit:
        def __init__(self): self.connection=connect()
        def execute(self,*args): return self.connection.execute(*args)
        def commit(self): raise OSError("injected commit failure")
        def rollback(self): return self.connection.rollback()
        def close(self): return self.connection.close()
    monkeypatch.setattr(db,"get_conn",FailCommit)
    if fail_undo:
        rename=os.rename
        def fail_reverse(source,target):
            if Path(source).parent.name=="instance":
                raise PermissionError("injected rollback lock")
            return rename(source,target)
        monkeypatch.setattr(snapshot.os,"rename",fail_reverse)
    with pytest.raises(RuntimeError if fail_undo else OSError,match="SNAPSHOT_SCOPE_RECOVERY_REQUIRED" if fail_undo else "commit failure"):
        db.migrate_game_scope("legacy","instance",before_commit=lambda:snapshot.migrate_game_scope("legacy","instance"))
    conn=connect()
    assert conn.execute("SELECT game_slug FROM sessions WHERE id=?",("fixture-session",)).fetchone()[0]=="legacy"
    conn.close()
    expected="instance" if fail_undo else "legacy"
    for name in ("first","second"):
        assert (store / expected / name / "data.bin").read_bytes()==name.encode()
