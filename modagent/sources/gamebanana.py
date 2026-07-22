"""GameBanana 适配器：FPS/格斗/Source/FNF/Sonic 等海量皮肤与 mod。公开 API(apiv11,无需 key)。"""
import re
import time
import urllib.parse

from . import _http_json, _safe, _dest
from .. import downloader

_GAME_CACHE = {}                 # game_name(lower) -> (ts, game_id|None)
_GAME_TTL = 3600


def find_game(game_name: str):
    """游戏名 → GameBanana 游戏 id(apiv11 Util/Game/NameMatch,实测端点)。没收录返回 None。"""
    key = (game_name or "").strip().lower()
    if not key:
        return None
    hit = _GAME_CACHE.get(key)
    if hit and time.time() - hit[0] < _GAME_TTL:
        return hit[1]
    gid = None
    try:
        data = _http_json("https://gamebanana.com/apiv11/Util/Game/NameMatch?_sName="
                          + urllib.parse.quote(game_name.strip()))
        recs = data.get("_aRecords") or []
        for r in recs:                                   # 精确名优先,退而取首个匹配
            if (r.get("_sName") or "").strip().lower() == key:
                gid = r.get("_idRow")
                break
        if gid is None and recs:
            gid = recs[0].get("_idRow")
    except Exception:
        return None                                      # 站点不可达 → 当没收录,不缓存失败
    _GAME_CACHE[key] = (time.time(), gid)
    return gid


def search(game_id: int, query: str, limit: int = 10) -> list:
    """在某游戏板块内按关键词搜 mod(apiv11 Util/Search/Results,实测端点)。"""
    data = _http_json(
        "https://gamebanana.com/apiv11/Util/Search/Results?_sModelName=Mod&_sOrder=best_match"
        f"&_idGameRow={int(game_id)}&_sSearchString=" + urllib.parse.quote((query or "").strip()))
    out = []
    for r in (data.get("_aRecords") or [])[:limit]:
        ts = r.get("_tsDateModified") or r.get("_tsDateAdded") or 0
        out.append({
            "name": r.get("_sName", ""),
            "url": r.get("_sProfileUrl", ""),
            "updated_at": time.strftime("%Y-%m-%d", time.localtime(ts)) if ts else "",
            "has_files": bool(r.get("_bHasFiles")),
        })
    return out


def _parse(url: str):
    m = re.search(r"gamebanana\.com/mods/(\d+)", url)
    return int(m.group(1)) if m else None


def download(url: str, game_slug: str, progress_callback=None) -> dict:
    mid = _parse(url)
    if not mid:
        raise RuntimeError("无法解析 GameBanana 链接（需形如 gamebanana.com/mods/<id>）")
    data = _http_json(f"https://gamebanana.com/apiv11/Mod/{mid}/DownloadPage")
    files = data.get("_aFiles", []) or []
    if not files:
        raise RuntimeError("GameBanana 该 mod 没有可下载文件")
    f = files[0]
    dlurl = f.get("_sDownloadUrl")
    if not dlurl:
        raise RuntimeError("GameBanana 未返回下载链接")
    fn = f.get("_sFile", f"gamebanana_{mid}.zip")
    dest = _dest(game_slug, f"gb_{mid}_{_safe(fn)}")
    downloader.download_file(dlurl, dest, progress_callback)
    return {"local_path": dest, "name": fn, "source": "gamebanana", "version": ""}
