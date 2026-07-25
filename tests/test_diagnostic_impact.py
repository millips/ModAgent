"""Semantic diagnostic impact and confirmation regressions."""
import json
import os
import tempfile
import types

import modagent.config as config


TMP = tempfile.mkdtemp()
config.CONFIG_DIR = os.path.join(TMP, "cfg")
os.makedirs(config.CONFIG_DIR, exist_ok=True)

import modagent.db as db
from modagent import tools
from modagent.agent import Agent
from modagent.diagnostic_impact import build_diagnostic_strategy, classify_mod


db.DB_FILE = os.path.join(TMP, "state.db")
db.init_db()
GAME = os.path.join(TMP, "Game")
os.makedirs(GAME, exist_ok=True)


def add(mod_id, name, dependencies=None, disabled=False):
    path = os.path.join(GAME, f"{mod_id}.pak")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(name)
    if disabled:
        os.rename(path, path + ".disabled")
    mod = db.InstalledMod(
        id=mod_id, name=name, version="1", snapshot_id="",
        files_installed=json.dumps([path]), dependencies=json.dumps(dependencies or []),
        game_slug="ff7r",
    )
    db.add_mod(mod)
    return mod


hook = add("hook", "FFVIIHook - INI and dev console unlocker")
loader = add("rml", "Reunion Mod Loader", ["hook"])
dresscode = add("dresscode", "Dresscode - Costume Changer", ["rml"])
sword = add("sword", "Sword of Bahamut - Dresscode", ["dresscode"], disabled=True)

cfg = types.SimpleNamespace(
    nexus_api_key="", game_slug="ff7r", game_id=0, game_root=GAME,
    tier="pro", chrome_cdp_port=18888,
)


def execute(name, args):
    return json.loads(tools.execute(name, args, cfg))


# Classification remains generic but has useful player-facing roles.
assert classify_mod(hook)["role"] == "framework"
assert classify_mod(dresscode)["role"] == "appearance_system"
assert classify_mod(sword)["role"] == "appearance"

# Already-disabled dependents are described but never scheduled a second time.
preview = execute("mod_disable", {"mod_id": "dresscode"})
assert preview["requires_confirmation"] is True
assert [item["id"] for item in preview["will_disable"]] == ["dresscode"]
assert [item["id"] for item in preview["already_disabled"]] == ["sword"]
assert preview["dependents"] == []
support = preview["decision_support"]
assert support["reversible"] is True
assert "换装" in support["player_impact"][0]["functionality_lost"]
assert "不会卸载或删除" in support["summary"]
assert any(item["name"].startswith("FFVIIHook") for item in support["retained"])
assert any(item["name"].startswith("Reunion") for item in support["retained"])
assert not any(item["id"] == "sword" for item in support["retained"])
assert "已经禁用" in support["already_inactive"][0]["note"]
assert support["next_if_fixed"] and support["next_if_not_fixed"]

# The confirmed operation uses the preview token and touches only the active item.
done = execute("mod_disable", {
    "mod_id": "dresscode", "confirmed": True,
    "confirmation_token": preview["confirmation_token"],
})
assert done["verified"] is True
assert [item["id"] for item in done["disabled_mods"]] == ["dresscode"]

# A direct log attribution is ranked ahead of a broad framework fallback.
strategy = build_diagnostic_strategy({"findings": [{
    "broken_mods": [{"mod": "Dresscode - Costume Changer"}],
    "attributed_mods": [{"name": "FFVIIHook - INI and dev console unlocker"}],
}]}, [hook, loader, dresscode, sword])
assert strategy["evidence_level"] == "direct"
assert strategy["ranked_candidates"][0]["id"] == "dresscode"
assert strategy["ranked_candidates"][-1]["role"] == "framework"
assert "影响范围最小" in strategy["isolation_policy"]

# Even a poor LLM reply is deterministically completed with the structured
# player impact before it reaches the chat UI.
guarded = Agent._ensure_disable_decision_support(
    "禁用 5 个文件，确认吗？",
    [{"role": "tool", "content": json.dumps(preview, ensure_ascii=False)}],
)
assert "你会暂时失去" in guarded
assert "仍会保留" in guarded
assert "如何恢复" in guarded
assert "不会再次修改" in guarded
assert "在你确认前不会修改文件" in guarded

print("ALL PASS")
