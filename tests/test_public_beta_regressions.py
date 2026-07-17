"""First public beta regressions: Unity alive check and local-mod import."""
import json
import os
import tempfile
import urllib.error

from modagent import db, games, nexus, scanner
from modagent.sources import thunderstore


all_ok = True


def check(label, condition, detail=""):
    global all_ok
    print(("PASS " if condition else "FAIL ") + label)
    if not condition and detail:
        print("  " + detail)
    all_ok = all_ok and condition


def touch(path, data=b"x"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as handle:
        handle.write(data)


root = tempfile.mkdtemp()
unity_root = os.path.join(root, "YAPYAP")
touch(os.path.join(unity_root, "yapyap.exe"), b"x" * 672256)
touch(os.path.join(unity_root, "UnityPlayer.dll"))
touch(os.path.join(unity_root, "yapyap_Data", "globalgamemanagers"))
alive = games.verify_game_alive(unity_root)
check("A1 small Unity launcher accepted", alive.get("alive") is True, str(alive))
check("A2 Unity engine identified", alive.get("engine") == "unity", str(alive))

fake_root = os.path.join(root, "Fake")
touch(os.path.join(fake_root, "helper.exe"), b"x" * 100)
check("A3 tiny unrelated exe rejected",
      games.verify_game_alive(fake_root).get("alive") is False)

db.DB_FILE = os.path.join(root, "state.db")
db.init_db()
game_root = os.path.join(root, "REPO")
touch(os.path.join(game_root, "BepInEx", "plugins", "LoosePlugin.dll"))
touch(os.path.join(
    game_root, "BepInEx", "plugins", "FolderMod", "FolderMod.dll"
))
scanned = scanner.scan_existing_mods(game_root, "repo", "")
names = {item["name"] for item in scanned["identified"]}
check("B1 loose DLL and folder mod scanned",
      {"LoosePlugin", "FolderMod"} <= names, str(scanned))

imported = scanner.import_mods(scanned["identified"])
saved = db.get_installed_mods("repo")
check("B2 both existing mods imported", imported == 2, str(imported))
check("B3 imported mods remain game-scoped",
      {item.name for item in saved} == {"LoosePlugin", "FolderMod"})
check("B4 imported files recorded",
      all(json.loads(item.files_installed) for item in saved))

original_api = nexus._api
nexus._api = lambda *args, **kwargs: (_ for _ in ()).throw(
    urllib.error.URLError("proxy unavailable")
)
try:
    try:
        nexus._search_api("clothes", "network-test-game", "key", 99999)
        network_status = ""
    except nexus.NexusSearchUnavailable as exc:
        network_status = exc.status
    check("C1 Nexus connection failure is not an empty result",
          network_status == "source_unavailable", network_status)
finally:
    nexus._api = original_api

original_http = thunderstore._http_json
thunderstore._PKG_CACHE.clear()
responses = [[], [{
    "name": "RecoveredMod",
    "owner": "Author",
    "versions": [{"description": "health mod", "downloads": 10}],
    "package_url": "https://thunderstore.io/c/test/p/Author/RecoveredMod/",
}]]


def intermittent_http(_url):
    return responses.pop(0)


thunderstore._http_json = intermittent_http
try:
    first = thunderstore.search("test", "health")
    second = thunderstore.search("test", "health", force_refresh=True)
    check("C2 Thunderstore forced refresh recovers transient empty",
          first == [] and len(second) == 1, str(second))
finally:
    thunderstore._http_json = original_http
    thunderstore._PKG_CACHE.clear()

if not all_ok:
    raise SystemExit(1)
print("PUBLIC BETA REGRESSION TESTS PASSED")
