import asyncio
import json
import os
import sys
import time
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse, FileResponse
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, Field

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modagent.config import Config, load as load_config, save as save_config, CONFIG_DIR, edition_data_dir
from modagent import db, games, installer, __version__
from modagent import snapshot                      # ← 补:get_snapshot_detail / delete_snapshot 用到 snapshot.SNAPSHOTS_DIR
from modagent.tools import execute, build_tools_definitions
from modagent.agent import Agent
from modagent.startup_checks import run_startup_checks
from modagent.prompts import build_prompt
from modagent import debug_trace

cfg: Config = None
agents: dict[str, Agent] = {}
_agent_last_used: dict[str, float] = {}            # ← 补回:被 _get_agent 使用
_AGENT_TTL = 3600                                  # ← 补回:agent 空闲回收时间(秒)

PROMPT_REFERENCED_TOOLS = {
    # 与 I 盘真身 tools.py 的 build_tools_definitions 保持一致(32 个)
    "nexus_search", "nexus_get_detail", "mod_recommend", "mod_download", "batch_download",
    "mod_install", "mod_install_batch", "mod_install_custom", "mod_uninstall", "mod_update_check", "mod_update",
    "mod_disable", "mod_enable", "mod_dependency_set",
    "snapshot_create", "snapshot_restore", "snapshot_list", "snapshot_delete", "conflict_check",
    "list_local_mods", "tool_extract",
    "get_installed", "read_readme", "game_diagnose", "mod_patch",
    "scan_games", "scan_existing_mods", "import_existing_mods",
    "collection_view", "download_from_url", "thunderstore_search",
    "workshop_search", "workshop_install", "workshop_uninstall",
    "github_search", "gamebanana_search",
    # 注:mod_files / mod_readfile / mod_writefile 在 I 盘真身中未实现,故不列入。
    # 若日后把 C 盘的微调工作台(workshop.py + 三个工具)合并进来,再补这三个。
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    global cfg
    db.init_db()
    cfg = load_config()
    run_startup_checks(build_prompt(cfg), build_tools_definitions(cfg.tier),
                       referenced_tools=PROMPT_REFERENCED_TOOLS)
    yield
    # 关闭阶段(此处无需清理);切勿再加第二个 yield —— lifespan 只能有一个


app = FastAPI(title="ModAgent API", version=__version__, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000", "null"],
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "X-ModAgent-Token"],
    allow_credentials=False,
)

_API_TOKEN = os.environ.get("MODAGENT_API_TOKEN", "")


@app.middleware("http")
async def require_local_token(request: Request, call_next):
    if request.url.path == "/health" or request.method == "OPTIONS":
        return await call_next(request)
    if not _API_TOKEN:
        if request.headers.get("origin"):
            return JSONResponse({"detail": "ModAgent API token required"}, status_code=401)
    elif request.headers.get("X-ModAgent-Token") != _API_TOKEN:
        return JSONResponse({"detail": "Invalid ModAgent API token"}, status_code=401)
    return await call_next(request)


# ── Debug endpoints (developer mode) ──
# 必须注册在下面的 @app.options("/{rest_of_path:path}") 通配路由之前,
# 否则通配 path 会截胡 /debug/* 的请求,导致全部 405 Method Not Allowed。

def _require_dev():
    if not getattr(cfg, "dev_mode", False):
        raise HTTPException(403, "开发者模式未开启")


@app.get("/debug/status")
def debug_status():
    return {"dev_mode": bool(getattr(cfg, "dev_mode", False))}


@app.get("/debug/last_turn")
def debug_last_turn():
    _require_dev()
    return debug_trace.get_last_turn() or {}


@app.get("/debug/turns")
def debug_turns(limit: int = 20):
    _require_dev()
    return debug_trace.list_turns(limit)


@app.get("/debug/turn/{turn_id}")
def debug_turn(turn_id: str):
    _require_dev()
    t = debug_trace.get_turn(turn_id)
    if not t:
        raise HTTPException(404, "turn not found")
    return t


class DebugExec(BaseModel):
    name: str
    args: dict = {}


@app.post("/debug/exec")
def debug_exec(body: DebugExec):
    """工具沙箱:用任意参数直接跑一个工具。⚠️ 会真实执行(可能写文件/下载)。"""
    _require_dev()
    debug_trace.start_manual_turn(f"exec:{body.name}")
    t0 = time.time()
    try:
        result = execute(body.name, body.args, cfg)
        ok = not (isinstance(result, str) and result.strip().startswith(("{\"error\"", "错误", "[ERR]")))
    except Exception as e:
        result = json.dumps({"error": str(e)}, ensure_ascii=False)
        ok = False
    ms = (time.time() - t0) * 1000.0
    debug_trace.record_tool(body.name, body.args, result, ms, ok)
    debug_trace.finish_turn(history=None, final_text=None)
    return {"name": body.name, "args": body.args, "ok": ok,
            "ms": round(ms, 1), "result": result}


