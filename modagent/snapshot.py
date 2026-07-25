import json
import os
import re
import shutil
import time
import filecmp

from .config import CONFIG_DIR

SNAPSHOTS_DIR = os.path.join(CONFIG_DIR, "snapshots")


def migrate_game_scope(legacy_slug: str, instance_id: str) -> None:
    """Move legacy snapshot folders under the selected install identity."""
    if not legacy_slug or not instance_id or legacy_slug == instance_id:
        return
    source = os.path.join(SNAPSHOTS_DIR, legacy_slug)
    target = os.path.join(SNAPSHOTS_DIR, instance_id)
    if not os.path.isdir(source):
        return
    os.makedirs(target, exist_ok=True)
    for name in os.listdir(source):
        old = os.path.join(source, name)
        new = os.path.join(target, name)
        if not os.path.exists(new):
            shutil.move(old, new)
    try:
        os.rmdir(source)
    except OSError:
        pass

# 每游戏快照保留上限,超出自动淘汰最老的(最早的原版基线除外)。
# 硬链接方案下删旧快照是安全的:文件 inode 引用计数还在,新快照不受影响。
MAX_SNAPSHOTS = 20

# ─────────────────────────────────────────────────────────────
# 快照域(snapshot domain)= ModAgent 有能力写入的文件集合
#
# 设计原则:快照范围必须与 installer 的写入范围严格一致。
#   · 范围过大 → 复制整个游戏二进制目录,慢到超时(v0.8 的病)
#   · 范围过小 → restore 时把"不在快照里"的原版文件当成新增物删除(灾难)
# 因此 create 与 restore 共用同一个 _iter_domain_files(),永不错位。
#
# spec: {"dir": 相对目录, "include": 正则(相对该目录的路径) 或 None=全部}
# ─────────────────────────────────────────────────────────────

# UE 注入器散件 + ue4ss 目录 = Win64 下唯一属于 mod 域的东西;
# 游戏本体 exe / 官方 dll 一律不进快照、也永不被 restore 删除。
_UE_INJECTOR_RE = re.compile(
    r"^(?:"
    r"ue4ss/.*"                                              # ue4ss 整个目录(含 Mods/、日志、settings)
    r"|(?:dwmapi|xinput1_3|dsound|version|d3d11|winmm)\.dll" # 注入器 dll
    r"|UE4SS-settings\.ini"
    r"|dwmapi\.ini"
    r")$",
    re.IGNORECASE,
)

