"""Structured selection locks identity and ends post-install discovery."""

import json

from modagent import agent as agent_module
from modagent.agent import Agent


class Config:
    tier = "pro"
    dev_mode = False
    llm_endpoint = "https://example.invalid/v1"
    llm_api_key = "test"
    mod_loader = "BepInEx"


instance = Agent(Config())
instance._selection_action = "confirm"
instance._selection_allowed_nexus_ids = {"39"}
instance._selection_nexus_alias_ids = {
    instance._selection_alias("MoneyValueTracker"): "39",
}
instance._selection_allowed_source_urls = {
    "https://thunderstore.io/c/repo/p/Owner/Allowed/",
}
assert instance._is_error(json.dumps({
    "status": "dependency_blocked",
    "install_blocked": True,
    "message": "dependency missing",
})) is True

wrong = json.loads(instance._exec("nexus_get_detail", {"mod_id": 202}))
assert wrong["error"] == "selection_identity_mismatch"
assert wrong["allowed_mod_ids"] == ["39"]

wrong_batch = json.loads(instance._exec(
    "mod_install_batch", {"mod_ids": ["39", "202"]}
))
assert wrong_batch["error"] == "selection_identity_mismatch"
assert wrong_batch["requested_mod_ids"] == ["202", "39"]

wrong_url = json.loads(instance._exec(
    "download_from_url", {"url": "https://example.invalid/replacement.zip"}
))
assert wrong_url["error"] == "selection_identity_mismatch"

search = json.loads(instance._exec("nexus_search", {"query": "replacement"}))
assert search["error"] == "selection_search_scope_blocked"

snapshot = json.loads(instance._exec("snapshot_create", {"trigger_mod_name": "early"}))
assert snapshot["status"] == "snapshot_deferred_to_verified_install"
assert snapshot["snapshot_created"] is False
assert "顺延" in instance._tool_summary(
    "snapshot_create", json.dumps(snapshot, ensure_ascii=False), True
)

old_execute = agent_module.execute
executed = []


def fake_execute(name, args, cfg):
    executed.append((name, args))
    return json.dumps({
        "files_installed": ["BepInEx/plugins/39/MapMoneyMod.dll"],
        "name": "MoneyValueTracker",
    })


agent_module.execute = fake_execute
try:
    exact_alias = json.loads(instance._exec(
        "mod_download", {"mod_id": "MoneyValueTracker"}
    ))
    assert exact_alias["name"] == "MoneyValueTracker"
    assert executed[-1][1]["mod_id"] == "39"
    assert executed[-1][1]["require_verified_preflight"] is True

    fuzzy_alias = json.loads(instance._exec(
        "mod_download", {"mod_id": "Money Value Tracker"}
    ))
    assert fuzzy_alias["error"] == "selection_identity_mismatch"

    batch_alias = json.loads(instance._exec(
        "mod_install_batch", {"mod_ids": ["MoneyValueTracker"]}
    ))
    assert batch_alias["name"] == "MoneyValueTracker"
    assert executed[-1][1]["mod_ids"] == ["39"]

    installed = json.loads(instance._exec("mod_install", {"mod_id": 39}))
    assert installed["name"] == "MoneyValueTracker"
    assert instance._install_completed_this_turn is True
    blocked_after = json.loads(instance._exec("nexus_search", {"query": "more mods"}))
    assert blocked_after["error"] == "post_install_search_blocked"
finally:
    agent_module.execute = old_execute

print("ALL PASS")
