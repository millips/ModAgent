"""Multiple installs of the same catalogue game must not share local state."""

from pathlib import Path

from modagent import db, games
from modagent.config import Config


def test_same_slug_installations_receive_distinct_instance_ids(tmp_path, monkeypatch):
    first_root = tmp_path / "Steam" / "Same Game"
    second_root = tmp_path / "Xbox" / "Same Game"
    first_root.mkdir(parents=True)
    second_root.mkdir(parents=True)

    entries, first = games.upsert_manual_game(
        [], "Same Unknown Game", str(first_root)
    )
    _, second = games.upsert_manual_game(
        entries, "Same Unknown Game", str(second_root)
    )

    assert first["slug"] == second["slug"]
    assert first["game_instance_id"] != second["game_instance_id"]

    monkeypatch.setattr(db, "DB_FILE", str(tmp_path / "state.db"))
    selected = Config(
        game_slug=first["slug"],
        game_root=str(first_root),
        game_instance_id=first["game_instance_id"],
    )
    monkeypatch.setattr(db, "load_config", lambda: selected)
    db.init_db()

    db.add_mod(db.InstalledMod(
        id="shared-upstream-id",
        name="First Copy Mod",
        version="1",
        snapshot_id="",
        game_slug=first["slug"],
    ))

    selected.game_root = str(second_root)
    selected.game_instance_id = second["game_instance_id"]
    db.add_mod(db.InstalledMod(
        id="shared-upstream-id",
        name="Second Copy Mod",
        version="2",
        snapshot_id="",
        game_slug=second["slug"],
    ))

    first_mods = db.get_installed_mods(first["game_instance_id"])
    second_mods = db.get_installed_mods(second["game_instance_id"])
    assert [item.name for item in first_mods] == ["First Copy Mod"]
    assert [item.name for item in second_mods] == ["Second Copy Mod"]