class DebugReplay(BaseModel):
    turn_id: str
    message: Optional[str] = None


@app.post("/debug/replay")
def debug_replay(body: DebugReplay):
    """重放某一轮:用该轮 pre_history 作为起点重发(可改)用户消息。⚠️ 会真实执行工具。"""
    _require_dev()
    src = debug_trace.get_turn(body.turn_id)
    if not src:
        raise HTTPException(404, "turn not found")
    msg = body.message if body.message is not None else src["user_msg"]

    scratch = Agent(cfg)
    scratch.session_id = f"__replay__{body.turn_id}"
    scratch.history = list(src.get("pre_history") or [])
    reply = scratch.chat(msg)
    return {"replayed_from": body.turn_id, "message": msg,
            "reply": reply, "new_turn": debug_trace.get_last_turn()}


@app.options("/{rest_of_path:path}")
async def preflight_handler():
    return {"ok": True}


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(status_code=422, content={"error": str(exc)})


@app.exception_handler(500)
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    return JSONResponse(status_code=500, content={"error": str(exc)})


class ChatRequest(BaseModel):
    message: str
    session_id: str = ""


class SessionCreate(BaseModel):
    title: str = ""
    game_slug: str = ""


class SessionUpdate(BaseModel):
    title: str = ""


class SessionMessagesUpdate(BaseModel):
    messages: list[dict] = Field(default_factory=list)


class ConfigUpdate(BaseModel):
    api_key: Optional[str] = None
    nexus_api_key: Optional[str] = None
    game_name: Optional[str] = None
    game_slug: Optional[str] = None
    game_id: Optional[int] = None
    game_root: Optional[str] = None
    chrome_cdp_port: Optional[int] = None
    llm_endpoint: Optional[str] = None
    llm_model: Optional[str] = None
    llm_api_key: Optional[str] = None
    tier: Optional[str] = None
    mod_loader: Optional[str] = None
    tavily_api_key: Optional[str] = None
    dev_mode: Optional[bool] = None


def _get_agent(session_id: str) -> Agent:
    now = time.time()
    stale = [sid for sid, ts in _agent_last_used.items() if now - ts > _AGENT_TTL]
    for sid in stale:
        agents.pop(sid, None)
        _agent_last_used.pop(sid, None)
    if session_id not in agents:
        agents[session_id] = Agent(cfg)
    _agent_last_used[session_id] = now
    agents[session_id].session_id = session_id      # trace 归属用
    return agents[session_id]


@app.get("/status")
def get_status():
    bg_dir = edition_data_dir("bg")
    os.makedirs(bg_dir, exist_ok=True)
    bg_files = [f for f in os.listdir(bg_dir) if os.path.isfile(os.path.join(bg_dir, f))]
    bg = bg_files[0] if bg_files else None
    return {
        "game_name": cfg.game_name,
        "game_slug": cfg.game_slug,
        "game_root": cfg.game_root or "",
        "tier": cfg.tier,
        "api_key_set": bool(cfg.nexus_api_key),
        "llm_set": bool(cfg.llm_api_key),
        "llm_model": cfg.llm_model,
        "llm_endpoint": cfg.llm_endpoint,
        "cdp_port": cfg.chrome_cdp_port,
        "bg": bg,
        "tavily_set": bool(cfg.tavily_api_key),
        "dev_mode": bool(getattr(cfg, "dev_mode", False)),
    }


@app.get("/games/detect")
def detect_games():
    return games.detect_steam_games()


@app.get("/games/resolve")
def resolve_game(name: str = ""):
    if not name:
        return {"slug": "", "game_id": 0}
    from .games import _auto_infer
    result = _auto_infer(name)
    if result:
        slug, gid = result
        cfg.game_slug = slug
        cfg.game_id = gid
        save_config(cfg)
        return {"slug": slug, "game_id": gid}
    return {"slug": "", "game_id": 0}


@app.get("/games/health")
def games_health():
    """游戏体检:重新检测 Steam 游戏 + 校验当前配置的游戏根目录是否活体。"""
    return games.health_check_games(
        configured_root=getattr(cfg, "game_root", "") or "",
        configured_slug=getattr(cfg, "game_slug", "") or "")


