"""Stardew-specific install gates and completion evidence."""

import json
import os
import tempfile
import zipfile

from modagent import stardew


def write(path, data=b"x"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    mode = "wb" if isinstance(data, bytes) else "w"
    kwargs = {} if mode == "wb" else {"encoding": "utf-8"}
    with open(path, mode, **kwargs) as handle:
        handle.write(data)


def manifest(path, name, unique_id, version="1.0.0"):
    write(path, json.dumps({
        "Name": name,
        "UniqueID": unique_id,
        "Version": version,
        "EntryDll": name.replace(" ", "") + ".dll",
    }))


temp = tempfile.mkdtemp(prefix="modagent_stardew_")
steam_root = os.path.join(temp, "Steam")
game_root = os.path.join(steam_root, "steamapps", "common", "Stardew Valley")
appdata = os.path.join(temp, "AppData", "Roaming")
old_steam = os.environ.get("MODAGENT_STEAM_DIR")
old_appdata = os.environ.get("APPDATA")
os.environ["MODAGENT_STEAM_DIR"] = steam_root
os.environ["APPDATA"] = appdata

try:
    for relative in ("StardewModdingAPI.exe", "StardewModdingAPI.dll", "Stardew Valley.exe"):
        write(os.path.join(game_root, relative))
    os.makedirs(os.path.join(game_root, "smapi-internal"), exist_ok=True)
    manifest(
        os.path.join(game_root, "Mods", "ConsoleCommands", "manifest.json"),
        "Console Commands", "SMAPI.ConsoleCommands", "4.5.2",
    )
    manifest(
        os.path.join(game_root, "Mods", "NPCMapLocations", "manifest.json"),
        "NPC Map Locations", "Bouhm.NPCMapLocations", "3.5.2",
    )

    pending = stardew.smapi_status(game_root, "Stardew Valley", "stardewvalley")
    assert pending["stage"] == "launch_option_pending", pending
    assert pending["complete"] is False
    assert pending["launch"]["expected"] == f'"{os.path.join(game_root, stardew.SMAPI_EXE)}" %command%'

    launch = (
        pending["launch"]["expected"]
        .replace("\\", "\\\\")
        .replace('"', '\\"')
    )
    localconfig = os.path.join(steam_root, "userdata", "123", "config", "localconfig.vdf")
    write(localconfig, (
        '"UserLocalConfigStore" { "Software" { "Valve" { "Steam" { "apps" { '
        f'"{stardew.STEAM_APP_ID}" {{ "LaunchOptions" "{launch}" }}'
        " } } } } }"
    ))
    configured = stardew.smapi_status(game_root, "Stardew Valley", "stardewvalley")
    assert configured["stage"] == "first_launch_pending", configured
    assert configured["launch"]["configured"] is True

    log_path = os.path.join(appdata, "StardewValley", "ErrorLogs", "SMAPI-latest.txt")
    write(log_path, (
        "[SMAPI] SMAPI 4.5.2 with Stardew Valley 1.6\n"
        "[SMAPI] ERROR NPC Map Locations failed to load.\n"
    ))
    failed_mention = stardew.smapi_status(game_root, "Stardew Valley", "stardewvalley")
    assert failed_mention["complete"] is False, failed_mention
    assert failed_mention["custom_mods_loaded"] == [], failed_mention

    write(log_path, (
        "[SMAPI] SMAPI 4.5.2 with Stardew Valley 1.6\n"
        "[SMAPI] Loaded 3 mods:\n"
        "[SMAPI]    Console Commands 4.5.2 by SMAPI\n"
        "[SMAPI]    Save Backup 4.5.2 by SMAPI\n"
        "[SMAPI]    NPC Map Locations 3.5.2 by Bouhm\n"
    ))
    complete = stardew.smapi_status(game_root, "Stardew Valley", "stardewvalley")
    assert complete["complete"] is True, complete
    assert complete["stage"] == "complete"
    assert complete["custom_mods_loaded"][0]["unique_id"] == "Bouhm.NPCMapLocations"

    archive = os.path.join(temp, "StardewValleyExpanded.zip")
    with zipfile.ZipFile(archive, "w") as package:
        package.writestr("Stardew Valley Expanded/manifest.json", json.dumps({
            "Name": "Stardew Valley Expanded",
            "UniqueID": "FlashShifter.StardewValleyExpandedCP",
            "Version": "1.15.0",
            "ContentPackFor": {"UniqueID": "Pathoschild.ContentPatcher"},
            "Dependencies": [{
                "UniqueID": "Esca.FarmTypeManager",
                "MinimumVersion": "1.23.0",
                "IsRequired": True,
            }],
        }))
    blocked = stardew.archive_dependency_preflight(
        archive, game_root, "Stardew Valley", "stardewvalley"
    )
    assert blocked["install_blocked"] is True, blocked
    assert {item["name"] for item in blocked["missing_dependencies"]} == {
        "Content Patcher", "Farm Type Manager",
    }

    manifest(
        os.path.join(game_root, "Mods", "ContentPatcher", "manifest.json"),
        "Content Patcher", "Pathoschild.ContentPatcher",
    )
    manifest(
        os.path.join(game_root, "Mods", "FarmTypeManager", "manifest.json"),
        "Farm Type Manager", "Esca.FarmTypeManager", "1.0.0",
    )
    outdated = stardew.archive_dependency_preflight(
        archive, game_root, "Stardew Valley", "stardewvalley"
    )
    assert outdated["install_blocked"] is True, outdated
    assert outdated["incompatible_dependencies"][0]["name"] == "Farm Type Manager"

    manifest(
        os.path.join(game_root, "Mods", "FarmTypeManager", "manifest.json"),
        "Farm Type Manager", "Esca.FarmTypeManager", "1.23.0",
    )
    allowed = stardew.archive_dependency_preflight(
        archive, game_root, "Stardew Valley", "stardewvalley"
    )
    assert allowed["ok"] is True and allowed["install_blocked"] is False, allowed
finally:
    if old_steam is None:
        os.environ.pop("MODAGENT_STEAM_DIR", None)
    else:
        os.environ["MODAGENT_STEAM_DIR"] = old_steam
    if old_appdata is None:
        os.environ.pop("APPDATA", None)
    else:
        os.environ["APPDATA"] = old_appdata

print("STARDEW SMAPI TESTS PASSED")
