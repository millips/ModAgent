"""下载进度的进程内共享状态。chat 请求线程写、/downloads/status 轮询请求线程读。"""
import threading
import time

_lock = threading.Lock()
_state = {
    "active": False,
    "items": [],
    "updated": 0.0,
    "started": 0.0,
    "samples": [],
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


def start(mods: list):
    """mods: [{mod_id, name, source?, source_label?}]，开始一批下载。"""
    with _lock:
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
        _state["active"] = True
        now = time.time()
        _state["started"] = now
        _state["updated"] = now
        _state["samples"] = [(now, 0.0)]


def _find(mod_id):
    for it in _state["items"]:
        if str(it["mod_id"]) == str(mod_id):
            return it
    return None


def set_status(mod_id, status: str, error: str = ""):
    with _lock:
        it = _find(mod_id)
        if it:
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
        it = _find(mod_id)
        if it:
            it["status"] = "downloading"
            it["pct"] = max(0, min(100, int(pct)))
        now = time.time()
        _state["updated"] = now
        _record_sample(now)


def set_name(mod_id, name: str):
    with _lock:
        it = _find(mod_id)
        if it and name:
            it["name"] = name
        _state["updated"] = time.time()


def finish():
    with _lock:
        _state["active"] = False
        _state["updated"] = time.time()


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
        if _state["active"] and eta_seconds is None:
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
            "items": [dict(it) for it in _state["items"]],
            "updated": _state["updated"],
            "started": _state["started"],
            "elapsed_seconds": max(0, round(now - _state["started"])) if _state["started"] else 0,
            "overall_pct": round(overall_pct, 1),
            "eta_seconds": eta_seconds,
            "eta_kind": eta_kind,
        }
