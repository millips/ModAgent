import json
import os
import shutil
import time

SNAPSHOTS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "snapshots")

# Known mod directories per game as hints. Auto-detection fills gaps.
GAME_MOD_DIRS = {
    "cyberpunk2077": ["archive/pc/mod", "bin/x64/plugins", "r6/scripts", "r6/tweaks"],
    "skyrimspecialedition": ["Data", "SKSE"],
    "fallout4": ["Data"],
    # UE 系(剑星等):pak mod + 注入器目录都要纳入快照,否则 UE4SS 类改动无法回滚
    "stellarblade": ["SB/Content/Paks/~mods", "SB/Binaries/Win64"],
}

# 目录名白名单:自动发现时命中这些名字则纳入
_WATCH_DIR_NAMES = ("~mods", "mods", "mod", "plugins", "scripts",
                    "r6", "tweaks", "archive", "data", "skse", "win64")


def _auto_detect_mod_dirs(game_root: str, game_slug: str) -> list[str]:
    """
    自动发现 mod 目录。
    变更:不再返回 ['.'] 兜底(那会导致 copytree 整个游戏目录)。
    发现不到就返回 [],由调用方决定如何处理(快照将判定为空)。
    """
    known = GAME_MOD_DIRS.get(game_slug, [])
    if known and any(os.path.isdir(os.path.join(game_root, k)) for k in known):
        return [k for k in known if os.path.isdir(os.path.join(game_root, k))]

    discovered: list[str] = []
    if not os.path.isdir(game_root):
        return discovered

    for root, dirs, _ in os.walk(game_root):
        depth = root.replace(game_root, "").count(os.sep)
        if depth > 5:
            dirs[:] = []          # 剪枝,别再往深走
            continue
        for d in dirs:
            if d.lower() in _WATCH_DIR_NAMES:
                rel = os.path.relpath(os.path.join(root, d), game_root).replace("\\", "/")
                if rel not in discovered:
                    discovered.append(rel)

    return discovered[:6]         # 不再有 ['.'] 兜底


def snapshot_create(game_root: str, game_slug: str, trigger_mod_id: str = "", trigger_mod_name: str = "") -> str:
    """
    创建快照。
    变更(P3.1):只有真正备份到文件才写 DB / 保留目录;
              0 文件视为失败,清理空目录并抛出异常,绝不写一条空快照进 DB。
    调用方注意:若安装流程内部调用本函数,请处理 ValueError(或先确认目标目录非空)。
    """
    if not os.path.isdir(game_root):
        raise FileNotFoundError(f"游戏目录不存在: {game_root}")

    target_dirs = _auto_detect_mod_dirs(game_root, game_slug)

    # ID 去重:同一秒内多次创建不再撞目录/覆盖
    base = time.strftime("%Y%m%d_%H%M%S")
    snap_id = f"snap_{base}"
    game_snap_root = os.path.join(SNAPSHOTS_DIR, game_slug)
    n = 1
    while os.path.exists(os.path.join(game_snap_root, snap_id)):
        n += 1
        snap_id = f"snap_{base}_{n}"
    snap_dir = os.path.join(game_snap_root, snap_id)
    os.makedirs(snap_dir, exist_ok=True)

    files_backed_up: list[str] = []
    absent_dirs: list[str] = []

    for rel_dir in target_dirs:
        src = os.path.join(game_root, rel_dir)
        if not os.path.exists(src):
            absent_dirs.append(rel_dir)
            continue
        dst = os.path.join(snap_dir, rel_dir)
        try:
            shutil.copytree(src, dst, dirs_exist_ok=True)
            for root, _, files in os.walk(src):
                for f in files:
                    files_backed_up.append(os.path.join(root, f))
        except Exception:
            continue

    # ✅ P3.1:0 文件 → 不写 DB,清掉空目录,明确报错
    if not files_backed_up:
        try:
            shutil.rmtree(snap_dir, ignore_errors=True)
        except Exception:
            pass
        raise ValueError(
            "empty_snapshot: 未在以下目录发现任何文件,快照未创建 "
            f"(scanned={target_dirs or '[]'})。请确认游戏目录/游戏 profile 是否正确。"
        )

    manifest = {
        "snapshot_id": snap_id,
        "timestamp": time.time(),
        "game_root": game_root,
        "game_slug": game_slug,
        "files_count": len(files_backed_up),
        "files": files_backed_up,
        "absent_dirs": absent_dirs,
        "trigger_mod_id": trigger_mod_id,
        "trigger_mod_name": trigger_mod_name,
    }
    with open(os.path.join(snap_dir, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

    # 全部落盘成功后才写 DB
    from .db import Snapshot, add_snapshot
    add_snapshot(Snapshot(
        id=snap_id, timestamp=time.time(),
        # 注意:这里存的是 list,配合 api.py 修好的 files_count 统计(见 api_patches.md)
        files=json.dumps(files_backed_up),
        trigger_mod_id=trigger_mod_id, trigger_mod_name=trigger_mod_name,
        game_slug=game_slug,
    ))

    return snap_id


def snapshot_restore(snapshot_id: str) -> int:
    from .db import get_snapshot
    snap = get_snapshot(snapshot_id)
    if snap is None:
        raise FileNotFoundError(f"快照不存在: {snapshot_id}")

    snap_dir = None
    for game_dir in os.listdir(SNAPSHOTS_DIR) if os.path.isdir(SNAPSHOTS_DIR) else []:
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

    game_root = manifest.get("game_root", "")
    game_slug = manifest.get("game_slug", "")
    target_dirs = _auto_detect_mod_dirs(game_root, game_slug)
    snapshot_files = set(manifest.get("files", []))
    absent_dirs = set(manifest.get("absent_dirs", []))
    restored = 0
    deleted = 0

    for rel_dir in target_dirs:
        live_dir = os.path.join(game_root, rel_dir)

        if rel_dir in absent_dirs:
            if os.path.exists(live_dir):
                shutil.rmtree(live_dir)
                deleted += 1
            continue

        if os.path.exists(live_dir):
            for root, _, files in os.walk(live_dir):
                for f in files:
                    full = os.path.join(root, f)
                    if full not in snapshot_files:
                        try:
                            os.remove(full)
                            deleted += 1
                        except Exception:
                            pass

        snap_src = os.path.join(snap_dir, rel_dir)
        if not os.path.exists(snap_src):
            continue
        try:
            for root, _, files in os.walk(snap_src):
                for f in files:
                    rel = os.path.relpath(os.path.join(root, f), snap_dir)
                    dest = os.path.join(game_root, rel)
                    os.makedirs(os.path.dirname(dest), exist_ok=True)
                    shutil.copy2(os.path.join(root, f), dest)
                    restored += 1
        except Exception:
            continue

    return restored + deleted


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
