from pathlib import Path

from modagent import downloader


def test_browser_download_is_imported_into_cache_without_network_redownload(tmp_path):
    source_dir = tmp_path / "browser"
    cache_dir = tmp_path / "cache"
    source_dir.mkdir()
    cache_dir.mkdir()
    source = source_dir / "example.zip"
    source.write_bytes(b"browser-download-content")
    target = cache_dir / source.name
    progress = []

    imported = downloader.import_local_download(
        source,
        target,
        progress_callback=progress.append,
    )

    assert Path(imported) == target
    assert target.read_bytes() == b"browser-download-content"
    assert not source.exists()
    assert progress[-1] == 1.0


def test_import_is_idempotent_when_browser_file_already_is_cache_file(tmp_path):
    target = tmp_path / "example.zip"
    target.write_bytes(b"already-managed")

    imported = downloader.import_local_download(target, target)

    assert Path(imported) == target
    assert target.read_bytes() == b"already-managed"
