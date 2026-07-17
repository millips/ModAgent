"""Standalone tools extract under ModAgent data, never into the game."""
import os
import tempfile
import zipfile

from modagent import downloader


old_downloads = downloader.DOWNLOADS_DIR
old_dropbox = downloader.DROPBOX_DIR
old_tools = downloader.TOOLS_DIR

with tempfile.TemporaryDirectory() as root:
    downloader.DOWNLOADS_DIR = os.path.join(root, "downloads")
    downloader.DROPBOX_DIR = os.path.join(root, "dropbox")
    downloader.TOOLS_DIR = os.path.join(root, "tools")
    source_dir = os.path.join(downloader.DOWNLOADS_DIR, "streetfighter6")
    os.makedirs(source_dir)
    archive = os.path.join(source_dir, "818_Fluffy_v3.079.zip")
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("Fluffy/Modmanager.exe", b"MZ")
        zf.writestr("Fluffy/Data/config.dat", b"x")

    result = downloader.extract_external_tool(
        archive, "Fluffy Mod Manager v3.079"
    )
    assert result["status"] == "extracted"
    assert os.path.commonpath((result["tool_dir"], downloader.TOOLS_DIR)) == downloader.TOOLS_DIR
    assert result["archive_path"] == archive
    assert result["executables"][0].endswith("Modmanager.exe")
    assert os.path.isfile(result["executables"][0])

downloader.DOWNLOADS_DIR = old_downloads
downloader.DROPBOX_DIR = old_dropbox
downloader.TOOLS_DIR = old_tools

print("ALL PASS")