GAME_SNAPSHOT_SPECS: dict[str, list[dict]] = {
    # FFVII Rebirth:仅管理插件目录、~mods 与已知注入器。绝不能把整个
    # End/Binaries/Win64、Engine/Plugins 当作 mod 域，否则 Steam 更新后回滚
    # 旧快照会把新版游戏原生 DLL 覆盖回旧版。
    "finalfantasy7rebirth": [
        {"dir": "End/Mods", "include": None},
        {"dir": "End/Content/Paks/~mods", "include": None},
        {"dir": "End/Binaries/Win64", "include": _UE_INJECTOR_RE},
    ],
    "stellarblade": [
        {"dir": "SB/Content/Paks/~mods", "include": None},
        {"dir": "SB/Content/Paks/LogicMods", "include": None},   # CNS 本体 pak 住这儿,v0.8 漏了
        {"dir": "SB/Binaries/Win64", "include": _UE_INJECTOR_RE},
    ],
    "cyberpunk2077": [
        {"dir": "archive/pc/mod", "include": None},
        {"dir": "bin/x64/plugins", "include": None},
        {"dir": "r6/scripts", "include": None},
        {"dir": "r6/tweaks", "include": None},
    ],
    "skyrimspecialedition": [
        {"dir": "Data", "include": None},
        {"dir": "SKSE", "include": None},
    ],
    "fallout4": [
        {"dir": "Data", "include": None},
    ],
    # Palworld:UE5,同剑星结构(项目目录 Pal/)
    "palworld": [
        {"dir": "Pal/Content/Paks/~mods", "include": None},
        {"dir": "Pal/Content/Paks/LogicMods", "include": None},   # UE4SS 蓝图 mod
        {"dir": "Pal/Binaries/Win64", "include": _UE_INJECTOR_RE},
    ],
    # R.E.P.O. / 恐鬼症:Unity + BepInEx。mod = plugins/config 下的文件;
    # 加载器本体(winhttp.dll / BepInEx/core)属一次性引导,不纳入快照回滚域。
    "repo": [
        {"dir": "BepInEx/plugins", "include": None},
        {"dir": "BepInEx/config", "include": None},
    ],
    # 恐鬼症:Unity IL2CPP,主流加载器是 MelonLoader(mod = Mods/*.dll + UserData/);
    # 域与 installer 的 phasmophobia layout 写入范围一致(加载器本体 MelonLoader/ 与根 dll
    # 属一次性引导,同 BepInEx core 一样不进回滚域)。少数 BepInEx mod 目录一并纳入,
    # 不存在的目录会被 _auto_detect_specs 过滤掉。
    "phasmophobia": [
        {"dir": "Mods", "include": None},              # MelonLoader mod dll
        {"dir": "UserData", "include": None},          # MelonLoader mod 配置/资源
        {"dir": "UserLibs", "include": None},          # mod 依赖库
        {"dir": "Plugins", "include": None},           # MelonLoader 插件(非 BepInEx plugins)
        {"dir": "BepInEx/plugins", "include": None},
        {"dir": "BepInEx/config", "include": None},
    ],
}

_PROFILE_ALIASES = {
    "local_final_fantasy_vii_rebirth": "finalfantasy7rebirth",
    "final_fantasy_vii_rebirth": "finalfantasy7rebirth",
}


def _snapshot_profile(game_slug: str, game_root: str = "") -> str:
    """把手动导入的 local_* slug 映射到已知安全快照域。"""
    slug = str(game_slug or "").strip().lower()
    if slug in GAME_SNAPSHOT_SPECS:
        return slug
    if slug in _PROFILE_ALIASES:
        return _PROFILE_ALIASES[slug]
    compact = re.sub(r"[^a-z0-9]+", "", slug)
    root_compact = re.sub(r"[^a-z0-9]+", "", str(game_root or "").lower())
    if "finalfantasyviirebirth" in compact or "finalfantasyviirebirth" in root_compact:
        return "finalfantasy7rebirth"
    return ""


def is_known_snapshot_profile(game_slug: str, game_root: str = "") -> bool:
    return bool(_snapshot_profile(game_slug, game_root))

# 未知游戏:自动发现时命中这些目录名则纳入(整目录)
_WATCH_DIR_NAMES = ("~mods", "mods", "mod", "plugins", "scripts",
                    "r6", "tweaks", "archive", "data", "skse", "win64")


def _custom_domain_files(game_slug: str) -> list:
    """该游戏 T2 登记的自定义落点(精确相对路径)。DB 不可用时返回 [] ——
    域退化为不含 custom(即现有行为),绝不因 DB 故障阻塞快照。"""
    if not game_slug:
        return []
    try:
        from .db import get_custom_domain_files
        return get_custom_domain_files(game_slug)
    except Exception:
        return []


