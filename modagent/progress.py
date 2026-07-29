"""下载进度的进程内共享状态。chat 请求线程写、/downloads/status 轮询请求线程读。"""
import threading
import time

_lock = threading.Lock()
_thread_state = threading.local()
_state = {
    "active": False,
    "items": [],
    "task_kind": "",
    "label": "",
    "exclusive": False,
    "cancel_requested": False,
    "cancel_reason": "",
    "updated": 0.0,
    "started": 0.0,
    "samples": [],
    "generation": 0,
}

_SOURCE_LABELS = {
    "nexus": "Nexus",
    "workshop": "Steam 创意工坊",
    "github": "GitHub",
    "thunderstore": "Thunderstore",
    "gamebanana": "GameBanana",
}


def _overall_pct() -> float:
    items = _state["items"]
    if not items:
        return 0.0
    return sum(float(item.get("pct", 0)) for item in items) / len(items)


def _record_sample(now: float) -> None:
    """Keep a short moving window for a stable, evidence-based ETA."""
    pct = _overall_pct()
    samples = _state["samples"]
    if not samples or pct > samples[-1][1]:
        samples.append((now, pct))
    cutoff = now - 30.0
    _state["samples"] = [sample for sample in samples if sample[0] >= cutoff][-30:]


def start(
    mods: list, *, task_kind: str = "download", label: str = "",
    exclusive: bool = False,
) -> bool:
    """mods: [{mod_id, name, source?, source_label?}]，开始一批下载。"""
    with _lock:
        if _state["active"] and (_state["exclusive"] or exclusive):
            return False
        _state["generation"] += 1
        _thread_state.generation = _state["generation"]
        _state["items"] = [{
            "mod_id": m.get("mod_id"),
            "name": m.get("name", "") or f"mod {m.get('mod_id')}",
            "source": str(m.get("source") or "").strip().lower(),
            "source_label": (
                str(m.get("source_label") or "").strip()
                or _SOURCE_LABELS.get(
                    str(m.get("source") or "").strip().lower(), ""
                )
            ),
            "status": "queued",  # queued | downloading | done | failed
            "pct": 0,
            "error": "",
        } for m in mods]
        _state["task_kind"] = str(task_kind or "download")
        _state["label"] = str(label or "")
        _state["exclusive"] = bool(exclusive)
        _state["cancel_requested"] = False
        _state["cancel_reason"] = ""
        _state["active"] = True
        now = time.time()
        _state["started"] = now
        _state["updated"] = now
        _state["samples"] = [(now, 0.0)]
        return True


def _find(mod_id):
    for it in _state["items"]:
        if str(it["mod_id"]) == str(mod_id):
            return it
    return None


def _owns_current_task() -> bool:
    """Prevent a cancelled/stale worker from mutating a newer progress task."""
    return (
        bool(_state["active"])
        and getattr(_thread_state, "generation", None) == _state["generation"]
    )


def set_status(mod_id, status: str, error: str = ""):
    with _lock:
        if not _owns_current_task():
            return
        it = _find(mod_id)
        if it:
            if _state["cancel_requested"] and status == "failed":
                status = "cancelled"
                error = _state["cancel_reason"] or error or "用户已取消"
            it["status"] = status
            if status == "done":
                it["pct"] = 100
            if error:
                it["error"] = error[:200]
        now = time.time()
        _state["updated"] = now
        _record_sample(now)


def set_pct(mod_id, pct: int):
    with _lock:
        if not _owns_current_task():
            return
        it = _find(mod_id)
        if it:
            it["status"] = "downloading"
            it["pct"] = max(0, min(100, int(pct)))
        now = time.time()
        _state["updated"] = now
        _record_sample(now)


def set_name(mod_id, name: str):
    with _lock:
        if not _owns_current_task():
            return
        it = _find(mod_id)
        if it and name:
            it["name"] = name
        _state["updated"] = time.time()


def request_cancel(task_kind: str = "") -> bool:
    """Cooperatively cancel the current task without killing the backend."""
    with _lock:
        expected = str(task_kind or "").strip()
        if not _state["active"]:
            return False
        if expected and expected != _state["task_kind"]:
            return False
        _state["cancel_requested"] = True
        _state["cancel_reason"] = "用户已取消"
        _state["updated"] = time.time()
        return True


