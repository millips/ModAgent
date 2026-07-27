"""A successful detail check upgrades the existing decision row in-place."""

import json
import os
import tempfile

os.environ["MODAGENT_DATA_DIR"] = tempfile.mkdtemp(prefix="ma_promotion_")

from modagent import agent as agent_module, db  # noqa: E402
from modagent.agent import Agent  # noqa: E402
from modagent.recommendation_ui import normalize_recommendations  # noqa: E402


class Config:
    tier = "pro"
    dev_mode = False
    game_slug = "repo"
    game_root = ""
    game_instance_id = ""
    game_name = "R.E.P.O."
    mod_loader = "BepInEx"
    recommendation_limit = 10
    llm_endpoint = "https://example.invalid/v1"
    llm_api_key = "test"


def chunk(content=None, tool_calls=None):
    delta = type("Delta", (), {"content": content, "tool_calls": tool_calls})()
    return type("Chunk", (), {
        "choices": [type("Choice", (), {"delta": delta})()],
    })()


detail_call = type("ToolCall", (), {
    "index": 0,
    "id": "detail-233",
    "function": type("Function", (), {
        "name": "nexus_get_detail",
        "arguments": '{"mod_id":233}',
    })(),
})()


class FakeAgent(Agent):
    def __init__(self):
        super().__init__(Config())
        self.round = 0
        self.session_id = "promotion-session"

    def _stream(self, _messages, _tools):
        self.round += 1
        if self.round == 1:
            return [chunk(tool_calls=[detail_call])]
        return [chunk(content="详情核验完成，请在原清单继续。")]

    def _exec(self, _name, _args):
        return json.dumps({
            "mod_id": 233,
            "name": "Admin Menu",
            "summary": "Host administration menu.",
            "version": "1.1.7",
            "dependency_labels": [],
            "required_loader": "",
        })

    def _localize_recommendation_set(self, payload):
        return payload


db.init_db()
db.create_session("promotion-session", "verify", "repo")
state = normalize_recommendations({
    "recommendations": [{
        "mod_id": 233,
        "name": "Admin Menu",
        "summary": "Host administration menu.",
    }],
}, mod_loader="BepInEx")
key = state["items"][0]["selection_key"]
state["wanted_keys"] = [key]
db.update_session_ui_state("promotion-session", state)

old_prompt = agent_module.build_prompt
old_tools = agent_module.build_tools_definitions
old_report = agent_module.ENABLE_REPORT_VALIDATION
old_state = agent_module.ENABLE_STATE_CHECK
agent_module.build_prompt = lambda _cfg: "system"
agent_module.build_tools_definitions = lambda _tier: [{
    "type": "function", "function": {"name": "nexus_get_detail"},
}]
agent_module.ENABLE_REPORT_VALIDATION = False
agent_module.ENABLE_STATE_CHECK = False

try:
    events = [
        json.loads(value)
        for value in FakeAgent().chat_stream("重新核验 Admin Menu")
    ]
    updates = [
        event["recommendations_update"]
        for event in events if event.get("recommendations_update")
    ]
    assert len(updates) == 1
    assert updates[0]["promotion"]["selection_key"] == key
    assert updates[0]["items"][0]["installable"] is True
    assert updates[0]["selected_keys"] == [key]
    assert updates[0]["wanted_keys"] == []
    assert not any(event.get("recommendations") for event in events)
    stored = json.loads(db.get_session("promotion-session")["ui_state"])
    assert stored["selected_keys"] == [key]
finally:
    agent_module.build_prompt = old_prompt
    agent_module.build_tools_definitions = old_tools
    agent_module.ENABLE_REPORT_VALIDATION = old_report
    agent_module.ENABLE_STATE_CHECK = old_state

print("ALL PASS")