def _auto_detect_specs(game_root: str, game_slug: str) -> list[dict]:
    """返回该游戏的快照域 spec 列表。已知游戏用硬编码表,未知游戏才走目录名嗅探;
    末尾并入该游戏 T2 登记的自定义落点(精确文件型 spec,不受嗌探目录名/6 目录上限约束)。
    custom_domains 表默认空 → 无登记时并入空集,现有游戏行为逐字不变。"""
    known = GAME_SNAPSHOT_SPECS.get(_snapshot_profile(game_slug, game_root))
    if known:
        base = [s for s in known if os.path.isdir(os.path.join(game_root, s["dir"]))]
    elif not os.path.isdir(game_root):
        base = []
    else:
        discovered: list[dict] = []
        for root, dirs, _ in os.walk(game_root):
            depth = root.replace(game_root, "").count(os.sep)
            if depth > 5:
                dirs[:] = []
                continue
            for d in dirs:
                if d.lower() in _WATCH_DIR_NAMES:
                    rel = os.path.relpath(os.path.join(root, d), game_root).replace("\\", "/")
                    if not any(s["dir"] == rel for s in discovered):
                        discovered.append({"dir": rel, "include": None})
        base = discovered[:6]

    custom = _custom_domain_files(game_slug)
    if custom:
        base = base + [{"files": custom}]
    return base


def _norm(p: str) -> str:
    return p.replace("\\", "/")


def _iter_domain_files(game_root: str, specs: list[dict]):
    """产出快照域内所有文件的相对路径(相对 game_root,正斜杠)。create/restore 共用。

    两种 spec 形态:
      · {"dir": 相对目录, "include": 正则|None} —— 目录型,walk 整目录(含过滤)
      · {"files": [相对 game_root 的精确路径]}   —— 文件型(T2 自定义落点),只产出登记过、
        且当前仍存在的精确文件,绝不 walk 目录,免得把同目录的游戏原文件误纳入域。
    """
    for spec in specs:
        if "files" in spec:
            for rel in spec["files"]:
                if os.path.isfile(os.path.join(game_root, rel.replace("/", os.sep))):
                    yield _norm(rel)
            continue
        base = os.path.join(game_root, spec["dir"].replace("/", os.sep))
        if not os.path.isdir(base):
            continue
        inc = spec.get("include")
        for root, _, files in os.walk(base):
            for f in files:
                full = os.path.join(root, f)
                rel_in_dir = _norm(os.path.relpath(full, base))
                if inc is not None and not inc.match(rel_in_dir):
                    continue
                yield _norm(os.path.relpath(full, game_root))


def _prev_snap_dir(game_snap_root: str, exclude: str = "") -> str:
    """最近一次快照目录,用于硬链接去重(同盘,零拷贝)。"""
    if not os.path.isdir(game_snap_root):
        return ""
    cands = sorted(
        (d for d in os.listdir(game_snap_root)
         if d.startswith("snap_") and d != exclude
         and os.path.exists(os.path.join(game_snap_root, d, "manifest.json"))),
        reverse=True,
    )
    return os.path.join(game_snap_root, cands[0]) if cands else ""


def _workshop_state(game_root: str):
    """记录创意工坊订阅集(= steamapps/workshop/content/<appid>/ 的条目)。
    工坊内容在 steamapps 而非游戏目录,文件快照天然覆盖不到 ——
    所以以"订阅清单"的形式纳入快照语义,restore 时做差集同步(退订多的、重订缺的)。"""
    try:
        from .sources.steam_workshop import resolve_appid, workshop_content_dir
        appid = resolve_appid(game_root)
        if not appid:
            return None
        d = workshop_content_dir(game_root, appid)
        ids = sorted(e for e in os.listdir(d) if e.isdigit()) if os.path.isdir(d) else []
        return {"appid": appid, "ids": ids}
    except Exception:
        return None


def _workshop_diff(game_root: str, ws: dict) -> tuple[list, list]:
    """快照订阅清单 vs 当前订阅集的差集 → (该退订的, 该重订的)。预览与执行共用。"""
    from .sources import steam_workshop as sw
    appid = ws["appid"]
    want = set(str(i) for i in ws.get("ids", []))
    d = sw.workshop_content_dir(game_root, appid)
    have = set(e for e in os.listdir(d) if e.isdigit()) if os.path.isdir(d) else set()
    return sorted(have - want), sorted(want - have)