class GameImport(BaseModel):
    game_root: str
    game_name: str = ""
    game_slug: str = ""
    game_id: int = 0


@app.post("/games/import")
def import_game(body: GameImport):
    """手动导入游戏路径,带活体验证。前端"手动选择游戏目录"用。
    验证不通过时返回 warning 但仍允许用户强制保存(force),避免挡住特殊安装。"""
    alive = games.verify_game_alive(body.game_root)
    resp = {"alive": alive["alive"], "reason": alive["reason"],
            "shipping_exe": alive.get("shipping_exe")}
    # 无论是否活体都写入配置(用户可能明知特殊结构),但把告警回传给前端展示
    cfg.game_root = body.game_root
    if body.game_name:
        cfg.game_name = body.game_name
    if body.game_slug:
        cfg.game_slug = body.game_slug
    if body.game_id:
        cfg.game_id = body.game_id
    save_config(cfg)
    resp["saved"] = True
    if not alive["alive"]:
        resp["warning"] = "该目录未通过活体检测(未找到游戏本体 exe),已保存但安装 mod 可能不生效。"
    return resp


@app.post("/config")
def update_config(body: ConfigUpdate):
    data = body.model_dump(exclude_none=True)
    if "api_key" in data:
        cfg.nexus_api_key = data.pop("api_key")
    for key, value in data.items():
        setattr(cfg, key, value)
    save_config(cfg)
    return {"ok": True}


@app.get("/mods")
def list_mods(game_slug: str = ""):
    mods = db.get_installed_mods(game_slug if game_slug else cfg.game_slug)

    return [{
        "id": m.id, "name": m.name, "version": m.version,
        "load_order": m.load_order, "snapshot_id": m.snapshot_id,
        "installed_at": m.installed_at, "installed_by": m.installed_by,
        "game_slug": m.game_slug,
        "disabled": installer.is_mod_disabled(_mod_files(m)),
    } for m in mods]


def _mod_files(mod) -> list:
    try:
        value = json.loads(mod.files_installed) if isinstance(mod.files_installed, str) else (mod.files_installed or [])
        return value if isinstance(value, list) else []
    except (TypeError, ValueError, json.JSONDecodeError):
        return []


def _is_mod_in_game(m, game_root: str) -> bool:
    try:
        files = json.loads(m.files_installed) if isinstance(m.files_installed, str) else (m.files_installed or [])
        if files and game_root:
            return any(f.startswith(game_root) for f in files)
    except Exception:
        pass
    return True


@app.get("/snapshots")
def list_snapshots(game_slug: str = ""):
    snaps = db.list_snapshots(game_slug) if game_slug else db.list_snapshots()

    def _count(s):
        try:
            data = json.loads(s.files)
            if isinstance(data, list):
                return len(data)
            if isinstance(data, dict):
                return int(data.get("count", 0))
        except Exception:
            pass
        return 0

    def _valid(s):
        # 账本 ≠ 事实:v0.8 的病是目录删了照列不误、回滚按钮照点不误。
        # 列表直接带失效标记,前端标灰 + 禁用回滚。
        d = os.path.join(snapshot.SNAPSHOTS_DIR, s.game_slug or "", s.id)
        if not os.path.isdir(d):
            d = os.path.join(snapshot.SNAPSHOTS_DIR, s.id)
        return os.path.exists(os.path.join(d, "manifest.json"))

    return [{"id": s.id, "timestamp": s.timestamp, "trigger_mod_name": s.trigger_mod_name,
             "files_count": _count(s), "game_slug": s.game_slug,
             "baseline": _count(s) == 0, "valid": _valid(s)} for s in snaps]


@app.get("/snapshots/{sid}")
def get_snapshot_detail(sid: str):
    snap = db.get_snapshot(sid)
    if not snap:
        raise HTTPException(404, "Snapshot not found")
    snap_dir = os.path.join(snapshot.SNAPSHOTS_DIR, snap.game_slug or "", sid)
    if not os.path.isdir(snap_dir):
        snap_dir = os.path.join(snapshot.SNAPSHOTS_DIR, sid)
    manifest_path = os.path.join(snap_dir, "manifest.json")
    files = []
    if os.path.exists(manifest_path):
        with open(manifest_path, "r", encoding="utf-8") as f:
            m = json.load(f)
            files = m.get("files", [])[:50]
    return {
        "id": snap.id, "timestamp": snap.timestamp, "trigger_mod_name": snap.trigger_mod_name,
        "game_slug": snap.game_slug, "files_count": len(files), "files": files,
    }


