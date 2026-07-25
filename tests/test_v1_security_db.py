"""v1.0 release blockers: local API auth, game-scoped IDs, honest patching."""
import importlib
import json
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
    f.write("<root><value>1</value></root>")
result = patcher.patch_file(xml, "value=2")
check("B1 XML patch reports success", result.get("success") is True)
check("B2 XML element updated", ">2</value>" in open(xml, encoding="utf-8").read())

os.environ["MODAGENT_API_TOKEN"] = "test-secret"
import modagent.api as api_module
api_module = importlib.reload(api_module)
with TestClient(api_module.app) as client:
    check("C1 health remains public", client.get("/health").status_code == 200)
    check("C2 missing token rejected", client.get("/status").status_code == 401)
    check("C3 wrong token rejected", client.get("/status", headers={"X-ModAgent-Token": "wrong"}).status_code == 401)
    check("C4 correct token accepted", client.get("/status", headers={"X-ModAgent-Token": "test-secret"}).status_code == 200)
    check("C5 download status is protected", client.get("/downloads/status").status_code == 401)

    from modagent import progress
    progress.start([{"mod_id": "download-test", "name": "Download Test"}])
    progress.set_pct("download-test", 42)
    download_state = client.get(
        "/downloads/status", headers={"X-ModAgent-Token": "test-secret"}
    )
    check("C6 download status accepts renderer token", download_state.status_code == 200)
    payload = download_state.json()
    check("C7 download progress shape", payload["active"] is True and payload["items"][0]["pct"] == 42)
    progress.finish()

    disabled_file = os.path.join(tmp, "disabled-test.pak")
    with open(disabled_file + ".disabled", "w", encoding="utf-8") as f:
        f.write("disabled")
    db.add_mod(db.InstalledMod(
        id="disabled-test", name="Disabled Test", version="1", snapshot_id="",
        files_installed=json.dumps([disabled_file]), game_slug="palworld",
    ))
    mods_state = client.get(
        "/mods?game_slug=palworld", headers={"X-ModAgent-Token": "test-secret"}
    )
    check("C8 disabled mod state comes from disk", mods_state.json()[0]["disabled"] is True)

print("ALL PASS")
