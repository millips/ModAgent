"""SMAPI packages must never fall through to the BepInEx installer."""

import json
import os
import tempfile
import zipfile
from unittest import mock

from modagent import installer


# Regression: Windows runners may canonicalize a lexical temp path to an 8.3
# short path. Relative layout must still come from the two lexical operands.
lexical_root = os.path.join(tempfile.gettempdir(), "Runner Admin Temp")
lexical_child = os.path.join(lexical_root, "AutoForager", "AutoForager.dll")
realpath_original = os.path.realpath


def fake_short_realpath(value):
    absolute = os.path.abspath(value)
    try:
        relative = os.path.relpath(absolute, lexical_root)
    except ValueError:
        return realpath_original(value)
    if relative != os.pardir and not relative.startswith(os.pardir + os.sep):
        short_root = os.path.join(tempfile.gettempdir(), "RUNNER~1")
        return short_root if relative == "." else os.path.join(short_root, relative)
    return realpath_original(value)


with mock.patch.object(installer.os.path, "realpath", side_effect=fake_short_realpath):
    assert installer._relative_child_path(lexical_child, lexical_root) == os.path.join(
        "AutoForager", "AutoForager.dll"
    )


root = tempfile.mkdtemp(prefix="modagent-stardew-install-")
game = os.path.join(root, "Stardew Valley")
os.makedirs(game)
archive = os.path.join(root, "7736_Auto_Forager_4.1.0.zip")

manifest = {
    "Name": "Auto Forager",
    "Author": "Jag3Dagster",
    "Version": "4.1.0",
    "UniqueID": "J3.AutoForager",
    "EntryDll": "AutoForager.dll",
}
with zipfile.ZipFile(archive, "w") as handle:
    handle.writestr(
        "AutoForager/manifest.json",
        json.dumps(manifest),
    )
    handle.writestr("AutoForager/AutoForager.dll", b"dll")
    handle.writestr("AutoForager/i18n/default.json", "{}")

result = installer.install_mod(archive, game, "stardewvalley")
installed = {
    os.path.normcase(os.path.relpath(item["dest"], game))
    for item in result["installed"]
}
assert installed == {
    os.path.normcase(os.path.join("Mods", "AutoForager", "manifest.json")),
    os.path.normcase(os.path.join("Mods", "AutoForager", "AutoForager.dll")),
    os.path.normcase(os.path.join("Mods", "AutoForager", "i18n", "default.json")),
}
assert result["handler"] == "stardew_smapi"
assert result["verified_mods"] == [{
    "name": "Auto Forager",
    "unique_id": "J3.AutoForager",
    "version": "4.1.0",
    "folder": "AutoForager",
    "entry_dll": "AutoForager.dll",
}]
assert not os.path.exists(os.path.join(game, "BepInEx"))

bad_archive = os.path.join(root, "loose-dll.zip")
with zipfile.ZipFile(bad_archive, "w") as handle:
    handle.writestr("AutoForager.dll", b"dll")
try:
    installer.install_mod(bad_archive, game, "stardewvalley")
except RuntimeError as exc:
    assert "manifest.json" in str(exc)
else:
    raise AssertionError("A loose Stardew DLL must not use the BepInEx fallback")

print("STARDEW INSTALL ROUTING TESTS PASSED")
