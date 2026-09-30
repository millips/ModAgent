import json
import os
import tempfile

os.environ["MODAGENT_DATA_DIR"] = tempfile.mkdtemp(prefix="modagent-workshop-toggle-data-")

from modagent import db, tools
from modagent.config import Config, save


with tempfile.TemporaryDirectory(prefix="modagent-workshop-toggle-game-") as game:
    save(Config(game_root=game, game_slug="palworld"))
    db.init_db()
    db.add_mod(db.InstalledMod(
        id="ws_123456", name="Workshop Test", version="", snapshot_id="",
        files_installed=json.dumps([os.path.join(game, "outside-workshop-item")]),
        installed_by="steam_workshop", game_slug="palworld",
    ))

    cfg = Config(game_root=game, game_slug="palworld")
    disabled = json.loads(tools.execute("mod_disable", {"mod_id": "ws_123456"}, cfg))
    assert disabled["requires_external_manager"] is True
    assert disabled["files_changed"] is False
    assert disabled["subscription_changed"] is False

    enabled = json.loads(tools.execute("mod_enable", {"mod_id": "ws_123456"}, cfg))
    assert enabled["requires_external_manager"] is True
    assert enabled["files_changed"] is False

print("WORKSHOP TOGGLE SAFETY TEST PASSED")
