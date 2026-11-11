"""Structured login prompts must not retry subscriptions or write inventory."""
import asyncio
import json
import os
import tempfile
import types

ROOT = tempfile.mkdtemp(prefix="modagent-browser-login-")
os.environ["MODAGENT_DATA_DIR"] = ROOT
import modagent.db as db
import modagent.tools as tools
from modagent.sources import steam_workshop as sw

db.DB_FILE = os.path.join(ROOT, "state.db")
db.init_db()
cfg = types.SimpleNamespace(nexus_api_key="",tavily_api_key="",game_id=0,game_root=ROOT, game_slug="fixture", game_instance_id="",
    game_name="Fixture", chrome_cdp_port=18888, agent_core_v2="off", tier="subscription", mod_loader="")
tools._refresh_local_inventory = lambda _cfg: []
sw.resolve_appid = lambda _root: 123
calls = []

async def missing(*args):
    calls.append("missing")
    raise sw.SteamLoginRequired("Fixture login required")

sw.search = missing
result = json.loads(tools.execute("workshop_search", {"query":"fixture"}, cfg))
assert result["status"] == "login_required"
sw.subscribe = missing
result = json.loads(tools.execute("workshop_install", {"workshop_id":"98765"}, cfg))
assert result["status"] == "login_required"
assert len(calls) == 2
for payload, expected in [({"error":"no_session"}, True), ({"status":401}, True),
                          ({"status":403}, False), ({"error":"no_response"}, False)]:
    sw.subscribe = lambda *args, value=payload: asyncio.sleep(0, result=value)
    result = json.loads(tools.execute("workshop_install", {"workshop_id":"98765"}, cfg))
    assert (result.get("status") == "login_required") is expected, result
    assert db.get_mod("ws_98765", "fixture") is None
print("PASS Steam missing page / session / 401 prompts; 403 and network errors not mislabeled; no inventory write")
