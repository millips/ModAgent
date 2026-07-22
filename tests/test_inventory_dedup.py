"""Large local inventory and download preflight regression tests."""
import asyncio
import json
import os
import tempfile
import time

from modagent import db, downloader, nexus, scanner, tools
from modagent.config import Config, Tier


def touch(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as handle:
        handle.write(b"x")


root = tempfile.mkdtemp()
db.DB_FILE = os.path.join(root, "state.db")
db.init_db()
game = os.path.join(root, "Cyberpunk 2077")

for index in range(600):
    touch(os.path.join(
        game, "archive", "pc", "mod", f"Pack{index:04d}",
        f"Outfit_{index:04d}.archive",
    ))

started = time.monotonic()
scan = scanner.scan_existing_mods(game, "cyberpunk2077", "")
elapsed = time.monotonic() - started
assert scan["detected"] == 600, scan["detected"]
assert len(scan["identified"]) == 600, len(scan["identified"])
assert elapsed < 5, elapsed
assert scanner.import_mods(scan["identified"]) == 600
assert len(db.get_installed_mods("cyberpunk2077")) == 600

# A fresh database row has a local hash ID. mod_download must still identify a
# strict upstream-name match, create the binding and avoid touching downloader.
cfg = Config(
    game_name="Cyberpunk 2077", game_slug="cyberpunk2077", game_id=3333,
    game_root=game, nexus_api_key="key", tier=Tier.PRO,
)
target = next(item for item in db.get_installed_mods("cyberpunk2077")
              if item.name == "Outfit 0042")
original_get_mod = nexus.get_mod
original_download = downloader.download_mod
nexus.get_mod = lambda *_args, **_kwargs: {
    "name": "Outfit 0042", "version": "2.0.0",
}


async def forbidden_download(**_kwargs):
    raise AssertionError("download must be skipped for an installed mod")


downloader.download_mod = forbidden_download
try:
    result = json.loads(tools.execute("mod_download", {"mod_id": 4242}, cfg))
finally:
    nexus.get_mod = original_get_mod
    downloader.download_mod = original_download

assert result["already_installed"] is True, result
assert result["download_skipped"] is True, result
assert result["installed_id"] == target.id, result
binding = db.get_mod_source_binding(target.id, "cyberpunk2077")
assert binding and binding["source"] == "nexus" and binding["source_key"] == "4242", binding

github_target = db.InstalledMod(
    id="local_cool", name="Cool Mod", version="1.0", snapshot_id="",
    installed_by="imported", game_slug="cyberpunk2077",
)
db.add_mod(github_target)
url_result = json.loads(tools.execute(
    "download_from_url", {"url": "https://github.com/Author/Cool-Mod"}, cfg
))
assert url_result["already_installed"] is True, url_result
assert url_result["source"] == "github", url_result
assert db.get_mod_source_binding("local_cool", "cyberpunk2077")["source_key"] == "Author/Cool-Mod"

print("INVENTORY SCALE + DOWNLOAD DEDUP TESTS PASSED")
