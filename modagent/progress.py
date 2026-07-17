"""下载进度的进程内共享状态。chat 请求线程写、/downloads/status 轮询请求线程读。"""
import threading
import time

_lock = threading.Lock()
_state = {"active": False, "items": [], "updated": 0.0}


def start(mods: list):
    """mods: [{mod_id, name}]，开始一批下载。"""
    with _lock:
        _state["items"] = [{
            "mod_id": m.get("mod_id"),
            "name": m.get("name", "") or f"mod {m.get('mod_id')}",
            "status": "queued",  # queued | downloading | done | failed
            "pct": 0,
            "error": "",
        } for m in mods]
        _state["active"] = True
        _state["updated"] = time.time()


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
        _state["updated"] = time.time()


def set_pct(mod_id, pct: int):
    with _lock:
        it = _find(mod_id)
        if it:
            it["status"] = "downloading"
            it["pct"] = max(0, min(100, int(pct)))
        _state["updated"] = time.time()


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
        return {
            "active": _state["active"],
            "items": [dict(it) for it in _state["items"]],
            "updated": _state["updated"],
        }
