"""多来源 Mod 适配器。每个来源实现 download(url, game_slug, progress_callback) -> dict。
下载下来的压缩包统一进 downloads/<game_slug>/，之后复用现有的解压/安装/快照流水线。"""
import json
import gzip
import os
import re
import ssl
import time
import urllib.request

from .. import downloader


class RequestCancelled(RuntimeError):
    pass


def _http_json(
    url: str, headers: dict = None, *, timeout: int = 12,
    total_timeout: int = 60, cancel_check=None,
) -> dict:
    ctx = ssl._create_unverified_context()
    h = {
        "User-Agent": "ModAgent/1.3",
        "Accept": "application/json",
        # Thunderstore's community catalogue is tens of megabytes without
        # compression. Browsers request gzip automatically; urllib does not.
        "Accept-Encoding": "gzip",
    }
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, headers=h)
    started = time.monotonic()
    chunks = []
    with urllib.request.urlopen(req, context=ctx, timeout=timeout) as r:
        while True:
            if cancel_check and cancel_check():
                raise RequestCancelled("用户已取消当前网络任务")
            if total_timeout and time.monotonic() - started > total_timeout:
                raise TimeoutError(f"请求总耗时超过 {total_timeout} 秒")
            chunk = r.read(256 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        raw = b"".join(chunks)
        if str(r.headers.get("Content-Encoding") or "").casefold() == "gzip":
            raw = gzip.decompress(raw)
        return json.loads(raw)


def _safe(name: str) -> str:
    return re.sub(r"[^\w.\-]+", "_", name or "")[:60]


def _dest(game_slug: str, filename: str) -> str:
    d = os.path.join(downloader.DOWNLOADS_DIR, game_slug or "_misc")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, filename)


_SRC_CACHE = {}                  # slug/name(lower) -> (ts, result)
_SRC_TTL = 3600


def available_sources(game_name: str, game_slug: str, game_root: str,
                      tavily_key: str = "", nexus_api_key: str = "") -> dict:
    """当前游戏在哪些平台有 mod 可搜。CURRENT STATE 注入 + mod_recommend 选源共用。
    本地判断(nexus=slug 非 local_、工坊=acf 解析)零成本;联网探测(thunderstore 社区、
    gamebanana 收录)并发跑、单项限时 4 秒,失败按不可用处理——绝不阻塞对话首条消息。
    结果按游戏缓存 1 小时。github 是通用代码托管,恒可用。"""
    import time
    key = (
        (game_slug or game_name or "").lower(),
        bool(tavily_key),
        bool(nexus_api_key),
    )
    hit = _SRC_CACHE.get(key)
    if hit and time.time() - hit[0] < _SRC_TTL:
        return hit[1]

    static_nexus = bool(game_slug) and not str(game_slug).startswith("local_")
    out = {
        "nexus": game_slug if static_nexus else None,
        "workshop": None,        # appid | None
        "thunderstore": None,    # community slug | None
        "gamebanana": None,      # game id | None
        "github": True,
        "source_status": {
            "nexus": {
                "status": "available" if static_nexus else "not_detected",
                "evidence": "static game mapping" if static_nexus else "",
                "slug": game_slug if static_nexus else "",
            },
            "workshop": {"status": "not_detected", "evidence": ""},
            "thunderstore": {"status": "not_detected", "evidence": ""},
            "gamebanana": {"status": "not_detected", "evidence": ""},
            "github": {"status": "available", "evidence": "generic repository search"},
        },
    }
    if not static_nexus:
        try:
            from .. import nexus
            discovered = nexus.discover_game(
                game_name, tavily_key, nexus_api_key
            )
            out["source_status"]["nexus"] = discovered
            if discovered.get("status") == "available":
                out["nexus"] = discovered.get("slug") or None
        except Exception as exc:
            out["source_status"]["nexus"] = {
                "status": "search_failed",
                "evidence": "",
                "slug": "",
                "reason": (str(exc) or type(exc).__name__)[:160],
            }
    try:
        from . import steam_workshop as sw
        out["workshop"] = sw.resolve_appid(game_root) or None
        if out["workshop"]:
            out["source_status"]["workshop"] = {
                "status": "candidate",
                "evidence": f"Steam appid {out['workshop']}",
                "reason": "Steam app identity found; Workshop availability is not confirmed",
            }
    except Exception:
        pass

    import concurrent.futures as cf
    def _ts():
        from . import thunderstore
        return thunderstore.find_community(game_name)
    def _gb():
        from . import gamebanana
        return gamebanana.find_game(game_name)
    ex = cf.ThreadPoolExecutor(max_workers=2)
    futs = {"thunderstore": ex.submit(_ts), "gamebanana": ex.submit(_gb)}
    done, not_done = cf.wait(list(futs.values()), timeout=5)
    for k, f in futs.items():
        try:
            if f in not_done:
                raise TimeoutError("source probe exceeded 5 seconds")
            out[k] = f.result() or None
            if out[k]:
                out["source_status"][k] = {
                    "status": "available",
                    "evidence": str(out[k]),
                }
        except Exception:
            out[k] = None
            out["source_status"][k] = {
                "status": "search_failed",
                "evidence": "",
            }
    ex.shutdown(wait=False)      # 超时的探测线程后台自生自灭,不拖住对话

    _SRC_CACHE[key] = (time.time(), out)
    return out


def detect_source(url: str) -> str:
    u = (url or "").lower()
    if "github.com" in u:
        return "github"
    if "thunderstore.io" in u:
        return "thunderstore"
    if "gamebanana.com" in u:
        return "gamebanana"
    if "nexusmods.com" in u:
        return "nexus"
    return ""


def download_from_url(url: str, game_slug: str, progress_callback=None) -> dict:
    """根据链接自动识别来源并下载，返回 {local_path, name, source, version}。"""
    src = detect_source(url)
    if src == "github":
        from . import github
        return github.download(url, game_slug, progress_callback)
    if src == "thunderstore":
        from . import thunderstore
        return thunderstore.download(url, game_slug, progress_callback)
    if src == "gamebanana":
        from . import gamebanana
        return gamebanana.download(url, game_slug, progress_callback)
    if src == "nexus":
        raise RuntimeError("Nexus 链接请用 nexus_search / mod_download（需要 mod_id 与已登录 Chrome）")
    raise RuntimeError("无法识别的来源链接（支持 GitHub / Thunderstore / GameBanana）")