@app.get("/snapshots/{sid}/preview")
def preview_snapshot_restore(sid: str):
    """回滚预览(干跑,不落盘):将删除/将还原清单,供前端回滚确认弹窗使用。"""
    try:
        return snapshot.snapshot_restore_preview(sid)
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))


@app.delete("/snapshots/{sid}")
def delete_snapshot(sid: str):
    try:
        snapshot.snapshot_delete(sid)
    except FileNotFoundError:
        raise HTTPException(404, "Snapshot not found")
    return {"ok": True}


@app.post("/snapshots/reconcile")
def snapshots_reconcile(game_slug: str = "", clean: bool = False):
    """快照对账:DB 记录 ↔ 磁盘 manifest。clean=true 时顺手删掉失效记录。"""
    slug = game_slug or cfg.game_slug
    snaps = db.list_snapshots(slug) if slug else db.list_snapshots()
    invalid = []
    for s in snaps:
        d = os.path.join(snapshot.SNAPSHOTS_DIR, s.game_slug or "", s.id)
        if not os.path.isdir(d):
            d = os.path.join(snapshot.SNAPSHOTS_DIR, s.id)
        if not os.path.exists(os.path.join(d, "manifest.json")):
            invalid.append(s.id)
            if clean:
                db.delete_snapshot(s.id)
    return {"checked": len(snaps), "invalid": invalid, "cleaned": clean}


@app.post("/mods/reconcile")
def mods_reconcile(game_slug: str = ""):
    """已装 mod 对账:files_installed 里的文件是否还在磁盘上。"""
    slug = game_slug or cfg.game_slug
    mods = db.get_installed_mods(slug) if slug else db.get_installed_mods()
    issues = []
    for m in mods:
        try:
            files = json.loads(m.files_installed or "[]")
        except Exception:
            files = []
        # A disabled copy is still present and managed; do not report it as a
        # missing file during ledger reconciliation.
        missing = [f for f in files if not os.path.exists(f) and not os.path.exists(f + ".disabled")]
        if not files or missing:
            issues.append({"mod_id": m.id, "name": m.name,
                           "total": len(files), "missing": len(missing),
                           "missing_sample": missing[:5],
                           "problem": "记录里没有任何文件(空账)" if not files else "部分文件已不在磁盘"})
    return {"checked": len(mods), "issues": issues}


@app.get("/log")
def get_log(limit: int = 30):
    return db.get_operation_log(limit)


@app.post("/chat")
def chat(req: ChatRequest):
    try:
        session_id = req.session_id
        if not session_id:
            session_id = f"session_{int(time.time())}"
            db.create_session(session_id, req.message[:20], cfg.game_slug)

        existing = db.get_session(session_id)
        ag = _get_agent(session_id)

        if existing:
            history = json.loads(existing.get("messages", "[]")) if isinstance(existing.get("messages"), str) else (existing.get("messages") or [])
            ag.history = history
        else:
            db.create_session(session_id, req.message[:20], cfg.game_slug)
            ag.history = []
            existing = db.get_session(session_id)

        reply = ag.chat(req.message)

        if existing and not (existing.get("title") or "").strip():
            db.update_session_title(session_id, req.message[:20])

        db.update_session_messages(session_id, ag.history)

        return {"reply": reply, "session_id": session_id}

    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.post("/chat/stream")
def chat_stream(req: ChatRequest):
    session_id = req.session_id
    if not session_id:
        session_id = f"session_{int(time.time())}"
        db.create_session(session_id, req.message[:20], cfg.game_slug)

    existing = db.get_session(session_id)
    ag = _get_agent(session_id)

    if existing:
        history = json.loads(existing.get("messages", "[]")) if isinstance(existing.get("messages"), str) else (existing.get("messages") or [])
        ag.history = history
    else:
        db.create_session(session_id, req.message[:20], cfg.game_slug)
        ag.history = []

    def generate():
        try:
            for chunk in ag.chat_stream(req.message):
                yield f"data: {chunk}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
        finally:
            if existing and not (existing.get("title") or "").strip():
                db.update_session_title(session_id, req.message[:20])
            db.update_session_messages(session_id, ag.history)

    return StreamingResponse(generate(), media_type="text/event-stream")


@app.post("/chat/reset")
def reset_chat(session_id: str = ""):
    if session_id and session_id in agents:
        agents[session_id].reset()
    return {"ok": True}


# ── Sessions ──

@app.get("/sessions")
def list_sessions(game_slug: str = ""):
    return db.list_sessions(game_slug)


