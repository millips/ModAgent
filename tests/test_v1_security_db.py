"""v1.0 release blockers: local API auth, game-scoped IDs, honest patching."""
import importlib
import os
import sqlite3
import tempfile

from fastapi.testclient import TestClient

from modagent import db, patcher


def check(name, condition):
    if not condition:
        raise AssertionError(name)
    print("PASS", name)


tmp = tempfile.mkdtemp(prefix="modagent_v1_")
db.DB_FILE = os.path.join(tmp, "state.db")
db.init_db()

db.add_mod(db.InstalledMod(id="123", name="Pal mod", version="1", snapshot_id="", game_slug="palworld"))
db.add_mod(db.InstalledMod(id="123", name="Skyrim mod", version="2", snapshot_id="", game_slug="skyrimspecialedition"))
check("A1 same source ID survives across games", len(db.get_installed_mods()) == 2)
check("A2 game-scoped lookup", db.get_mod("123", "palworld").name == "Pal mod")
db.remove_mod("123", "palworld")
check("A3 scoped removal keeps other game", db.get_mod("123", "skyrimspecialedition") is not None)

pk = [r[1] for r in sqlite3.connect(db.DB_FILE).execute("PRAGMA table_info(installed_mods)") if r[5]]
check("A4 composite primary key", set(pk) == {"id", "game_slug"})

xml = os.path.join(tmp, "plugin.xml")
with open(xml, "w", encoding="utf-8") as f:
    f.write("<root />")
result = patcher.patch_file(xml, "value=2")
check("B1 unsupported patch reports failure", result.get("success") is False)
check("B2 unsupported patch leaves file intact", open(xml, encoding="utf-8").read() == "<root />")

os.environ["MODAGENT_API_TOKEN"] = "test-secret"
import modagent.api as api_module
api_module = importlib.reload(api_module)
with TestClient(api_module.app) as client:
    check("C1 health remains public", client.get("/health").status_code == 200)
    check("C2 missing token rejected", client.get("/status").status_code == 401)
    check("C3 wrong token rejected", client.get("/status", headers={"X-ModAgent-Token": "wrong"}).status_code == 401)
    check("C4 correct token accepted", client.get("/status", headers={"X-ModAgent-Token": "test-secret"}).status_code == 200)

print("ALL PASS")
