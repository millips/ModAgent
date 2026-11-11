"""A mixed local/Workshop toggle batch must make no partial changes."""

import json
import os
import tempfile

os.environ["MODAGENT_DATA_DIR"] = tempfile.mkdtemp(
    prefix="modagent-toggle-preflight-data-"
)

from modagent import db
from modagent.agent import Agent
from modagent.config import Config


db.init_db()
db.add_mod(db.InstalledMod(
    id="local_mod", name="Local Mod", version="1.0", snapshot_id="",
    files_installed="[]", installed_by="modagent", game_slug="palworld",
))
db.add_mod(db.InstalledMod(
    id="ws_123", name="Workshop Mod", version="", snapshot_id="",
    files_installed="[]", installed_by="steam_workshop", game_slug="palworld",
))

agent = Agent(Config(game_slug="palworld"))
calls = [
    {"function": {"name": "mod_disable", "arguments": json.dumps({"mod_id": "local_mod"})}},
    {"function": {"name": "mod_disable", "arguments": json.dumps({"mod_id": "ws_123"})}},
]
result = json.loads(agent._batch_toggle_preflight(calls))
assert result["blocked"] is True
assert result["no_changes_made"] is True
assert result["steam_workshop_targets"][0]["mod_id"] == "ws_123"
assert result["local_file_targets"][0]["mod_id"] == "local_mod"

print("MIXED TOGGLE BATCH PREFLIGHT PASSED")