def _reconcile_workshop(game_root: str, ws: dict) -> dict:
    """把工坊订阅集恢复到快照时的状态。CDP/Chrome 不可用时绝不阻塞文件回滚,
    把差集如实放进 manual_* 让用户手动处理。"""
    import asyncio
    from .sources import steam_workshop as sw
    appid = ws["appid"]
    to_unsub, to_resub = _workshop_diff(game_root, ws)
    if not to_unsub and not to_resub:
        return {"appid": appid, "in_sync": True}
    result = {"appid": appid, "in_sync": False, "unsubscribed": [], "resubscribed": [],
              "manual_unsubscribe": [], "manual_subscribe": []}
    for pid in to_unsub:
        try:
            r = asyncio.run(sw.unsubscribe(pid, appid))
            (result["unsubscribed"] if r.get("ok") else result["manual_unsubscribe"]).append(pid)
        except Exception:
            result["manual_unsubscribe"].append(pid)
    for pid in to_resub:
        try:
            r = asyncio.run(sw.subscribe(pid, appid))
            (result["resubscribed"] if r.get("ok") else result["manual_subscribe"]).append(pid)
        except Exception:
            result["manual_subscribe"].append(pid)
    if result["manual_unsubscribe"] or result["manual_subscribe"]:
        result["note"] = ("部分工坊物品无法自动同步(Chrome 未登录 Steam?)。"
                          f"请在 Steam 手动退订: {result['manual_unsubscribe'] or '无'};"
                          f"手动重新订阅: {result['manual_subscribe'] or '无'}")
    return result


def _same_file(a: str, b: str) -> bool:
    try:
        sa, sb = os.stat(a), os.stat(b)
        return sa.st_size == sb.st_size and abs(sa.st_mtime - sb.st_mtime) < 2
    except OSError:
        return False


def _same_content(a: str, b: str) -> bool:
    """回滚判定必须比较真实内容，不能只信可能被保留的 size/mtime。"""
    try:
        return filecmp.cmp(a, b, shallow=False)
    except OSError:
        return False


def _path_in_specs(rel: str, specs: list[dict]) -> bool:
    """判断清单路径是否仍属于当前安全域；用于隔离旧版过宽快照。"""
    rel = _norm(rel).lstrip("./")
    rel_lower = rel.lower()
    for spec in specs:
        if "files" in spec:
            if rel_lower in {_norm(p).lstrip("./").lower() for p in spec["files"]}:
                return True
            continue
        base = _norm(spec["dir"]).strip("/")
        prefix = base + "/"
        if rel_lower == base.lower():
            inner = ""
        elif rel_lower.startswith(prefix.lower()):
            inner = rel[len(prefix):]
        else:
            continue
        inc = spec.get("include")
        if inc is None or inc.match(inner):
            return True
    return False


