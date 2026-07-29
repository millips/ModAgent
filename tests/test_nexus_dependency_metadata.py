"""Nexus prose requirements become structured install gates."""

from modagent.nexus import _extract_dependency_labels, _extract_required_loader


description = """
This mod is essentially a [b]port of Tansinator's Map Value Tracker[/b]
to [b]MelonLoader[/b].
<br />[*][b]Ensure you have the following required dependencies installed:[/b]
<br />[list]
<br />[*][b]RepoLib[/b]
<br />[*][b]MelonLoader[/b]
<br />[/list]
<br />[*][b]Launch the game[/b], and the total map value should be displayed!
"""

dependencies = _extract_dependency_labels(description)
assert dependencies == ["RepoLib", "MelonLoader"]
assert _extract_required_loader(description, dependencies) == "MelonLoader"

incidental = "Compatible with both communities. MelonLoader users have a separate port."
assert _extract_dependency_labels(incidental) == []
assert _extract_required_loader(incidental, []) == ""

bepinex = "Requirements:\n* BepInExPack\n* MenuLib\n\nUsage:\nPress F8."
assert _extract_dependency_labels(bepinex) == ["BepInExPack", "MenuLib"]
assert _extract_required_loader(bepinex, ["BepInExPack", "MenuLib"]) == "BepInEx"

install_path_only = (
    "Installation: place YAPYAP_MorePlayers.dll into "
    "YAPYAP/BepInEx/plugins."
)
assert _extract_required_loader(
    install_path_only, [], "MorePlayers(BepInEx)"
) == "BepInEx"

title_only = "No dependency list was published."
assert _extract_required_loader(
    title_only, [], "MorePlayers(BepInEx)"
) == "BepInEx"

print("ALL PASS")
