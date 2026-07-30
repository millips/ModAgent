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


def test_source_alignment_exposes_item_counter_and_current_name():
    progress.start([
        {"mod_id": "a", "name": "Alpha"},
        {"mod_id": "b", "name": "Beta"},
        {"mod_id": "c", "name": "Gamma"},
    ], task_kind="source_align", label="绑定维护来源")
    progress.set_status("a", "done")
    progress.set_status("b", "processing")
    state = progress.snapshot()
    assert state["task_kind"] == "source_align"
    assert state["completed_count"] == 1
    assert state["total_count"] == 3
    assert state["current_item"]["name"] == "Beta"
    assert state["eta_seconds"] is None
    progress.finish()


def test_download_phase_is_exposed_without_faking_byte_progress():
    progress.start(
        [{"mod_id": "nexus-1", "name": "Example", "source": "nexus"}],
        task_kind="download",
        label="下载 Mod",
    )
    progress.set_phase(
        "nexus-1",
        "waiting_verification",
        label="等待完成人机验证",
        detail="验证完成后会自动继续",
        status="waiting_verification",
    )
    waiting = progress.snapshot()
    assert waiting["current_item"]["phase"] == "waiting_verification"
    assert waiting["current_item"]["phase_label"] == "等待完成人机验证"
    assert waiting["current_item"]["detail"] == "验证完成后会自动继续"
    assert waiting["overall_pct"] == 0

    progress.set_phase(
        "nexus-1",
        "browser_download_complete",
        label="浏览器下载完成",
        status="processing",
    )
    resumed = progress.snapshot()
    assert resumed["current_item"]["phase"] == "browser_download_complete"
    assert resumed["current_item"]["status"] == "processing"
    progress.finish(cancelled=True)


def test_exclusive_task_can_be_cancelled_without_being_overwritten():
    assert progress.start(
        [{"mod_id": "a", "name": "Alpha"}],
        task_kind="source_align",
        label="正在对齐",
        exclusive=True,
    ) is True
    assert progress.start(
        [{"mod_id": "b", "name": "Beta"}],
        task_kind="update_check",
        exclusive=True,
    ) is False
    assert progress.request_cancel("update_check") is False
    assert progress.request_cancel("source_align") is True
    assert progress.is_cancel_requested("source_align") is True
    progress.finish(cancelled=True)
    state = progress.snapshot()
    assert state["active"] is False
    assert state["items"][0]["status"] == "cancelled"