def snapshot_create(game_root: str, game_slug: str, trigger_mod_id: str = "",
                    trigger_mod_name: str = "") -> str:
    """
    创建快照(v0.9 重写)。

    相比 v0.8 的三处关键变化:
      1. 快照域收窄到 ModAgent 真正会写的文件(Win64 下只取注入器 + ue4ss),
         不再整目录复制游戏二进制,消除 90s 超时的主因。
      2. 增量硬链接:与上一份快照内容相同(size+mtime)的文件直接 os.link,
         零字节拷贝。第二次起的快照接近瞬时。
      3. 拷贝失败即整体失败(不再 except: continue)。
         原因:manifest 缺文件会让 restore 把真实游戏文件当成"新增物"删除。
         宁可不出快照,不可出残缺快照。
    """
    if not os.path.isdir(game_root):
        raise FileNotFoundError(f"游戏目录不存在: {game_root}")

    from .config import load as load_config, game_storage_id
    game_instance_id = game_storage_id(load_config(), game_slug)
    specs = _auto_detect_specs(game_root, game_slug)
    rel_files = sorted(set(_iter_domain_files(game_root, specs)))

    if not rel_files:
        # 域为空有两种可能:① 原版无 mod —— 这是合法且宝贵的"基线快照"
        # (files=[],回滚到它 = 清空所有 mod 回到原版);② game_root 配置错误。
        # 用活体检测区分,防止给错误目录记一份空账(P3.1 的初衷由活体守卫承接)。
        from .games import verify_game_alive
        if not verify_game_alive(game_root).get("alive"):
            raise ValueError(
                "empty_snapshot: 快照域为空且游戏目录未通过活体检测 "
                f"(scanned={[s['dir'] for s in specs] or '[]'})。请确认游戏目录/游戏 profile 是否正确。"
            )

    base = time.strftime("%Y%m%d_%H%M%S")
    snap_id = f"snap_{base}"
    game_snap_root = os.path.join(SNAPSHOTS_DIR, game_instance_id)
    # ID 去重必须同时查目录和 DB:目录按游戏分桶,DB 的 id 却是全局唯一——
    # 只查目录的话,同一秒内给两个不同游戏建快照会目录不撞、DB 撞(IntegrityError)。
    from .db import get_snapshot
    n = 1
    while (os.path.exists(os.path.join(game_snap_root, snap_id))
           or get_snapshot(snap_id) is not None):
        n += 1
        snap_id = f"snap_{base}_{n}"
    snap_dir = os.path.join(game_snap_root, snap_id)
    os.makedirs(snap_dir, exist_ok=True)

    prev_dir = _prev_snap_dir(game_snap_root, exclude=snap_id)
    linked = copied = 0

    try:
        for rel in rel_files:
            src = os.path.join(game_root, rel.replace("/", os.sep))
            dst = os.path.join(snap_dir, rel.replace("/", os.sep))
            os.makedirs(os.path.dirname(dst), exist_ok=True)

            # 增量:上一份快照里有同样的文件(size+mtime 一致)→ 硬链接,不拷字节
            if prev_dir:
                prev = os.path.join(prev_dir, rel.replace("/", os.sep))
                if os.path.exists(prev) and _same_file(src, prev):
                    try:
                        os.link(prev, dst)
                        linked += 1
                        continue
                    except OSError:
                        pass  # 跨卷/文件系统不支持 → 退回拷贝
            shutil.copy2(src, dst)
            copied += 1
        from . import user_config
        external_configs = user_config.capture_snapshot(game_slug, snap_dir)
    except Exception as e:
        shutil.rmtree(snap_dir, ignore_errors=True)
        raise RuntimeError(
            f"快照创建失败,已回滚空目录(不写残缺快照,否则 restore 会误删游戏文件): {e}"
        ) from e

    manifest = {
        "snapshot_id": snap_id,
        "schema": 2,                     # v2: files 为相对路径
        "baseline": not rel_files,       # True = 原版基线(域内无 mod),回滚到它即清空所有 mod
        "workshop": _workshop_state(game_root),  # 工坊订阅集(不在游戏目录,以清单形式入快照)
        "external_configs": external_configs,    # Documents/AppData 等受控用户配置
        "timestamp": time.time(),
        "game_root": game_root,
        "game_slug": game_slug,
        "game_instance_id": game_instance_id,
        "specs": [({"files_count": len(s["files"])} if "files" in s
                   else {"dir": s["dir"], "filtered": s.get("include") is not None})
                  for s in specs],
        "files_count": len(rel_files),
        "files": rel_files,              # 相对 game_root,正斜杠
        "stats": {"linked": linked, "copied": copied},
        "trigger_mod_id": trigger_mod_id,
        "trigger_mod_name": trigger_mod_name,
    }
    with open(os.path.join(snap_dir, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

    from .db import Snapshot, add_snapshot
    add_snapshot(Snapshot(
        id=snap_id, timestamp=time.time(),
        files=json.dumps(rel_files),
        trigger_mod_id=trigger_mod_id, trigger_mod_name=trigger_mod_name,
        game_slug=game_instance_id,
    ))

    _prune_old_snapshots(game_instance_id)   # 保留策略:超上限淘汰最老的(基线除外),失败不阻塞

    return snap_id


def snapshot_delete(snapshot_id: str) -> dict:
    """删除快照:磁盘目录 + DB 记录一起清(账本跟事实走)。不影响已安装的 mod 文件。"""
    from .db import get_snapshot, delete_snapshot as db_delete
    snap = get_snapshot(snapshot_id)
    if snap is None:
        raise FileNotFoundError(f"快照不存在: {snapshot_id}")
    snap_dir = os.path.join(SNAPSHOTS_DIR, snap.game_slug or "", snapshot_id)
    if not os.path.isdir(snap_dir):
        alt = os.path.join(SNAPSHOTS_DIR, snapshot_id)   # 兼容旧版无 slug 分桶的布局
        snap_dir = alt if os.path.isdir(alt) else ""
    if snap_dir:
        shutil.rmtree(snap_dir, ignore_errors=True)
    db_delete(snapshot_id)
    return {"deleted": snapshot_id, "disk_removed": bool(snap_dir)}


def _is_baseline_row(s) -> bool:
    try:
        return not json.loads(s.files or "[]")
    except Exception:
        return False


def _prune_old_snapshots(game_slug: str) -> list[str]:
    """保留策略:超过 MAX_SNAPSHOTS 时淘汰最老的。
    例外:最早的原版基线永久保留——那是"回到原版"的唯一凭据。"""
    from .db import list_snapshots
    snaps = list_snapshots(game_slug)            # DESC(新→旧)
    if len(snaps) <= MAX_SNAPSHOTS:
        return []
    oldest_first = list(reversed(snaps))
    protected = next((s.id for s in oldest_first if _is_baseline_row(s)), None)
    pruned: list[str] = []
    for s in oldest_first:
        if len(snaps) - len(pruned) <= MAX_SNAPSHOTS:
            break
        if s.id == protected:
            continue
        try:
            snapshot_delete(s.id)
            pruned.append(s.id)
        except Exception:
            continue
    return pruned


def _locate_snapshot(snapshot_id: str) -> tuple[str, dict]:
    """定位快照目录并读 manifest(按 <slug>/<id> 分桶,兼容旧版平铺布局)。"""
    from .db import get_snapshot
    snap = get_snapshot(snapshot_id)
    if snap is None:
        raise FileNotFoundError(f"快照不存在: {snapshot_id}")

    snap_dir = None
    for game_dir in (os.listdir(SNAPSHOTS_DIR) if os.path.isdir(SNAPSHOTS_DIR) else []):
        candidate = os.path.join(SNAPSHOTS_DIR, game_dir, snapshot_id)
        if os.path.isdir(candidate):
            snap_dir = candidate
            break
    if not snap_dir:
        snap_dir = os.path.join(SNAPSHOTS_DIR, snapshot_id)

    manifest_path = os.path.join(snap_dir, "manifest.json")
    if not os.path.exists(manifest_path):
        raise FileNotFoundError(f"快照清单不存在: {manifest_path}")

    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)
    return snap_dir, manifest


def _restore_plan(snap_dir: str, manifest: dict) -> dict:
    """restore 的差集干跑:将删除 / 将还原 / 未变动 / 快照内缺失。
    预览与执行吃同一份 plan(铁律 6 的延伸:预览说什么,执行就做什么)。"""
    game_root = manifest.get("game_root", "")
    game_slug = manifest.get("game_slug", "")
    if not os.path.isdir(game_root):
        raise FileNotFoundError(f"游戏目录不存在: {game_root}")

    specs = _auto_detect_specs(game_root, game_slug)

    # 兼容 v0.8 快照(schema 1:files 存的是绝对路径)
    raw_files = manifest.get("files", [])
    if manifest.get("schema", 1) >= 2:
        snap_files = set(_norm(p) for p in raw_files)
    else:
        snap_files = set()
        for p in raw_files:
            try:
                snap_files.add(_norm(os.path.relpath(p, game_root)))
            except ValueError:
                continue

    # schema 2 时代的开放模式会嗅探整个 Win64/Engine/Plugins，可能把游戏
    # 原生文件写进快照。按当前安全域过滤旧清单，绝不把过宽历史载荷恢复回去。
    ignored_unsafe = sorted(p for p in snap_files if not _path_in_specs(p, specs))
    snap_files = {p for p in snap_files if _path_in_specs(p, specs)}
    live_files = set(_iter_domain_files(game_root, specs))

    to_delete = sorted(live_files - snap_files)      # 快照后新增物
    to_restore: list[str] = []
    missing_in_snapshot: list[str] = []              # manifest 有账、磁盘无货(残缺征兆,如实报)
    unchanged = 0
    for rel in sorted(snap_files):
        src = os.path.join(snap_dir, rel.replace("/", os.sep))
        if not os.path.exists(src):
            missing_in_snapshot.append(rel)
            continue
        dst = os.path.join(game_root, rel.replace("/", os.sep))
        if os.path.exists(dst) and _same_content(src, dst):
            unchanged += 1                           # 内容一致,免拷
        else:
            to_restore.append(rel)

    return {
        "game_root": game_root, "game_slug": game_slug,
        "specs": [(s["dir"] if "dir" in s else f"[自定义落点×{len(s['files'])}]") for s in specs],
        "domain_sniffed": not is_known_snapshot_profile(game_slug, game_root),
        "to_delete": to_delete, "to_restore": to_restore,
        "unchanged": unchanged, "missing_in_snapshot": missing_in_snapshot,
        "ignored_unsafe_snapshot_files": ignored_unsafe,
    }


def snapshot_restore_preview(snapshot_id: str) -> dict:
    """回滚预览(干跑,不落盘):将删除/将还原清单 + 工坊订阅差集。
    前端确认弹窗与开放模式强制确认门都吃这份数据。"""
    snap_dir, manifest = _locate_snapshot(snapshot_id)
    plan = _restore_plan(snap_dir, manifest)
    from . import user_config
    external = user_config.preview_snapshot(snap_dir, manifest)

    ws = manifest.get("workshop")
    ws_preview = None
    if ws and ws.get("appid"):
        try:
            to_unsub, to_resub = _workshop_diff(plan["game_root"], ws)
            ws_preview = {"appid": ws["appid"],
                          "to_unsubscribe": to_unsub, "to_resubscribe": to_resub}
        except Exception:
            ws_preview = None                        # 预览失败不阻塞文件预览(同 reconcile 原则)

    return {
        "snapshot_id": snapshot_id,
        "baseline": not manifest.get("files"),
        "game_slug": plan["game_slug"], "game_root": plan["game_root"],
        "domain_sniffed": plan["domain_sniffed"], "specs": plan["specs"],
        "to_delete": plan["to_delete"], "to_delete_count": len(plan["to_delete"]),
        "to_restore": plan["to_restore"], "to_restore_count": len(plan["to_restore"]),
        "unchanged_count": plan["unchanged"],
        "missing_in_snapshot": plan["missing_in_snapshot"],
        "ignored_unsafe_snapshot_files": plan["ignored_unsafe_snapshot_files"],
        "ignored_unsafe_snapshot_count": len(plan["ignored_unsafe_snapshot_files"]),
        "workshop": ws_preview,
        "external_configs": external,
    }


def snapshot_restore(snapshot_id: str) -> dict:
    """
    回滚到指定快照。返回 {"deleted", "restored", "failed", "files_restored", "workshop"}。
    files_restored = deleted + restored(兼容旧调用方);failed 按操作分桶记录失败文件
    (最常见原因:游戏正在运行,文件被锁 —— errno 归因是战役 3 的活,这里先把账记全)。

    安全边界:只在快照域内动手 —— 删除"域内存在但快照里没有"的文件(即快照后新增的 mod 文件),
    还原快照里的全部文件。快照域外的任何文件(游戏 exe、官方 dll、存档…)永不触碰。
    工坊内容不在游戏目录,按订阅清单差集同步(见 _reconcile_workshop),失败不阻塞文件回滚。
    """
    snap_dir, manifest = _locate_snapshot(snapshot_id)
    plan = _restore_plan(snap_dir, manifest)
    game_root = plan["game_root"]

    from .diagnostics import classify_oserror
    deleted = restored = 0
    failed = {"delete": [], "restore": []}   # 每项 {rel, code, reason, action}(战役3 errno 归因)

    # ① 删除域内的"快照后新增物"
    for rel in plan["to_delete"]:
        full = os.path.join(game_root, rel.replace("/", os.sep))
        try:
            os.remove(full)
            deleted += 1
        except OSError as e:
            failed["delete"].append({"rel": rel, **classify_oserror(e, full)})

    # ② 还原快照内容(copy2,不用硬链接 —— 还原出来的必须是独立文件)
    for rel in plan["to_restore"]:
        src = os.path.join(snap_dir, rel.replace("/", os.sep))
        dst = os.path.join(game_root, rel.replace("/", os.sep))
        try:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(src, dst)
            restored += 1
        except OSError as e:
            failed["restore"].append({"rel": rel, **classify_oserror(e, dst)})

    # 文件删除后清掉域内空目录，避免诊断工具只看到 GITifa/FF7RML 等空壳目录
    # 就误判为“Mod 仍残留”。只处理目录型安全域，绝不向上删除游戏目录。
    directories_removed = 0
    for spec in _auto_detect_specs(game_root, manifest.get("game_slug", "")):
        if "dir" not in spec:
            continue
        base = os.path.join(game_root, spec["dir"].replace("/", os.sep))
        if not os.path.isdir(base):
            continue
        for current, _, _ in os.walk(base, topdown=False):
            if current == base:
                continue
            try:
                os.rmdir(current)
                directories_removed += 1
            except OSError:
                pass

    ws = manifest.get("workshop")
    ws_result = _reconcile_workshop(game_root, ws) if ws and ws.get("appid") else None
    from . import user_config
    external_result = user_config.restore_snapshot(snap_dir, manifest)
    # 执行后用同一差分器重新核验。只有差分归零才叫完成；目录存在与否不能
    # 替代文件级验证，也不能因 restored=0（原本一致）误判为未恢复。
    after = _restore_plan(snap_dir, manifest)
    complete = (not after["to_delete"] and not after["to_restore"]
                and not after["missing_in_snapshot"]
                and not failed["delete"] and not failed["restore"]
                and external_result.get("complete"))
    return {
        "status": "complete" if complete else "incomplete",
        "complete": complete,
        "deleted": deleted,
        "restored": restored,
        "unchanged_verified": after["unchanged"],
        "verified_target_files": after["unchanged"],
        "pending_delete": after["to_delete"],
        "pending_restore": after["to_restore"],
        "missing_in_snapshot": after["missing_in_snapshot"],
        "ignored_unsafe_snapshot_files": after["ignored_unsafe_snapshot_files"],
        # 旧字段保留，但语义改为“实际复制还原数”；不再把删除伪装成还原。
        "files_restored": restored,
        "operations_applied": deleted + restored,
        "directories_removed": directories_removed,
        "failed": failed,
        "workshop": ws_result,
        "external_configs": external_result,
    }


def list_snapshots_dir() -> list[str]:
    if not os.path.exists(SNAPSHOTS_DIR):
        return []
    result = []
    for entry in os.listdir(SNAPSHOTS_DIR):
        sub = os.path.join(SNAPSHOTS_DIR, entry)
        if os.path.isdir(sub) and entry.startswith("snap_"):
            result.append(entry)
        elif os.path.isdir(sub):
            for snap in os.listdir(sub):
                if snap.startswith("snap_"):
                    result.append(snap)
    return sorted(result, reverse=True)
