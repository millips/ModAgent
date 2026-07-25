"""Destructive ledger operations must never escape the selected game root."""
import os
import tempfile

from modagent import installer


tmp = tempfile.mkdtemp(prefix="modagent-path-boundary-")
game = os.path.join(tmp, "Game")
outside = os.path.join(tmp, "precious-user-file.txt")
inside = os.path.join(game, "Mods", "safe.dll")
os.makedirs(os.path.dirname(inside), exist_ok=True)
with open(inside, "w", encoding="utf-8") as handle:
    handle.write("mod")
with open(outside, "w", encoding="utf-8") as handle:
    handle.write("precious")

result = installer.uninstall_mod(
    "corrupt-ledger",
    game,
    [inside, outside, os.path.join("..", "precious-user-file.txt")],
    game_slug="test",
)
assert not os.path.exists(inside), result
assert os.path.isfile(outside), result
assert len(result["blocked_unsafe"]) == 2, result
assert result["removed"] == [inside], result

with open(inside, "w", encoding="utf-8") as handle:
    handle.write("mod")
disable = installer.disable_mod([inside, outside], game)
assert os.path.isfile(inside + ".disabled"), disable
assert os.path.isfile(outside), disable
assert len(disable["blocked_unsafe"]) == 1, disable

enable = installer.enable_mod([inside, outside], game)
assert os.path.isfile(inside), enable
assert os.path.isfile(outside), enable
assert len(enable["blocked_unsafe"]) == 1, enable

drive, _ = os.path.splitdrive(os.path.abspath(game))
drive_root = drive + os.sep if drive else os.path.abspath(os.sep)
resolved, reason = installer.resolve_managed_game_path(outside, drive_root)
assert not resolved and "磁盘根目录" in reason, (resolved, reason)

print("PASS destructive path boundary")
