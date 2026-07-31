"""Street Fighter 6 RE Engine archives preserve their natives tree."""
import os
import tempfile
import zipfile

from modagent import installer


def verify():
    with tempfile.TemporaryDirectory(prefix="ma-sf6-route-") as root:
        archive = os.path.join(root, "sf6-mod.zip")
        game = os.path.join(root, "Street Fighter 6")
        os.makedirs(game)
        with zipfile.ZipFile(archive, "w") as bundle:
            bundle.writestr("CoolOutfit/modinfo.ini", "name=Cool Outfit")
            bundle.writestr("CoolOutfit/preview.png", b"preview")
            bundle.writestr(
                "CoolOutfit/natives/stm/product/model/esf/esf001.mesh.240424828",
                b"mesh",
            )
            bundle.writestr(
                "CoolOutfit/natives/stm/product/model/esf/esf001.mdf2.40",
                b"material",
            )

        result = installer.install_mod(
            archive, game, "local_street_fighter_6"
        )
        expected = os.path.join(
            game, "natives", "stm", "product", "model", "esf",
            "esf001.mesh.240424828",
        )
        assert os.path.isfile(expected)
        assert len(result["installed"]) == 2
        assert not os.path.exists(os.path.join(game, "modinfo.ini"))
        assert not os.path.exists(os.path.join(game, "preview.png"))


verify()
print("ALL PASS")
