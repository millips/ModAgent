"""Snapshot storage reporting must account for incremental hard links."""

import json
import os
import tempfile
from types import SimpleNamespace

from modagent import db, snapshot


root = tempfile.mkdtemp(prefix="modagent_snapshot_usage_")
original_root = snapshot.SNAPSHOTS_DIR
original_list = db.list_snapshots
snapshot.SNAPSHOTS_DIR = root

try:
    bucket = os.path.join(root, "game")
    first = os.path.join(bucket, "snap_1")
    second = os.path.join(bucket, "snap_2")
    orphan = os.path.join(bucket, "snap_orphan")
    os.makedirs(first)
    os.makedirs(second)
    os.makedirs(orphan)

    shared_first = os.path.join(first, "shared.bin")
    with open(shared_first, "wb") as handle:
        handle.write(b"x" * 100)
    os.link(shared_first, os.path.join(second, "shared.bin"))
    with open(os.path.join(second, "changed.bin"), "wb") as handle:
        handle.write(b"y" * 50)
    for directory in (first, second):
        with open(os.path.join(directory, "manifest.json"), "w", encoding="utf-8") as handle:
            json.dump({"files": []}, handle)
    with open(os.path.join(orphan, "manifest.json"), "w", encoding="utf-8") as handle:
        json.dump({"files": []}, handle)
    with open(os.path.join(orphan, "orphan.bin"), "wb") as handle:
        handle.write(b"z" * 25)

    rows = [
        SimpleNamespace(id="snap_2", game_slug="game"),
        SimpleNamespace(id="snap_1", game_slug="game"),
    ]
    db.list_snapshots = lambda game_slug="": rows

    usage = snapshot.snapshot_storage_usage("game")
    assert usage["snapshot_count"] == 2
    assert usage["valid_snapshot_count"] == 2
    assert usage["orphan_snapshot_count"] == 1
    assert usage["orphan_exclusive_bytes"] >= 25
    assert usage["deduplicated_bytes"] < usage["logical_bytes"]
    assert usage["snapshots"]["snap_2"]["exclusive_bytes"] >= 50
    assert usage["snapshots"]["snap_1"]["logical_bytes"] >= 100
finally:
    snapshot.SNAPSHOTS_DIR = original_root
    db.list_snapshots = original_list

print("SNAPSHOT STORAGE USAGE TESTS PASSED")
