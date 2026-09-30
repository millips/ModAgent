import os
import tempfile

os.environ["MODAGENT_DATA_DIR"] = tempfile.mkdtemp(prefix="modagent-snapshot-dedupe-data-")

from modagent import db, snapshot
from modagent.config import Config, save


with tempfile.TemporaryDirectory(prefix="modagent-snapshot-dedupe-game-") as game:
    os.makedirs(os.path.join(game, "BepInEx", "plugins"), exist_ok=True)
    managed = os.path.join(game, "BepInEx", "plugins", "Example.dll")
    with open(managed, "wb") as stream:
        stream.write(b"v1")

    save(Config(game_root=game, game_slug="repo"))
    db.init_db()

    first = snapshot.snapshot_create(game, "repo", trigger_mod_name="安装前快照")
    repeated = snapshot.snapshot_create(game, "repo", trigger_mod_name="安装前快照")
    assert repeated == first, (first, repeated)
    assert len(db.list_snapshots()) == 1

    with open(managed, "wb") as stream:
        stream.write(b"v2")
    changed = snapshot.snapshot_create(game, "repo", trigger_mod_name="安装前快照")
    assert changed != first
    assert len(db.list_snapshots()) == 2

    different_operation = snapshot.snapshot_create(game, "repo", trigger_mod_name="卸载前快照")
    assert different_operation != changed
    assert len(db.list_snapshots()) == 3

print("SNAPSHOT DEDUPE TEST PASSED")
