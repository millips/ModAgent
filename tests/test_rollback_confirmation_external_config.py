"""Rollback is two-stage for every profile and includes managed user configs."""

import json
import os
import tempfile
import types
from pathlib import Path

tmp = Path(tempfile.mkdtemp(prefix="modagent-rollback-config-"))
os.environ["MODAGENT_DATA_DIR"] = str(tmp / "data")

from modagent import db, games, snapshot, tools, user_config
from modagent.agent import Agent

db.DB_FILE = str(tmp / "state.db")
db.init_db()
snapshot.SNAPSHOTS_DIR = str(tmp / "snapshots")
user_config.CONFIG_DIR = str(tmp / "state")
documents = tmp / "Documents"
original_root_for = user_config.root_for
original_alive = games.verify_game_alive
user_config.root_for = lambda location: documents
games.verify_game_alive = lambda root: {"alive": True}

try:
    game = tmp / "FINAL FANTASY VII REBIRTH"
    game.mkdir()
    s0 = snapshot.snapshot_create(str(game), "finalfantasy7rebirth", trigger_mod_name="安装前")

    engine = documents / "My Games/FINAL FANTASY VII REBIRTH/Saved/Config/WindowsNoEditor/Engine.ini"
    engine.parent.mkdir(parents=True)
    original = "[ConsoleVariables]\nr.Streaming=1\n"
    engine.write_text(original, encoding="utf-8")
    r = user_config.write_config(
        "documents", "My Games/FINAL FANTASY VII REBIRTH/Saved/Config/WindowsNoEditor/Engine.ini",
        "[/Script/EngineSettings.GameMapsSettings]\nGameInstanceClass=/FF7RML/BP_EndGameInstance.BP_EndGameInstance_C\n",
        game_slug="finalfantasy7rebirth", mod_id="1061",
    )
    assert r["verified"] and "GameInstanceClass=" in engine.read_text(encoding="utf-8")

    preview = snapshot.snapshot_restore_preview(s0)
    assert preview["external_configs"]["action_count"] == 1, preview
    assert preview["external_configs"]["actions"][0]["action"] == "restore"

    cfg = types.SimpleNamespace(
        nexus_api_key="", tavily_api_key="", game_name="FINAL FANTASY VII REBIRTH",
        game_slug="finalfantasy7rebirth", game_id=7237, game_root=str(game),
        tier="subscription", chrome_cdp_port=18888, manual_mod_dirs={}, dev_mode=False,
        llm_endpoint="", llm_api_key="",
    )
    gate = json.loads(tools.execute("snapshot_restore", {"snapshot_id": s0}, cfg))
    assert gate["requires_confirmation"] and gate["confirmation_token"]
    denied = json.loads(tools.execute("snapshot_restore", {
        "snapshot_id": s0, "confirmed": True, "confirmation_token": "invalid",
    }, cfg))
    assert denied["error"] == "rollback_confirmation_invalid"
    assert "GameInstanceClass=" in engine.read_text(encoding="utf-8")

    done = json.loads(tools.execute("snapshot_restore", {
        "snapshot_id": s0, "confirmed": True,
        "confirmation_token": gate["confirmation_token"],
    }, cfg))
    assert done["complete"], done
    assert engine.read_text(encoding="utf-8") == original
    assert done["external_configs"]["restored"] == 1

    # Agent may not preview and self-confirm inside one model turn.
    agent = Agent(cfg)
    agent._turn_id = "turn-1"
    agent._current_user_msg = "帮我回滚到安装前"
    gated = json.loads(agent._exec("snapshot_restore", {"snapshot_id": s0}))
    blocked = json.loads(agent._exec("snapshot_restore", {
        "snapshot_id": s0, "confirmed": True,
        "confirmation_token": gated["confirmation_token"],
    }))
    assert blocked["error"] == "confirmation_requires_new_user_turn"
    agent._turn_id = "turn-2"
    agent._current_user_msg = "确认回滚"
    accepted = json.loads(agent._exec("snapshot_restore", {
        "snapshot_id": s0, "confirmed": True,
        "confirmation_token": gated["confirmation_token"],
    }))
    assert accepted["complete"], accepted
finally:
    user_config.root_for = original_root_for
    games.verify_game_alive = original_alive

print("ROLLBACK CONFIRMATION + EXTERNAL CONFIG TESTS PASSED")
