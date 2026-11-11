import os
import tempfile

os.environ.setdefault("MODAGENT_DATA_DIR", tempfile.mkdtemp(prefix="modagent-background-test-"))


def test_background_status_ignores_partial_and_selects_latest(monkeypatch, tmp_path):
    from modagent import api, config
    monkeypatch.setattr(api, "cfg", config.Config())
    monkeypatch.setattr(api, "edition_data_dir", lambda kind: str(tmp_path))
    old = tmp_path / "old.png"
    new = tmp_path / "new.JPG"
    old.write_bytes(b"old")
    new.write_bytes(b"new")
    os.utime(old, ns=(1_000_000_000, 1_000_000_000))
    os.utime(new, ns=(2_000_000_000, 2_000_000_000))
    (tmp_path / "incomplete.png.tmp").write_bytes(b"partial")
    (tmp_path / "notes.txt").write_text("retain", encoding="utf-8")
    assert api.get_status()["bg"] == "new.JPG"
    new.unlink()
    assert api.get_status()["bg"] == "old.png"
    old.unlink()
    assert api.get_status()["bg"] is None
    assert (tmp_path / "notes.txt").read_text() == "retain"


def test_background_directory_failure_preserves_core_status(monkeypatch, tmp_path):
    from modagent import api, config
    monkeypatch.setattr(api, "cfg", config.Config(llm_model="fixture", game_slug="fixture-game"))
    monkeypatch.setattr(api, "edition_data_dir", lambda kind: str(tmp_path))
    def denied(_path):
        raise PermissionError("private-directory-do-not-expose")
    monkeypatch.setattr(api.os, "listdir", denied)
    status = api.get_status()
    assert status["llm_model"] == "fixture"
    assert status["game_slug"] == "fixture-game"
    assert status["bg"] is None
    assert status["bg_error"] == "BACKGROUND_READ_FAILED"
    assert "private-directory" not in str(status)


def test_status_does_not_create_background_directory(monkeypatch, tmp_path):
    from modagent import api, config
    directory = tmp_path / "missing"
    monkeypatch.setattr(api, "cfg", config.Config())
    monkeypatch.setattr(api, "edition_data_dir", lambda kind: str(directory))
    result = api.get_status()
    assert result["bg"] is None and result["bg_error"] is None
    assert not directory.exists()


def test_unreadable_image_warns_but_other_background_survives(monkeypatch, tmp_path):
    from modagent import api, config
    monkeypatch.setattr(api, "cfg", config.Config())
    monkeypatch.setattr(api, "edition_data_dir", lambda kind: str(tmp_path))
    (tmp_path / "good.png").write_bytes(b"image")
    blocked = tmp_path / "blocked.png"
    blocked.write_bytes(b"image")
    original_stat = os.stat
    def selective_stat(path, *args, **kwargs):
        if str(path) == str(blocked):
            raise PermissionError("private file")
        return original_stat(path, *args, **kwargs)
    monkeypatch.setattr(api.os, "stat", selective_stat)
    status = api.get_status()
    assert status["bg"] == "good.png"
    assert status["bg_error"] == "BACKGROUND_READ_FAILED"
