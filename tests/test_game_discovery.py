"""Launcher-agnostic game discovery and manual import regressions."""
import json
import os
import tempfile

from modagent import games


def touch(path: str, data: bytes = b"x"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as handle:
        handle.write(data)


root = tempfile.mkdtemp(prefix="modagent_games_")

# A tiny/non-standard executable is rejected by automatic heuristics but must
# be accepted when the user explicitly selected that exact EXE.
manual_root = os.path.join(root, "StandaloneGame")
manual_exe = os.path.join(manual_root, "tiny-game.exe")
touch(manual_exe, b"x" * 1024)
assert games.verify_game_alive(manual_root)["alive"] is False
explicit = games.verify_game_alive(manual_root, manual_exe)
assert explicit["alive"] is True
assert explicit["shipping_exe"] == os.path.realpath(manual_exe)

# A small Stardew Valley .NET launcher is valid when its game assembly and
# MonoGame content structure are present.
stardew_root = os.path.join(root, "Stardew Valley")
stardew_exe = os.path.join(stardew_root, "Stardew Valley.exe")
touch(stardew_exe, b"x" * 158 * 1024)
touch(os.path.join(stardew_root, "Stardew Valley.dll"))
touch(os.path.join(stardew_root, "MonoGame.Framework.dll"))
touch(os.path.join(stardew_root, "Content", "Content.xnb"))
stardew = games.verify_game_alive(stardew_root)
assert stardew["alive"] is True
assert stardew["engine"] == "dotnet"
assert stardew["shipping_exe"] == stardew_exe

entries, saved = games.upsert_manual_game(
    [], "Standalone Game", manual_root, executable=manual_exe
)
assert saved["slug"] == "local_standalone_game"
manual = games.normalize_manual_game(entries[0])
assert manual["real"] is True
assert manual["source"] == "manual"

# Re-importing the same path updates rather than duplicates it.
entries, _ = games.upsert_manual_game(
    entries, "Standalone Game Renamed", manual_root, executable=manual_exe
)
assert len(entries) == 1
assert entries[0]["name"] == "Standalone Game Renamed"

# Epic discovery is manifest-driven and validates the target install.
program_data = os.path.join(root, "ProgramData")
manifest_dir = os.path.join(
    program_data, "Epic", "EpicGamesLauncher", "Data", "Manifests"
)
epic_root = os.path.join(root, "EpicLibrary", "ExampleGame")
touch(os.path.join(epic_root, "ExampleGame.exe"), b"x" * 1024)
touch(os.path.join(epic_root, "UnityPlayer.dll"))
touch(os.path.join(epic_root, "ExampleGame_Data", "globalgamemanagers"))
os.makedirs(manifest_dir, exist_ok=True)
with open(os.path.join(manifest_dir, "example.item"), "w", encoding="utf-8") as handle:
    json.dump({
        "DisplayName": "Example Game",
        "InstallLocation": epic_root,
        "AppName": "ExampleGame",
        "CatalogItemId": "catalog-1",
    }, handle)

old_program_data = os.environ.get("ProgramData")
os.environ["ProgramData"] = program_data
try:
    detected = games.detect_epic_games()
finally:
    if old_program_data is None:
        os.environ.pop("ProgramData", None)
    else:
        os.environ["ProgramData"] = old_program_data

assert len(detected) == 1
assert detected[0]["name"] == "Example Game"
assert detected[0]["source"] == "epic_manifest"
assert detected[0]["real"] is True

# Lowercase portable roots such as D:\steam must be found without crawling
# the whole drive.
portable_drive = os.path.join(root, "PortableDrive")
portable_steam = os.path.join(portable_drive, "steam")
portable_steamapps = os.path.join(portable_steam, "steamapps")
portable_stardew = os.path.join(
    portable_steamapps, "common", "Stardew Valley"
)
touch(os.path.join(portable_stardew, "Stardew Valley.exe"), b"x" * 158 * 1024)
touch(os.path.join(portable_stardew, "Stardew Valley.dll"))
touch(os.path.join(portable_stardew, "MonoGame.Framework.dll"))
touch(os.path.join(portable_stardew, "Content", "Content.xnb"))
with open(
    os.path.join(portable_steamapps, "appmanifest_413150.acf"),
    "w",
    encoding="utf-8",
) as handle:
    handle.write(
        '"AppState"\n{\n'
        '  "appid" "413150"\n'
        '  "name" "Stardew Valley"\n'
        '  "installdir" "Stardew Valley"\n'
        '}\n'
    )

old_get_drives = games._get_drives
old_find_libraries = games._find_steam_libraries
old_program_files = os.environ.get("ProgramFiles(x86)")
games._get_drives = lambda: [portable_drive]
os.environ["ProgramFiles(x86)"] = os.path.join(root, "MissingProgramFiles")
try:
    discovered_libraries = games._find_steam_libraries()
    assert any(
        os.path.normcase(os.path.realpath(path))
        == os.path.normcase(os.path.realpath(portable_steam))
        for path in discovered_libraries
    )
    games._find_steam_libraries = lambda: [portable_steam]
    portable_detected = games.detect_steam_games()
finally:
    games._find_steam_libraries = old_find_libraries
    games._get_drives = old_get_drives
    if old_program_files is None:
        os.environ.pop("ProgramFiles(x86)", None)
    else:
        os.environ["ProgramFiles(x86)"] = old_program_files

portable_matches = [
    game for game in portable_detected
    if os.path.normcase(os.path.realpath(game["path"]))
    == os.path.normcase(os.path.realpath(portable_stardew))
]
assert len(portable_matches) == 1
assert portable_matches[0]["name"] == "Stardew Valley"
assert portable_matches[0]["real"] is True

print("GAME DISCOVERY TESTS PASSED")