def is_cancel_requested(task_kind: str = "") -> bool:
    with _lock:
        expected = str(task_kind or "").strip()
        return bool(
            _state["active"]
            and _state["cancel_requested"]
            and (not expected or expected == _state["task_kind"])
        )


def active_task() -> dict:
    with _lock:
        return {
            "active": bool(_state["active"]),
            "task_kind": str(_state["task_kind"] or ""),
            "exclusive": bool(_state["exclusive"]),
            "cancel_requested": bool(_state["cancel_requested"]),
        }


def finish(*, cancelled: bool = False):
    with _lock:
        if not _owns_current_task():
            return
        if cancelled or _state["cancel_requested"]:
            for item in _state["items"]:
                if item.get("status") not in {"done", "failed"}:
                    item["status"] = "cancelled"
                    item["error"] = _state["cancel_reason"] or "用户已取消"
        _state["active"] = False
        _state["exclusive"] = False
        _state["updated"] = time.time()


def abort_active(reason: str = "用户已停止") -> bool:
    """Immediately retire the visible task; stale worker updates are ignored."""
    with _lock:
        if not _state["active"]:
            return False
        _state["cancel_requested"] = True
        _state["cancel_reason"] = str(reason or "用户已停止")
        for item in _state["items"]:
            if item.get("status") not in {"done", "failed"}:
                item["status"] = "cancelled"
                item["error"] = _state["cancel_reason"]
        _state["active"] = False
        _state["exclusive"] = False
        _state["updated"] = time.time()
        return True


def snapshot() -> dict:
    with _lock:
        now = time.time()
        overall_pct = _overall_pct()
        eta_seconds = None
        eta_kind = "estimating"
        samples = _state["samples"]
        # ETA is intentionally withheld until measurable progress exists.  This
        # prevents a fabricated or wildly jumping time estimate at 0-1%.
        if _state["active"] and 1.0 < overall_pct < 100.0 and len(samples) >= 2:
            first, last = samples[0], samples[-1]
            elapsed_window = last[0] - first[0]
            progressed = last[1] - first[1]
            if elapsed_window >= 1.0 and progressed > 0:
                rate = progressed / elapsed_window
                if rate >= 0.02:
                    eta_seconds = min(24 * 3600, round((100.0 - overall_pct) / rate))
                    eta_kind = "measured"
        if (
            _state["active"]
            and eta_seconds is None
            and _state["task_kind"] in {"download", "mod_update"}
        ):
            # Before the first response bytes arrive there is no transfer rate,
            # but leaving the UI at "estimating" for a minute feels broken.
            # Give a conservative stage baseline, then replace it as soon as
            # measured samples are available.
            remaining = sum(
                1.0 if item.get("status") == "queued"
                else max(0.0, (100.0 - float(item.get("pct", 0))) / 100.0)
                for item in _state["items"]
                if item.get("status") not in {"done", "failed"}
            )
            if remaining > 0:
                eta_seconds = max(15, round(75 * remaining))
                eta_kind = "baseline"
        return {
            "active": _state["active"],
            "task_kind": _state["task_kind"],
            "label": _state["label"],
            "exclusive": _state["exclusive"],
            "cancel_requested": _state["cancel_requested"],
            "cancel_reason": _state["cancel_reason"],
            "items": [dict(it) for it in _state["items"]],
            "completed_count": sum(
                1 for item in _state["items"]
                if item.get("status") in {"done", "failed", "cancelled"}
            ),
            "total_count": len(_state["items"]),
            "current_item": next((
                {
                    "mod_id": item.get("mod_id"),
                    "name": item.get("name", ""),
                    "status": item.get("status", ""),
                }
                for item in _state["items"]
                if item.get("status") in {"processing", "downloading"}
            ), None),
            "updated": _state["updated"],
            "started": _state["started"],
            "elapsed_seconds": max(0, round(now - _state["started"])) if _state["started"] else 0,
            "overall_pct": round(overall_pct, 1),
            "eta_seconds": eta_seconds,
            "eta_kind": eta_kind,
        }
