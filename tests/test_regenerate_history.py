"""Regenerate must replace the old reply instead of appending the prompt again."""
import json
import os
import tempfile

from fastapi import HTTPException

from modagent import api, db
from modagent.agent import Agent


tmp = tempfile.mkdtemp()
old_db = db.DB_FILE
db.DB_FILE = os.path.join(tmp, "state.db")
db.init_db()

allok = True


def check(label, condition):
    global allok
    print(("PASS " if condition else "FAIL ") + label)
    allok = allok and bool(condition)


sid = "regen_session"
db.create_session(sid, "regen", "local_unknown")
old_history = [
    {"role": "user", "content": "first"},
    {"role": "assistant", "content": "first answer"},
    {"role": "user", "content": "target prompt"},
    {
        "role": "assistant",
        "content": "",
        "tool_calls": [{
            "id": "call-old",
            "type": "function",
            "function": {"name": "github_search", "arguments": "{}"},
        }],
    },
    {"role": "tool", "tool_call_id": "call-old", "content": "[]"},
    {"role": "assistant", "content": "old answer"},
]
db.update_session_messages(sid, old_history)
api.agents.clear()
api._agent_last_used.clear()
api.agents[sid] = Agent(api.cfg)
api.agents[sid].history = list(old_history)

replacement_base = [
    {"role": "user", "content": "first"},
    {"role": "assistant", "content": "first answer"},
]
result = api.update_session_message_history(
    sid, api.SessionMessagesUpdate(messages=replacement_base))
stored = db.get_session(sid)
stored_messages = json.loads(stored["messages"])

check("A1 endpoint reports truncated count", result["messages_count"] == 2)
check("A2 database old reply removed", stored_messages == replacement_base)
check("A3 in-memory Agent history truncated", api.agents[sid].history == replacement_base)
check("A4 target prompt is not duplicated", all(
    m.get("content") != "target prompt" for m in stored_messages))

try:
    api.update_session_message_history(
        sid, api.SessionMessagesUpdate(messages=[
            {"role": "tool", "content": "not allowed"},
        ]))
    invalid_rejected = False
except HTTPException as exc:
    invalid_rejected = exc.status_code == 400
check("B1 structured/tool messages rejected at public endpoint", invalid_rejected)

db.DB_FILE = old_db
api.agents.clear()
api._agent_last_used.clear()

print("\nALL PASS" if allok else "\nSOME FAILED")
raise SystemExit(0 if allok else 1)
