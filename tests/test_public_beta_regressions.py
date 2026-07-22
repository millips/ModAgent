"""First public beta regressions: Unity alive check and local-mod import."""
import json
import os
import tempfile
import urllib.error

from modagent import db, games, nexus, scanner
from modagent.agent import sanitize_tool_history
from modagent.networking import plan_http_route
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

stardew_root = os.path.join(root, "Stardew Valley")
touch(os.path.join(stardew_root, "Stardew Valley.exe"), b"x" * 158 * 1024)
touch(os.path.join(stardew_root, "Stardew Valley.dll"))
touch(os.path.join(stardew_root, "MonoGame.Framework.dll"))
touch(os.path.join(stardew_root, "Content", "Data", "ObjectInformation.xnb"))
stardew_alive = games.verify_game_alive(stardew_root)
check("A4 small .NET game launcher accepted",
      stardew_alive.get("alive") is True, str(stardew_alive))
check("A5 .NET engine identified",
      stardew_alive.get("engine") == "dotnet", str(stardew_alive))

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

cp_root = os.path.join(root, "Cyberpunk 2077")
touch(os.path.join(cp_root, "archive", "pc", "mod", "OutfitPack", "nested_outfit.archive"))
original_verify = scanner._verify_on_nexus
scanner._verify_on_nexus = lambda *_args, **_kwargs: None
try:
    cp_scan = scanner.scan_existing_mods(cp_root, "cyberpunk2077", "")
finally:
    scanner._verify_on_nexus = original_verify
check("B5 nested Cyberpunk mod directory scanned",
      cp_scan["detected"] == 1 and len(cp_scan["identified"]) == 1, str(cp_scan))
check("B6 blocked source lookup retains local mod",
      cp_scan["identified"][0]["confidence"] == "local_unverified", str(cp_scan))

stellar_root = os.path.join(root, "StellarBlade")
touch(os.path.join(stellar_root, "SB", "Content", "Paks", "LogicMods", "Costume", "dress.pak"))
scanner._verify_on_nexus = lambda *_args, **_kwargs: None
try:
    stellar_scan = scanner.scan_existing_mods(stellar_root, "stellarblade", "")
finally:
    scanner._verify_on_nexus = original_verify
check("B7 Stellar Blade LogicMods scanned recursively",
      stellar_scan["detected"] == 1 and len(stellar_scan["identified"]) == 1,
      str(stellar_scan))

manager_root = os.path.join(root, "Vortex Staging")
touch(os.path.join(manager_root, "Author-ManagedPackage-2.4.0", "archive", "pc", "mod", "managed.archive"))
manager_scan = scanner.scan_existing_mods(os.path.join(root, "EmptyGame"), "unknown-game", "", [manager_root])
check("B8 external manager directory scanned",
      any(item["name"] == "ManagedPackage" for item in manager_scan["identified"]),
      str(manager_scan))
check("B9 external scan root reported",
      os.path.abspath(manager_root) in manager_scan["scanned_roots"], str(manager_scan))

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

broken_history = [
    {"role": "user", "content": "搜索"},
    {
        "role": "assistant",
        "content": "",
        "tool_calls": [
            {"id": "call_search", "type": "function",
             "function": {"name": "nexus_search", "arguments": "{}"}},
            {"id": "call_check", "type": "function",
             "function": {"name": "game_file_check", "arguments": "{}"}},
        ],
    },
    {"role": "tool", "tool_call_id": "call_search", "content": "{}"},
    {"role": "user", "content": "下一步"},
]
repaired = sanitize_tool_history(broken_history)
tool_ids = [item.get("tool_call_id") for item in repaired if item["role"] == "tool"]
check("D1 interrupted parallel tool history repaired",
      tool_ids == ["call_search", "call_check"], str(repaired))
check("D2 missing tool result is explicit",
      "tool_result_missing" in repaired[3]["content"], str(repaired))

route = plan_http_route(
    "https://api.deepseek.com/v1",
    {"HTTPS_PROXY": "socks4://127.0.0.1:40008"},
)
check("E1 unsupported SOCKS4 automatically bypassed",
      route["mode"] == "direct_fallback", str(route))
route = plan_http_route(
    "https://api.deepseek.com/v1",
    {"HTTPS_PROXY": "socks5://127.0.0.1:1080"},
)
check("E2 SOCKS5 proxy retained",
      route["mode"] == "proxy" and route["proxy_url"].startswith("socks5://"),
      str(route))

if not all_ok:
    raise SystemExit(1)
print("PUBLIC BETA REGRESSION TESTS PASSED")
