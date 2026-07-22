"""Pro recommendation selection state survives a session reload."""
import json
import os
import tempfile

from modagent import db


tmp = tempfile.mkdtemp()
old_db = db.DB_FILE
db.DB_FILE = os.path.join(tmp, "state.db")
try:
    db.init_db()
    db.create_session("ui-session", "recommend", "game")
    state = {
        "kind": "recommendation_set",
        "phase": "confirm",
        "selected_keys": ["nexus:abc", "github:def"],
        "items": [{"selection_key": "nexus:abc", "name": "One"}],
    }
    db.update_session_ui_state("ui-session", state)
    stored = db.get_session("ui-session")
    assert json.loads(stored["ui_state"]) == state

    # Updating model history must not corrupt the independent UI payload.
    db.update_session_messages(
        "ui-session", [{"role": "user", "content": "recommend mods"}]
    )
    stored = db.get_session("ui-session")
    assert json.loads(stored["ui_state"]) == state

    # Completed cards are terminal transcript history, not resumable floating
    # UI. The renderer deliberately ignores them after a reload so they cannot
    # jump to the newest chat position.
    completed = {**state, "phase": "completed"}
    db.update_session_ui_state("ui-session", completed)
    stored = db.get_session("ui-session")
    assert json.loads(stored["ui_state"])["phase"] == "completed"
finally:
    db.DB_FILE = old_db

print("ALL PASS")
