"""Managed download caches are bounded without deleting user-owned archives."""

import os
import tempfile
import time

from modagent import downloader


def write(path: str, size: int = 32, mtime: float | None = None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as handle:
        handle.write(b"x" * size)
    if mtime is not None:
        os.utime(path, (mtime, mtime))


root = tempfile.mkdtemp(prefix="modagent_cache_")
original_downloads = downloader.DOWNLOADS_DIR
downloader.DOWNLOADS_DIR = os.path.join(root, "downloads")
try:
    installed = os.path.join(downloader.DOWNLOADS_DIR, "game", "101_mod.zip")
    write(installed, 100)
    result = downloader.cleanup_installed_archive(installed)
    assert result["removed"] is True
    assert result["bytes_freed"] == 100
    assert not os.path.exists(installed)

    external = os.path.join(root, "user-files", "manual.zip")
    write(external, 80)
    result = downloader.cleanup_installed_archive(external)
    assert result == {"removed": False, "reason": "user_managed_file"}
    assert os.path.exists(external)

    now = time.time()
    stale = os.path.join(downloader.DOWNLOADS_DIR, "game", "old.zip")
    fresh = os.path.join(downloader.DOWNLOADS_DIR, "game", "fresh.zip")
    partial = os.path.join(downloader.DOWNLOADS_DIR, "game", "broken.zip.part")
    write(stale, 50, now - 8 * 86400)
    write(fresh, 60, now - 3600)
    write(partial, 70, now - 2 * 86400)
    sweep = downloader.cleanup_stale_downloads(now=now, max_bytes=1024)
    assert sweep["removed_files"] == 2
    assert not os.path.exists(stale)
    assert not os.path.exists(partial)
    assert os.path.exists(fresh)

    older = os.path.join(downloader.DOWNLOADS_DIR, "game", "older.zip")
    newer = os.path.join(downloader.DOWNLOADS_DIR, "game", "newer.zip")
    write(older, 70, now - 300)
    write(newer, 70, now - 100)
    sweep = downloader.cleanup_stale_downloads(now=now, max_bytes=100)
    assert sweep["remaining_bytes"] <= 100
    assert not os.path.exists(older)
    assert os.path.exists(newer)
finally:
    downloader.DOWNLOADS_DIR = original_downloads

print("DOWNLOAD CACHE CLEANUP TESTS PASSED")
