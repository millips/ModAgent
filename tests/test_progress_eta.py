"""Progress aggregation and ETA regression checks."""
from unittest.mock import patch

from modagent import progress


def test_batch_progress_is_aggregated_and_eta_waits_for_signal():
    with patch.object(progress.time, "time", return_value=100.0):
        progress.start([
            {"mod_id": 1, "name": "one", "source": "nexus"},
            {"mod_id": 2, "name": "two"},
        ])
        initial = progress.snapshot()
    assert initial["overall_pct"] == 0
    assert initial["eta_seconds"] == 150
    assert initial["eta_kind"] == "baseline"
    assert initial["items"][0]["source"] == "nexus"
    assert initial["items"][0]["source_label"] == "Nexus"

    with patch.object(progress.time, "time", return_value=105.0):
        progress.set_pct(1, 50)
        measured = progress.snapshot()
    assert measured["overall_pct"] == 25
    assert measured["elapsed_seconds"] == 5
    assert measured["eta_seconds"] == 15
    assert measured["eta_kind"] == "measured"


def test_done_items_count_as_complete():
    with patch.object(progress.time, "time", return_value=200.0):
        progress.start([
            {"mod_id": "a", "name": "A"},
            {"mod_id": "b", "name": "B"},
        ])
    with patch.object(progress.time, "time", return_value=204.0):
        progress.set_status("a", "done")
        state = progress.snapshot()
    assert state["items"][0]["pct"] == 100
    assert state["overall_pct"] == 50
    assert state["eta_seconds"] == 4
