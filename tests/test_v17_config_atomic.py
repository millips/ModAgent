"""Real temporary configuration files; no user credentials or game mutations."""
import json
import os
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.setdefault("MODAGENT_DATA_DIR", tempfile.mkdtemp(prefix="modagent-config-atomic-"))
from modagent import config


@pytest.fixture
def config_file(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "CONFIG_DIR", str(tmp_path))
    file = tmp_path / "config.json"
    monkeypatch.setattr(config, "CONFIG_FILE", str(file))
    file.write_text('{"llm_model":"original"}', encoding="utf-8")
    return file


@pytest.mark.parametrize("failure", ["serialize", "flush", "replace"])
def test_failed_save_preserves_file(monkeypatch, config_file, failure):
    before = config_file.read_bytes()
    def fail(*args, **kwargs):
        raise OSError("injected disk failure")
    if failure == "serialize":
        monkeypatch.setattr(config.json, "dump", fail)
    elif failure == "flush":
        monkeypatch.setattr(config.os, "fsync", fail)
    else:
        monkeypatch.setattr(config.os, "replace", fail)
    with pytest.raises(OSError):
        config.save(config.Config(llm_model="new"))
    assert config_file.read_bytes() == before
    assert list(config_file.parent.glob(".config-*.tmp")) == []


def test_success_secure_roundtrip(monkeypatch, config_file):
    monkeypatch.setenv("MODAGENT_SECURE_SECRETS", "1")
    config.save(config.Config(llm_model="新模型", llm_api_key="fake-test-key"))
    saved = json.loads(config_file.read_text(encoding="utf-8"))
    assert saved["llm_model"] == "新模型"
    assert "llm_api_key" not in saved
    assert "fake-test-key" not in config_file.read_text(encoding="utf-8")
    assert not list(config_file.parent.glob(".config-*.tmp"))


def test_api_failure_preserves_live_config_and_env(monkeypatch, config_file):
    from modagent import api
    original = config.Config(llm_model="original", llm_api_key="fake-original")
    agent = SimpleNamespace(_client_obj="old-client", _network_route="old-route")
    monkeypatch.setattr(api, "cfg", original)
    monkeypatch.setattr(api, "agents", {"test": agent})
    monkeypatch.setenv("MODAGENT_CREDENTIAL_ROUTE", "1")
    monkeypatch.setenv("MODAGENT_LLM_MODEL", "original")
    monkeypatch.setenv("MODAGENT_LLM_API_KEY", "fake-original")
    def fail(*args):
        raise OSError("injected save failure")
    monkeypatch.setattr(api, "save_config", fail)
    with pytest.raises(OSError):
        api.update_config(api.ConfigUpdate(llm_model="changed", llm_api_key="fake-new"))
    assert api.cfg is original
    assert original.llm_model == "original"
    assert original.llm_api_key == "fake-original"
    assert os.environ["MODAGENT_LLM_MODEL"] == "original"
    assert os.environ["MODAGENT_LLM_API_KEY"] == "fake-original"
    assert agent._client_obj == "old-client"


def test_api_publishes_only_after_save(monkeypatch, config_file):
    from modagent import api
    original = config.Config(llm_model="original")
    monkeypatch.setattr(api, "cfg", original)
    monkeypatch.setattr(api, "agents", {})
    monkeypatch.delenv("MODAGENT_CREDENTIAL_ROUTE", raising=False)
    def save(candidate):
        assert original.llm_model == "original"
        assert candidate is not original
        config.save(candidate)
    monkeypatch.setattr(api, "save_config", save)
    assert api.update_config(api.ConfigUpdate(llm_model="changed")) == {"ok": True}
    assert original.llm_model == "changed"
    assert json.loads(config_file.read_text(encoding="utf-8"))["llm_model"] == "changed"


