from modagent import progress


def test_cancellation_matches_generation(monkeypatch):
    state = dict(progress._state, active=True, task_kind="download", generation=42, cancel_requested=False)
    monkeypatch.setattr(progress, "_state", state)
    assert not progress.request_cancel("download", generation=41)
    assert not progress.request_cancel("download", generation="42")
    assert not progress.request_cancel("download", generation=True)
    assert not progress.request_cancel("mod_update", generation=42)
    assert not state["cancel_requested"]
    assert progress.request_cancel("download", generation=42)
    assert state["cancel_requested"]


def test_legacy_and_inactive_cancellation(monkeypatch):
    state = dict(progress._state, active=False, task_kind="download", generation=42, cancel_requested=False)
    monkeypatch.setattr(progress, "_state", state)
    assert not progress.request_cancel("download", generation=42)
    state["active"] = True
    assert progress.request_cancel("download")


def test_api_passes_generation_without_cancelling_new_task(monkeypatch):
    from modagent import api

    state = dict(progress._state, active=True, task_kind="download", generation=42, cancel_requested=False, items=[])
    monkeypatch.setattr(progress, "_state", state)
    assert api.cancel_active_task({"task_kind": "download", "generation": 41})["ok"] is False
    assert not state["cancel_requested"]
    assert api.cancel_active_task({"task_kind": "download", "generation": 42})["ok"] is True
