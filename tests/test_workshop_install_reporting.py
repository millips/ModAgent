"""Regression tests for truthful Steam Workshop installation reports."""
import asyncio
import json
import os
import tempfile
import types

import modagent.db as db
import modagent.tools as tools
from modagent import progress
from modagent.sources import steam_workshop as workshop


ROOT = tempfile.mkdtemp(prefix="modagent-workshop-report-")
GAME = os.path.join(ROOT, "SteamLibrary", "steamapps", "common", "TestGame")
os.makedirs(GAME, exist_ok=True)
db.DB_FILE = os.path.join(ROOT, "state.db")
db.init_db()


def check(label, condition):
    print(("PASS " if condition else "FAIL ") + label)
    if not condition:
        raise AssertionError(label)


cfg = types.SimpleNamespace(
    nexus_api_key="",
    tavily_api_key="",
    game_slug="testgame",
    game_id=0,
    game_root=GAME,
    game_name="Test Game",
    tier="subscription",
    chrome_cdp_port=18888,
    mod_loader="",
    game_instance_id="",
)

tools._refresh_local_inventory = lambda _cfg: []
workshop.resolve_appid = lambda _root: 123
workshop.get_titles = lambda ids: {str(ids[0]): "Named Workshop Mod"}
workshop.subscribe = lambda *_args, **_kwargs: asyncio.sleep(0, result={"ok": True})
progress.start = lambda *_args, **_kwargs: None
progress.finish = lambda *_args, **_kwargs: None
progress.set_status = lambda *_args, **_kwargs: None
progress.set_pct = lambda *_args, **_kwargs: None


async def pending_download(*_args, **_kwargs):
    return {"downloaded": False, "path": os.path.join(ROOT, "missing"), "files": []}


workshop.wait_for_download = pending_download
pending = json.loads(tools.execute("workshop_install", {"workshop_id": "12345"}, cfg))
check("pending result has explicit status", pending["status"] == "steam_download_pending")
check("pending result is not reported as installed", pending["results"][0]["ok"] is False)
check("pending result does not create installed record", db.get_mod("ws_12345", "testgame") is None)
check("pending keeps readable Steam title", pending["name"] == "Named Workshop Mod")


content = os.path.join(ROOT, "SteamLibrary", "steamapps", "workshop", "content", "123", "67890")
os.makedirs(content, exist_ok=True)
with open(os.path.join(content, "mod.pak"), "w", encoding="utf-8") as handle:
    handle.write("test")


async def completed_download(*_args, **_kwargs):
    return {"downloaded": True, "path": content, "files": [os.path.join(content, "mod.pak")]}


workshop.wait_for_download = completed_download
completed = json.loads(tools.execute("workshop_install", {"workshop_id": "67890"}, cfg))
check("completed result has explicit status", completed["status"] == "completed")
check("completed result is reported as installed", completed["results"][0]["ok"] is True)
check("completed result creates installed record", db.get_mod("ws_67890", "testgame").name == "Named Workshop Mod")

print("ALL PASS")