def test_resolve_is_read_only(monkeypatch):
    from modagent import api
    original = config.Config(game_slug="old", game_id=1)
    monkeypatch.setattr(api, "cfg", original)
    monkeypatch.setattr(api.games, "_auto_infer", lambda name: ("new", 2))
    monkeypatch.setattr(api, "save_config", lambda candidate: pytest.fail("resolve must not save"))
    assert api.resolve_game("Fixture") == {"slug": "new", "game_id": 2}
    assert (original.game_slug, original.game_id) == ("old", 1)


def test_directory_save_failure_keeps_mapping(monkeypatch, tmp_path):
    from modagent import api
    original = config.Config(game_root=str(tmp_path), game_slug="fixture", manual_mod_dirs={})
    monkeypatch.setattr(api, "cfg", original)
    def fail(candidate):
        raise OSError("injected write failure")
    monkeypatch.setattr(api, "save_config", fail)
    with pytest.raises(OSError):
        api.import_mod_directory(api.ModDirectoryImport(path=str(tmp_path)))
    assert original.manual_mod_dirs == {}


def test_directory_rejects_changed_game(monkeypatch, tmp_path):
    from modagent import api
    original = config.Config(game_root=str(tmp_path), game_slug="fixture", game_instance_id="current")
    monkeypatch.setattr(api, "cfg", original)
    monkeypatch.setattr(api, "save_config", lambda value: pytest.fail("must not save changed scope"))
    with pytest.raises(api.HTTPException) as caught:
        api.import_mod_directory(api.ModDirectoryImport(path=str(tmp_path), expected_game_instance_id="old"))
    assert caught.value.status_code == 409
    assert original.manual_mod_dirs == {}


@pytest.mark.parametrize("fail_save", [False, True])
def test_manual_import_publish_boundary(monkeypatch, tmp_path, fail_save):
    from modagent import api
    original = config.Config(game_root="old-root", game_slug="old", manual_games=[])
    monkeypatch.setattr(api, "cfg", original)
    monkeypatch.setattr(api.games, "verify_game_alive", lambda *args: {"alive": True, "reason": "fixture"})
    saved = {"path": str(tmp_path), "name": "Fixture", "slug": "fixture", "game_instance_id": "fixture-id", "game_id": 0}
    monkeypatch.setattr(api.games, "upsert_manual_game", lambda *args, **kwargs: ([saved], saved))
    monkeypatch.setattr(api.games, "normalize_manual_game", lambda value: value)
    scans = []
    monkeypatch.setattr(api, "_queue_inventory_scan", lambda *args: scans.append(args) or {"queued": True})
    def persist(candidate):
        assert original.game_slug == "old"
        if fail_save:
            raise OSError("injected save failure")
    monkeypatch.setattr(api, "save_config", persist)
    body = api.GameImport(game_root=str(tmp_path), game_name="Fixture")
    if fail_save:
        with pytest.raises(OSError):
            api.import_game(body)
        assert original.game_slug == "old"
        assert original.manual_games == []
        assert not scans
    else:
        result = api.import_game(body)
        assert result["saved"] is True
        assert original.game_slug == "fixture"
        assert len(scans) == 1


