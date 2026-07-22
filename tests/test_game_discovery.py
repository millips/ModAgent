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

print("GAME DISCOVERY TESTS PASSED")