@app.post("/sessions")
def create_session(req: SessionCreate):
    sid = f"session_{int(time.time())}"
    db.create_session(sid, req.title, req.game_slug or cfg.game_slug)
    return {"id": sid, "title": req.title}


@app.get("/sessions/{sid}")
def get_session(sid: str):
    s = db.get_session(sid)
    if not s:
        raise HTTPException(404, "Session not found")
    msgs = json.loads(s["messages"]) if isinstance(s["messages"], str) else (s["messages"] or [])
    # 显示过滤:结构化 history 里含 tool / assistant(tool_calls) 消息,
    # 这些只供模型上下文,不给前端渲染(否则会出现空气泡)。只保留 user + agent 文本。
    display = []
    for m in msgs:
        if m.get("role") == "user":
            display.append({"role": "user", "content": m.get("content", "")})
        elif m.get("role") == "assistant" and (m.get("content") or "").strip() and not m.get("tool_calls"):
            display.append({"role": "assistant", "content": m["content"]})
    return {"id": s["id"], "title": s["title"], "game_slug": s["game_slug"],
            "created_at": s["created_at"], "updated_at": s["updated_at"], "messages": display}


@app.put("/sessions/{sid}")
def update_session(sid: str, req: SessionUpdate):
    db.update_session_title(sid, req.title)
    return {"ok": True}


@app.put("/sessions/{sid}/messages")
def update_session_message_history(sid: str, req: SessionMessagesUpdate):
    if not db.get_session(sid):
        raise HTTPException(404, "Session not found")
    if len(req.messages) > 200:
        raise HTTPException(400, "Too many messages")
    clean = []
    for message in req.messages:
        role = message.get("role")
        content = message.get("content")
        if role not in {"user", "assistant"} or not isinstance(content, str):
            raise HTTPException(400, "History only accepts user/assistant text messages")
        clean.append({"role": role, "content": content})
    db.update_session_messages(sid, clean)
    if sid in agents:
        agents[sid].history = list(clean)
        _agent_last_used[sid] = time.time()
    return {"ok": True, "messages_count": len(clean)}


@app.delete("/sessions/{sid}")
def delete_session(sid: str):
    db.delete_session(sid)
    return {"ok": True}


@app.post("/tool/{name}")
def call_tool(name: str, body: dict = None):
    if body is None:
        body = {}
    return {"tool": name, "result": execute(name, body, cfg)}


@app.post("/dropbox/open")
def open_dropbox():
    """在系统文件管理器里打开当前游戏的投放文件夹,供用户把手动下载的 mod 拖进去。"""
    import subprocess
    from . import downloader
    path = downloader.ensure_dropbox_dir(cfg.game_slug or "")
    try:
        if sys.platform == "win32":
            os.startfile(path)                                  # noqa: 只在 Windows 存在
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
        return {"ok": True, "path": path}
    except Exception as e:
        return {"ok": False, "path": path, "error": str(e)}


def _open_folder(path: str):
    import subprocess
    os.makedirs(path, exist_ok=True)
    try:
        if sys.platform == "win32":
            os.startfile(path)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
        return {"ok": True, "path": path}
    except Exception as e:
        return {"ok": False, "path": path, "error": str(e)}


@app.post("/downloads/open")
def open_downloads():
    """Open the current game's managed Mod download cache."""
    from . import downloader
    return _open_folder(downloader.ensure_downloads_dir(cfg.game_slug or "_unknown"))


@app.post("/tools/open")
def open_tools():
    """Open ModAgent's managed standalone-tools directory."""
    from . import downloader
    return _open_folder(downloader.ensure_tools_dir())


@app.get("/health")
def health():
    return {"ok": True, "timestamp": time.time()}


@app.get("/downloads/status")
def downloads_status():
    """Expose the in-process download queue to the authenticated renderer."""
    from . import progress
    return progress.snapshot()


@app.get("/static/bg/{filename}")
def serve_bg(filename: str):
    bg_dir = edition_data_dir("bg")
    os.makedirs(bg_dir, exist_ok=True)
    safe_name = os.path.basename(filename)
    if not safe_name or safe_name != filename:
        raise HTTPException(400, "Invalid filename")
    fp = os.path.join(bg_dir, safe_name)
    if not os.path.isfile(fp):
        raise HTTPException(404)
    # no-cache:壁纸更换靠唯一文件名天然防缓存,这里是双保险
    # (旧版固定文件名 + 缓存曾导致"换图后永远显示旧图")
    return FileResponse(fp, headers={"Cache-Control": "no-cache"})


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=18890)