@pytest.mark.parametrize("failure", ["none", "config", "commit", "staged_read", "later_edit"])
def test_config_scope_transaction(monkeypatch, config_file, failure):
    from modagent import api, db, snapshot
    root=config_file.parent
    monkeypatch.setattr(db,"DB_FILE",str(root / "state.db"))
    monkeypatch.setattr(snapshot,"SNAPSHOTS_DIR",str(root / "snapshots"))
    folder=root / "snapshots" / "legacy" / "fixture-snapshot"
    folder.mkdir(parents=True)
    (folder / "data.bin").write_bytes(b"snapshot-content")
    db.init_db()
    connect=db.get_conn
    connection=connect()
    connection.execute("INSERT INTO sessions (id,title,game_slug) VALUES (?,?,?)",("fixture-session","Fixture","legacy"))
    connection.commit(); connection.close()
    original=config.Config(game_slug="old-game",game_instance_id="old-instance")
    monkeypatch.setattr(api,"cfg",original)
    monkeypatch.setattr(api,"agents",{})
    monkeypatch.delenv("MODAGENT_CREDENTIAL_ROUTE",raising=False)
    before=config_file.read_bytes()
    if failure=="staged_read":
        real_open=open
        def fail_staged_read(path,*args,**kwargs):
            if os.path.basename(str(path)).startswith(".config-") and args and args[0]=="rb":
                raise PermissionError("injected staged read failure")
            return real_open(path,*args,**kwargs)
        monkeypatch.setattr(config,"open",fail_staged_read,raising=False)
    if failure=="later_edit":
        def save_then_external_edit(candidate):
            receipt=config.save(candidate)
            config_file.write_bytes(b"later-user-edit")
            return receipt
        monkeypatch.setattr(api,"save_config",save_then_external_edit)
    if failure=="config":
        def fail_save(candidate): raise PermissionError("injected save failure")
        monkeypatch.setattr(api,"save_config",fail_save)
    if failure in {"commit", "later_edit"}:
        class FailCommit:
            def __init__(self): self.connection=connect()
            def execute(self,*args): return self.connection.execute(*args)
            def commit(self): raise OSError("injected commit failure")
            def rollback(self): return self.connection.rollback()
            def close(self): return self.connection.close()
        monkeypatch.setattr(db,"get_conn",FailCommit)
    body=api.ConfigUpdate(game_slug="legacy",game_instance_id="instance",game_root=str(root / "game"))
    if failure=="none":
        assert api.update_config(body)=={"ok":True}
        assert original.game_instance_id=="instance"
        assert json.loads(config_file.read_text())["game_instance_id"]=="instance"
    else:
        expected_error=RuntimeError if failure=="later_edit" else OSError
        with pytest.raises(expected_error): api.update_config(body)
        assert original.game_instance_id=="old-instance"
        assert config_file.read_bytes()==(b"later-user-edit" if failure=="later_edit" else before)
    connection=connect()
    scope=connection.execute("SELECT game_slug FROM sessions WHERE id=?",("fixture-session",)).fetchone()[0]
    connection.close()
    expected="instance" if failure=="none" else "legacy"
    assert scope==expected
    assert (root / "snapshots" / expected / "fixture-snapshot" / "data.bin").read_bytes()==b"snapshot-content"
    assert not list(root.glob(".config-*.tmp"))


def test_save_receipt_is_exact_bytes(monkeypatch, config_file):
    monkeypatch.setenv("MODAGENT_SECURE_SECRETS", "1")
    receipt=config.save(config.Config(llm_model="中文模型",llm_api_key="fake-secret"))
    assert isinstance(receipt,bytes)
    assert receipt==config_file.read_bytes()
    assert "中文模型" in receipt.decode("utf-8")
    assert b"fake-secret" not in receipt


def test_scope_save_does_not_reread_published_file(monkeypatch,config_file):
    from modagent import api
    monkeypatch.setattr(api,"cfg",config.Config(game_slug="old"))
    monkeypatch.setattr(api,"agents",{})
    original_read=api.read_config_bytes
    reads=[]
    def read_once():
        reads.append(True)
        if len(reads)>1: raise PermissionError("published file unreadable")
        return original_read()
    monkeypatch.setattr(api,"read_config_bytes",read_once)
    monkeypatch.setattr(api.snapshot,"migrate_game_scope",lambda *args: None)
    monkeypatch.setattr(api.db,"migrate_game_scope",lambda *args,before_commit: before_commit())
    assert api.update_config(api.ConfigUpdate(game_slug="legacy",game_instance_id="instance"))=={"ok":True}
    assert len(reads)==1
    assert api.cfg.game_instance_id=="instance"


def test_config_restore_refuses_later_edit(config_file):
    previous=config_file.read_bytes()
    config_file.write_bytes(b"later-user-edit")
    with pytest.raises(RuntimeError,match="CONFIG_RECOVERY_REQUIRED"):
        config.restore_config_bytes(previous,b"our-write")
    assert config_file.read_bytes()==b"later-user-edit"
