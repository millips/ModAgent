"""Large game/mod directories must not block discovery-facing requests."""

from __future__ import annotations

import os
from pathlib import Path
import tempfile
import threading
import time

from modagent import api, games


def test_executable_probe_skips_large_asset_tree():
    with tempfile.TemporaryDirectory(prefix="modagent_large_game_") as root:
        game_root = Path(root)
        content = game_root / "Content"
        content.mkdir()
        executable = game_root / "Example" / "Binaries" / "Win64" / (
            "Example-Win64-Shipping.exe"
        )
        executable.parent.mkdir(parents=True)
        executable.write_bytes(b"x")

        original_scandir = games.os.scandir

        def guarded_scandir(path):
            if os.path.normcase(os.path.abspath(path)) == os.path.normcase(
                os.path.abspath(content)
            ):
                raise AssertionError("asset tree should not be crawled for executables")
            return original_scandir(path)

        games.os.scandir = guarded_scandir
        try:
            result = games.verify_game_alive(str(game_root))
        finally:
            games.os.scandir = original_scandir

        assert result["alive"] is True
        assert os.path.normcase(result["shipping_exe"]) == os.path.normcase(
            str(executable)
        )


def test_inventory_scan_is_queued_without_blocking(monkeypatch):
    slug = "large_inventory_test"
    started = threading.Event()
    release = threading.Event()

    def slow_scan(*_args, **_kwargs):
        started.set()
        assert release.wait(2)
        return {
            "detected": 2,
            "identified": [{"name": "A"}, {"name": "B"}],
            "unidentified": [],
            "scanned_roots": ["X:/HugeMods"],
            "missing_roots": [],
        }

    monkeypatch.setattr(api.scanner, "scan_existing_mods", slow_scan)
    monkeypatch.setattr(api.scanner, "import_mods", lambda items: len(items))
    with api._inventory_scan_jobs_lock:
        api._inventory_scan_jobs.pop(slug, None)

    before = time.monotonic()
    state = api._queue_inventory_scan("X:/HugeGame", slug, "", ["X:/HugeMods"])
    elapsed = time.monotonic() - before

    assert elapsed < 0.2
    assert state["status"] == "running"
    assert state["queued"] is True
    assert started.wait(1)

    release.set()
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        state = api._inventory_scan_public_state(slug)
        if state["status"] != "running":
            break
        time.sleep(0.01)

    assert state["status"] == "completed"
    assert state["imported"] == 2
    assert state["detected"] == 2
    with api._inventory_scan_jobs_lock:
        api._inventory_scan_jobs.pop(slug, None)
