"""Unknown layouts return package evidence instead of blind BepInEx retries."""
import os
import tempfile
import zipfile

from modagent import installer


def verify():
    with tempfile.TemporaryDirectory(prefix="ma-install-guide-") as root:
        archive = os.path.join(root, "unusual.zip")
        game = os.path.join(root, "Game")
        os.makedirs(game)
        with zipfile.ZipFile(archive, "w") as bundle:
            bundle.writestr(
                "OddMod/README.md",
                "# Installation\nCopy the `Content/Paks` folder into the game.",
            )
            bundle.writestr("OddMod/Content/Paks/OddMod.pak", b"pak")

        try:
            installer.install_mod(archive, game, "local_unknown_game")
        except installer.UnsupportedInstallLayout as exc:
            members = {item.replace("\\", "/") for item in exc.archive_members}
            assert "README.md" in members
            assert "Content/Paks/OddMod.pak" in members
            assert "Copy the `Content/Paks` folder" in exc.install_notes
        else:
            raise AssertionError("unknown layout must request evidence guidance")

        assert not list(os.scandir(game))


verify()
print("ALL PASS")
