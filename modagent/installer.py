import json
import os
import shutil
import zipfile
import re
import tempfile
import subprocess
import hashlib
import uuid
from typing import Optional


class UnsupportedInstallLayout(RuntimeError):
    """The archive is valid, but deterministic game routing cannot place it.

    Carry the evidence needed by the agent to build an explicit, reviewable
    ``mod_install_custom`` mapping.  This is deliberately different from an
    extraction or write failure: callers must not blindly retry the same
    generic installer.
    """

    def __init__(
        self,
        message: str,
        *,
        archive_members: Optional[list[str]] = None,
        install_notes: str = "",
    ):
        self.archive_members = list(archive_members or [])
        self.install_notes = str(install_notes or "")
        super().__init__(message)

from .config import CONFIG_DIR

# C-0:集中备份区。原地 .modagent_bak 兄弟文件是在逃 bug ——
# CNS 等 mod 框架用非锚定子串扫描配置(string.find(name,'dekcns.json')),
# 原地备份会被当成正经配置产生"重影",且每次覆盖安装都复发。
BACKUPS_DIR = os.path.join(CONFIG_DIR, "backups")


def resolve_managed_game_path(path: str, game_root: str) -> tuple[str, str]:
    """Resolve a ledger path and fail closed unless it is inside the game root.

    Mod records are persistent input, not an authority boundary.  Old versions,
    manual database edits, junctions and symlinks can all turn a once-valid
    absolute path into a path outside the selected game.  Every destructive
    ledger operation must call this helper immediately before touching disk.
    """
    try:
        raw = os.fspath(path)
    except TypeError:
        return "", "记录不是有效文件路径"
    if not isinstance(raw, str) or not raw.strip():
        return "", "记录路径为空"
    if not game_root:
        return "", "未配置游戏根目录"

    root_abs = os.path.abspath(game_root)
    root_real = os.path.realpath(root_abs)
    drive, _ = os.path.splitdrive(root_real)
    anchor = drive + os.sep if drive else os.path.abspath(os.sep)
    if os.path.normcase(root_real) == os.path.normcase(anchor):
        return "", "游戏根目录不能是磁盘根目录"

    candidate = raw if os.path.isabs(raw) else os.path.join(root_abs, raw)
    candidate_abs = os.path.abspath(candidate)
    candidate_real = os.path.realpath(candidate_abs)
    try:
        within = (
            os.path.normcase(os.path.commonpath([root_real, candidate_real]))
            == os.path.normcase(root_real)
        )
    except ValueError:
        within = False
    if not within or os.path.normcase(candidate_real) == os.path.normcase(root_real):
        return "", "记录路径越出当前游戏目录"
    return candidate_abs, ""


def _file_fingerprint(path: str) -> tuple[int, str]:
    """Return size and SHA-256 for an on-disk commit verification."""
    digest = hashlib.sha256()
    size = 0
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            size += len(chunk)
            digest.update(chunk)
    return size, digest.hexdigest()


def _commit_files_transactionally(operations: list[dict], game_root: str,
                                  game_slug: str) -> list[dict]:
    """Stage and atomically commit a complete install plan.

    Every source is copied and hashed before the game directory is changed. Existing
    destinations are moved into a same-volume rollback area, staged files are then
    moved into place with ``os.replace``, and every committed file is re-hashed. Any
    failure restores all previous files and removes newly-created files.
    """
    if not operations:
        return []
    real_root = os.path.realpath(game_root)
    seen = set()
    for operation in operations:
        src = os.path.realpath(operation["src"])
        dest = os.path.realpath(operation["dest"])
        if not os.path.isfile(src):
            raise RuntimeError(f"安装预检失败，源文件不存在: {operation['src']}")
        try:
            if os.path.commonpath([real_root, dest]) != real_root:
                raise RuntimeError(f"安装预检失败，目标越出游戏目录: {operation['dest']}")
        except ValueError as exc:
            raise RuntimeError(f"安装预检失败，目标路径无效: {operation['dest']}") from exc
        key = os.path.normcase(dest)
        if key in seen:
            raise RuntimeError(f"安装预检失败，多个文件映射到同一目标: {operation['dest']}")
        seen.add(key)

    transaction_root = os.path.join(game_root, f".modagent-transaction-{uuid.uuid4().hex}")
    stage_root = os.path.join(transaction_root, "stage")
    rollback_root = os.path.join(transaction_root, "rollback")
    committed = []
    moved_originals = []
    cleanup_transaction = True
    try:
        os.makedirs(stage_root, exist_ok=False)
        os.makedirs(rollback_root, exist_ok=False)
        for index, operation in enumerate(operations):
            staged = os.path.join(stage_root, str(index))
            shutil.copy2(operation["src"], staged)
            operation["staged"] = staged
            operation["fingerprint"] = _file_fingerprint(staged)

        for index, operation in enumerate(operations):
            dest = operation["dest"]
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            existed = os.path.exists(dest)
            operation["existed"] = existed
            if existed:
                _backup_file(dest, game_root, game_slug)
                rollback = os.path.join(rollback_root, str(index))
                os.replace(dest, rollback)
                moved_originals.append((dest, rollback))
            os.replace(operation["staged"], dest)
            committed.append(dest)
            if _file_fingerprint(dest) != operation["fingerprint"]:
                raise RuntimeError(f"安装落盘复核失败: {dest}")

        installed = []
        for operation in operations:
            record = dict(operation.get("record", {}))
            record["dest"] = operation["dest"]
            record.setdefault("overwrote", operation["existed"])
            record["size"] = operation["fingerprint"][0]
            record["sha256"] = operation["fingerprint"][1]
            installed.append(record)
        return installed
    except Exception as original_error:
        restore_errors = []
        for dest in reversed(committed):
            try:
                if os.path.exists(dest):
                    os.remove(dest)
            except OSError as exc:
                restore_errors.append(f"无法移除失败提交 {dest}: {exc}")
        for dest, rollback in reversed(moved_originals):
            try:
                if os.path.exists(rollback):
                    os.makedirs(os.path.dirname(dest), exist_ok=True)
                    os.replace(rollback, dest)
            except OSError as exc:
                restore_errors.append(f"无法恢复原文件 {dest}: {exc}")
        if restore_errors:
            # Never delete the only remaining copy of an original file. Keeping the
            # transaction directory makes the failure recoverable and diagnosable.
            cleanup_transaction = False
            raise RuntimeError(
                "安装提交失败且自动恢复不完整；回滚文件已保留在 "
                f"{transaction_root}: {'; '.join(restore_errors)}"
            ) from original_error
        raise
    finally:
        if cleanup_transaction:
            shutil.rmtree(transaction_root, ignore_errors=True)


def _backup_file(dest: str, game_root: str, game_slug: str) -> None:
    """覆盖前把原文件备份到集中区(~/.modagent/backups/<slug>/<相对路径>)。
    保留首份(最原始版本)。备份失败不阻塞安装——快照才是第一还原手段。"""
    try:
        rel = os.path.relpath(dest, game_root)
        if rel.startswith(".."):
            rel = os.path.basename(dest)
        bak = os.path.join(BACKUPS_DIR, game_slug or "_unknown", rel)
        if not os.path.exists(bak):
            os.makedirs(os.path.dirname(bak), exist_ok=True)
            shutil.copy2(dest, bak)
    except Exception:
        pass


def _backup_lookup(f: str, game_root: str, game_slug: str) -> str:
    """查文件对应的备份:优先集中区,其次旧版原地 .modagent_bak(迁移期兼容)。无则返回空串。"""
    try:
        rel = os.path.relpath(f, game_root)
        if not rel.startswith(".."):
            central = os.path.join(BACKUPS_DIR, game_slug or "_unknown", rel)
            if os.path.exists(central):
                return central
    except ValueError:
        pass
    legacy = f + ".modagent_bak"
    return legacy if os.path.exists(legacy) else ""

# ─────────────────────────────────────────────────────────────
# C-6①:框架级 layout 生成器
# 落位规则属于"引擎/加载器生态",不属于单个游戏——剑星和 Palworld 的规则
# 除了 SB/ ↔ Pal/ 前缀外逐条相同,这是 per-framework 规则伪装成了 per-game。
# 新接一个同框架游戏 = 游戏表加一行参数,不再复制整段正则。
# ─────────────────────────────────────────────────────────────

def _ue_layout(project: str, extra_patterns: dict = None) -> dict:
    """UE4/5 通用约定:pak 三件套→~mods 扁平化 + UE4SS 注入器→exe 目录。
    project = UE 项目目录前缀(剑星 SB、Palworld 是 Pal)。
    extra_patterns 插在注入器规则之后、pak 兜底之前(如剑星的 CNS 注册文件)。"""
    pat = {
        # 结构化包(顺序在前,优先匹配,保留作者目录结构):
        # UE4SS 官方结构 "Copy the <project> folder into game root" → 原样合并
        rf"^{project}[/\\]": "",
        # 缺项目前缀、以 Binaries/ 或 Content/ 开头的包 → 补上前缀
        rf"^Binaries[/\\]": f"{project}/",
        rf"^Content[/\\]": f"{project}/",
        # 注入器散件(根目录直接就是 dll / ue4ss 文件夹)→ exe 目录
        r"^(?:dwmapi|xinput1_3|dsound|version|d3d11|winmm)\.dll$": f"{project}/Binaries/Win64/",
        r"^ue4ss[/\\]": f"{project}/Binaries/Win64/",
        r"^UE4SS-settings\.ini$": f"{project}/Binaries/Win64/",
    }
    if extra_patterns:
        pat.update(extra_patterns)
    # 松散 pak 三件套 → ~mods 扁平化(UE 递归加载),放最后兜底
    pat.update({
        r"\.pak$": f"{project}/Content/Paks/~mods/",
        r"\.ucas$": f"{project}/Content/Paks/~mods/",
        r"\.utoc$": f"{project}/Content/Paks/~mods/",
    })
    return {"patterns": pat, "load_order_file": None}


def _melonloader_layout() -> dict:
    """Unity IL2CPP + MelonLoader 约定。MelonLoader 只扫 Mods/ 顶层(不递归),
    散 dll 一律扁平化落 Mods/ 根(见 _resolve_dest)。少数 BepInEx 结构包由 ^BepInEx/ 兜住。"""
    return {
        "patterns": {
            # 结构化 MelonLoader 目录 → 原样合并到游戏根
            r"^Mods[/\\]": "",
            r"^UserData[/\\]": "",
            r"^UserLibs[/\\]": "",
            r"^Plugins[/\\]": "",
            # 加载器自举(MelonLoader.x64.zip = MelonLoader/ + version.dll + dobby.dll)
            r"^MelonLoader[/\\]": "",
            r"^(?:version|dobby)\.dll$": "",
            # 显式 BepInEx 结构包 → 原样合并(少数派生态)
            r"^BepInEx[/\\]": "",
            # 散 dll 兜底 → Mods/ 扁平化
            r"\.dll$": "Mods/",
        },
        "load_order_file": None,
    }


def _bethesda_layout(archive_exts: tuple, loose_dirs: tuple, injector_dirs: tuple = ()) -> dict:
    """Bethesda 系(天际/辐射…):插件与资源进 Data/,脚本扩展器(SKSE 等)进游戏根。"""
    pat = {
        r"\.esp$": "Data/",
        r"\.esm$": "Data/",
        r"\.esl$": "Data/",
    }
    for ext in archive_exts:
        pat[rf"\.{ext}$"] = "Data/"
    for d in loose_dirs:
        pat[rf"^{d}[/\\]"] = "Data/"
    for d in injector_dirs:
        pat[rf"^{d}[/\\]"] = ""
    pat[r"^Data[/\\]"] = ""
    return {"patterns": pat, "load_order_file": None}


def _redengine_layout() -> dict:
    """REDengine(2077):archive/reds 散件归位,结构化目录原样合并。"""
    return {
        "patterns": {
            r"\.archive$": "archive/pc/mod/",
            r"\.reds$": "r6/scripts/",
            r"^bin[/\\]": "",
            r"^engine[/\\]": "",
            r"^r6[/\\]": "",
            r"^archive[/\\]": "",
            r"^mods[/\\]": "mods/",
        },
        "load_order_file": None,
    }


# 游戏表:每游戏一行 (框架 + 参数)。
# 注意(Palworld):创意工坊 mod 由 Steam 自己下到 steamapps/workshop,不走本 installer;
# 这里只处理 Nexus 包。未匹配文件进 skipped,不硬装(汉化/系统类落别处的优雅降级)。
GAME_LAYOUTS = {
    "stardewvalley": {
        "patterns": {},
        "load_order_file": None,
        "handler": "stardew_smapi",
    },
    "stellarblade": _ue_layout("SB", extra_patterns={
        # CNS 注册文件 → ~mods 扁平化(CNS 从 ~mods 根递归扫描,见 DekCNS main.lua DekCNS_ScanConfigs)
        r"\.dekcns\.json$": "SB/Content/Paks/~mods/",
        r"\.dekani\.json$": "SB/Content/Paks/~mods/",
    }),
    "palworld": _ue_layout("Pal"),
    "phasmophobia": _melonloader_layout(),
    "cyberpunk2077": _redengine_layout(),
    "skyrimspecialedition": {
        **_bethesda_layout(("bsa",), ("meshes", "textures", "scripts"), ("SKSE",)),
        "load_order_file": "plugins.txt",
        "load_order_dir_env": "LOCALAPPDATA",
        "load_order_subpath": "Skyrim Special Edition",
    },
    "fallout4": _bethesda_layout(("ba2",), ("meshes", "textures")),
    "finalfantasy7rebirth": {
        "handler": "ff7r",
        "patterns": _ue_layout("End")["patterns"],
        "load_order_file": None,
    },
    # RE Engine / Fluffy Mod Manager packages preserve the ``natives`` tree
    # under the game root.  Top-level modinfo.ini and preview images are
    # manager metadata, not runtime files.
    "streetfighter6": {
        "patterns": {
            r"^natives[/\\]": "",
            r"^reframework[/\\]": "",
        },
        "load_order_file": None,
    },
}

_GAME_SLUG_ALIASES = {
    "local_final_fantasy_vii_rebirth": "finalfantasy7rebirth",
    "final_fantasy_vii_rebirth": "finalfantasy7rebirth",
    "local_street_fighter_6": "streetfighter6",
    "street_fighter_6": "streetfighter6",
    "streetfighter_6": "streetfighter6",
}


def _find_7zip() -> Optional[str]:
    candidates = [
        r"C:\Program Files\7-Zip\7z.exe",
        r"C:\Program Files (x86)\7-Zip\7z.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\7-Zip\7z.exe"),
        os.path.expandvars(r"%USERPROFILE%\scoop\apps\7zip\current\7z.exe"),
        r"C:\ProgramData\chocolatey\bin\7z.exe",
    ]
    for p in candidates:
        if p and os.path.exists(p):
            return p
    return (shutil.which("7z") or shutil.which("7z.exe")
            or shutil.which("7za") or shutil.which("7zr"))


def _detect_format(path: str) -> Optional[str]:
    """按魔数识别真实压缩格式（Nexus 下载常把 rar/7z 命名成 .zip）。"""
    try:
        with open(path, "rb") as f:
            head = f.read(8)
    except OSError:
        return None
    if head[:4] in (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08"):
        return "zip"
    if head[:4] == b"Rar!":
        return "rar"
    if head[:6] == b"7z\xbc\xaf\x27\x1c":
        return "7z"
    return None


def extract_archive(archive_path: str, extract_to: str) -> list[str]:
    if not os.path.exists(archive_path):
        raise FileNotFoundError(f"压缩包不存在: {archive_path}")
    os.makedirs(extract_to, exist_ok=True)

    # 优先按真实内容判断格式，扩展名只作兜底
    fmt = _detect_format(archive_path) or os.path.splitext(archive_path)[1].lower().lstrip(".")

    if fmt == "zip":
        try:
            with zipfile.ZipFile(archive_path, "r") as zf:
                root = os.path.abspath(extract_to)
                for member in zf.infolist():
                    destination = os.path.abspath(
                        os.path.join(root, member.filename)
                    )
                    if os.path.commonpath((root, destination)) != root:
                        raise RuntimeError(
                            f"压缩包包含越界路径，已拒绝解压: {member.filename}"
                        )
                zf.extractall(extract_to)
                return zf.namelist()
        except Exception as e:
            # 非标准 zip / zipfile 不支持的压缩方法 → 用兼容性更强的 7-Zip 兜底
            seven_zip = _find_7zip()
            if seven_zip:
                return _extract_with_7zip(seven_zip, archive_path, extract_to)
            raise RuntimeError(f"zip 解压失败（非标准格式），且未找到 7-Zip 兜底: {e}")

    if fmt in ("rar", "7z"):
        seven_zip = _find_7zip()
        if not seven_zip:
            raise RuntimeError(f"该文件是 {fmt.upper()} 格式，需要 7-Zip 才能解压。请从 https://7-zip.org 下载安装。")
        return _extract_with_7zip(seven_zip, archive_path, extract_to)

    raise RuntimeError(f"不支持或无法识别的压缩格式: {fmt or '未知'}")


def _extract_with_7zip(seven_zip: str, archive_path: str, extract_to: str) -> list[str]:
    proc = subprocess.run([seven_zip, "x", archive_path, f"-o{extract_to}", "-y"],
                          capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"7-Zip 解压失败: {(proc.stderr or proc.stdout or '').strip()[:200]}")
    result = []
    for root, _, files in os.walk(extract_to):
        for f in files:
            result.append(os.path.relpath(os.path.join(root, f), extract_to))
    return result


def get_game_layout(game_slug: str) -> dict:
    normalized = str(game_slug or "").strip().lower()
    canonical = _GAME_SLUG_ALIASES.get(normalized, normalized)
    return GAME_LAYOUTS.get(canonical, {
        "patterns": {},
        "load_order_file": None,
    })


_INSTALL_NOTE_NAMES = {
    "readme.txt", "readme.md", "readme", "readme.html",
    "install.txt", "install.md", "installation.txt", "installation.md",
}


def _read_install_notes_from_tree(root_dir: str, limit: int = 20000) -> str:
    """Read package-authored installation notes from an extracted archive."""
    candidates = []
    for current, _, files in os.walk(root_dir):
        for filename in files:
            if filename.casefold() in _INSTALL_NOTE_NAMES:
                path = os.path.join(current, filename)
                rel = os.path.relpath(path, root_dir).replace("\\", "/")
                candidates.append((rel.count("/"), rel.casefold(), rel, path))
    chunks = []
    remaining = max(1000, int(limit))
    for _, _, rel, path in sorted(candidates):
        if remaining <= 0:
            break
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as handle:
                content = handle.read(remaining)
        except OSError:
            continue
        if content.strip():
            section = f"## {rel}\n{content.strip()}"
            chunks.append(section)
            remaining -= len(section)
    return "\n\n".join(chunks)


def _ff7r_dest(member: str, plugin_roots: set[str], game_root: str) -> Optional[str]:
    norm = member.replace("\\", "/").lstrip("/")
    low = norm.lower()
    if low.startswith("end/"):
        rel = norm
    else:
        first = norm.split("/", 1)[0]
        if first.lower() in plugin_roots:
            rel = f"End/Mods/{norm}"
        elif re.search(r"(?:^|/)(?:dwmapi|xinput1_3|dsound|version|d3d11|winmm)\.dll$", low):
            rel = f"End/Binaries/Win64/{os.path.basename(norm)}"
        elif low.endswith((".pak", ".ucas", ".utoc")):
            rel = f"End/Content/Paks/~mods/{os.path.basename(norm)}"
        else:
            return None
    dest = os.path.normpath(os.path.join(game_root, rel.replace("/", os.sep)))
    try:
        if os.path.commonpath([os.path.realpath(game_root), os.path.realpath(dest)]) != os.path.realpath(game_root):
            return None
    except ValueError:
        return None
    return dest


def _install_ff7r(archive_path: str, game_root: str, game_slug: str) -> dict:
    """FF7 Rebirth：识别 End/ 结构、Dresscode 插件目录、注入器和松散 pak。"""
    result = {"installed": [], "skipped": [], "errors": []}
    with tempfile.TemporaryDirectory() as tmp:
        extract_archive(archive_path, tmp)
        walk_root = tmp
        while True:
            entries = [e for e in os.listdir(walk_root) if e.lower() != "__macosx"]
            if len(entries) != 1 or not os.path.isdir(os.path.join(walk_root, entries[0])):
                break
            candidate = os.path.join(walk_root, entries[0])
            # End 是游戏结构；直接含 .uplugin 的单目录是插件本体，两者都不能剥。
            if entries[0].lower() == "end" or any(
                    f.lower().endswith(".uplugin") for f in os.listdir(candidate)
                    if os.path.isfile(os.path.join(candidate, f))):
                break
            walk_root = candidate
        members = []
        for current, _, files in os.walk(walk_root):
            members.extend(os.path.relpath(os.path.join(current, f), walk_root) for f in files)
        plugin_roots = {
            m.replace("\\", "/").split("/", 1)[0].lower()
            for m in members if m.lower().endswith(".uplugin") and "/" in m.replace("\\", "/")
        }
        operations = []
        for member in members:
            dest = _ff7r_dest(member, plugin_roots, game_root)
            if not dest:
                result["skipped"].append(member)
                continue
            operations.append({
                "src": os.path.join(walk_root, member), "dest": dest,
                "record": {"file": member},
            })
        result["installed"] = _commit_files_transactionally(operations, game_root, game_slug)
    if not result["installed"]:
        raise RuntimeError("未识别到 FF7 Rebirth 的 End/Mods、注入器或 pak 文件，已停止安装。")
    return result


def _safe_mod_folder_name(value: str, fallback: str = "SMAPI-Mod") -> str:
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", str(value or "")).strip(" .")
    return (value or fallback)[:100]


def _relative_child_path(path: str, root: str) -> str:
    """Return a lexical child path while validating its canonical containment.

    Windows can expose the same temporary directory through both a long path and
    an 8.3 short path (for example ``RunnerAdmin`` and ``RUNNER~1``). Mixing a
    canonical root with a lexical child makes ``relpath`` manufacture ``..``
    segments. Keep both operands in their original absolute representation for
    the relative path, and use real paths only for the containment check.
    """
    absolute_path = os.path.abspath(path)
    absolute_root = os.path.abspath(root)
    real_path = os.path.normcase(os.path.realpath(absolute_path))
    real_root = os.path.normcase(os.path.realpath(absolute_root))
    try:
        if os.path.commonpath([real_root, real_path]) != real_root:
            raise ValueError(f"路径越出根目录: {path}")
    except ValueError as exc:
        raise ValueError(f"路径不属于指定根目录: {path}") from exc

    relative = os.path.relpath(absolute_path, absolute_root)
    if relative == os.pardir or relative.startswith(os.pardir + os.sep):
        raise ValueError(f"相对路径越出根目录: {path}")
    return relative


def _is_same_or_child_path(path: str, root: str) -> bool:
    try:
        _relative_child_path(path, root)
        return True
    except ValueError:
        return False


def _install_stardew_smapi(
    archive_path: str, game_root: str, game_slug: str,
) -> dict:
    """Install complete SMAPI packages below Mods/, preserving manifest roots."""
    result = {
        "installed": [], "skipped": [], "errors": [],
        "handler": "stardew_smapi", "verified_mods": [],
    }
    with tempfile.TemporaryDirectory() as tmp:
        extract_archive(archive_path, tmp)
        manifest_roots = []
        for current, dirs, files in os.walk(tmp):
            dirs[:] = [name for name in dirs if name.casefold() != "__macosx"]
            manifest_name = next(
                (name for name in files if name.casefold() == "manifest.json"),
                "",
            )
            if not manifest_name:
                continue
            manifest_path = os.path.join(current, manifest_name)
            try:
                with open(manifest_path, "r", encoding="utf-8-sig") as handle:
                    manifest = json.load(handle)
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                raise RuntimeError(
                    f"SMAPI manifest.json 无法解析: {manifest_path}: {exc}"
                ) from exc
            unique_id = str(manifest.get("UniqueID") or "").strip()
            name = str(manifest.get("Name") or "").strip()
            if not unique_id or not name:
                raise RuntimeError(
                    f"SMAPI manifest.json 缺少 Name/UniqueID: {manifest_path}"
                )
            # Preserve the lexical extraction path. Converting only this side to
            # realpath can turn it into an 8.3 short path on Windows CI and make
            # later relpath calculations escape through artificial ``..`` parts.
            manifest_roots.append((os.path.abspath(current), manifest))

        if not manifest_roots:
            raise RuntimeError(
                "Stardew Valley Mod 压缩包中未找到有效的 SMAPI manifest.json；"
                "已停止安装，未使用 BepInEx 兜底。"
            )

        manifest_roots.sort(key=lambda item: len(item[0]), reverse=True)
        used_folders = set()
        root_targets = {}
        for manifest_root, manifest in manifest_roots:
            relative = _relative_child_path(manifest_root, tmp)
            leaf = "" if relative == "." else os.path.basename(manifest_root)
            folder = _safe_mod_folder_name(
                leaf or manifest.get("Name"),
                str(manifest.get("UniqueID") or "SMAPI-Mod"),
            )
            base_folder = folder
            suffix = 2
            while folder.casefold() in used_folders:
                folder = f"{base_folder}-{suffix}"
                suffix += 1
            used_folders.add(folder.casefold())
            root_targets[manifest_root] = folder

        operations = []
        for current, dirs, files in os.walk(tmp):
            dirs[:] = [name for name in dirs if name.casefold() != "__macosx"]
            owner_root = next(
                (
                    root for root, _ in manifest_roots
                    if _is_same_or_child_path(current, root)
                ),
                "",
            )
            if not owner_root:
                for filename in files:
                    result["skipped"].append(
                        _relative_child_path(os.path.join(current, filename), tmp)
                    )
                continue
            folder = root_targets[owner_root]
            for filename in files:
                source = os.path.join(current, filename)
                relative = _relative_child_path(source, owner_root)
                destination = os.path.join(game_root, "Mods", folder, relative)
                operations.append({
                    "src": source,
                    "dest": destination,
                    "record": {
                        "file": _relative_child_path(source, tmp),
                        "smapi_unique_id": next(
                            str(manifest.get("UniqueID") or "")
                            for root, manifest in manifest_roots
                            if root == owner_root
                        ),
                    },
                })

        result["installed"] = _commit_files_transactionally(
            operations, game_root, game_slug
        )

        for manifest_root, manifest in manifest_roots:
            folder = root_targets[manifest_root]
            installed_root = os.path.join(game_root, "Mods", folder)
            installed_manifest = os.path.join(installed_root, "manifest.json")
            entry_dll = str(manifest.get("EntryDll") or "").strip()
            if not os.path.isfile(installed_manifest):
                raise RuntimeError(
                    f"SMAPI 安装复核失败，manifest 未落入 Mods/: {installed_manifest}"
                )
            if entry_dll and not os.path.isfile(os.path.join(installed_root, entry_dll)):
                raise RuntimeError(
                    f"SMAPI 安装复核失败，EntryDll 缺失: {entry_dll}"
                )
            result["verified_mods"].append({
                "name": str(manifest.get("Name") or ""),
                "unique_id": str(manifest.get("UniqueID") or ""),
                "version": str(manifest.get("Version") or ""),
                "folder": folder,
                "entry_dll": entry_dll,
            })
    return result


def detect_mod_structure(archive_path: str) -> list[str]:
    with tempfile.TemporaryDirectory() as tmp:
        return extract_archive(archive_path, tmp)


def _strip_wrapper_dirs(base: str, keep: set | None = None) -> str:
    """智能剥壳:很多 zip(GitHub release、Thunderstore 的 BepInExPack)把内容包在一层
    版本号/作者名壳目录里(如 UE4SS_v3.1.0-6/... 或 BepInExPack/...),导致路径规则匹配不上。
    若顶层只有【一个目录、无散文件】(忽略 __MACOSX),就把这层壳剥掉。可能有多层,循环剥。
    keep=不可剥的语义目录名集合(小写):包顶层只有一个 Mods/ 或 BepInEx/ 时,
    那不是壳而是结构本身,剥掉会让内容物沦为散文件被错误扁平化。"""
    while True:
        try:
            entries = os.listdir(base)
        except Exception:
            return base
        real = [e for e in entries if e.lower() not in ("__macosx",)]
        if (len(real) == 1 and os.path.isdir(os.path.join(base, real[0]))
                and not (keep and real[0].lower() in keep)):
            base = os.path.join(base, real[0])
        else:
            return base


def _layout_keep_dirs(patterns: dict) -> set:
    """从 layout patterns 推导不可剥壳的目录名:形如 ^Name[/\\] 的规则,Name 就是语义目录。"""
    keep = set()
    for pat in patterns:
        m = re.match(r"\^([A-Za-z0-9_~]+)\[", pat)
        if m:
            keep.add(m.group(1).lower())
    return keep


# Thunderstore 包的元数据文件(顶层),永远不安装
_TS_META = {"manifest.json", "icon.png", "readme.md", "changelog.md",
            "license", "license.txt", "license.md"}
# Thunderstore/r2modman 默认安装规则:包根的这些目录 → BepInEx 下对应位置。
# 值 = (BepInEx 下的相对目录, 是否按包名再分一层子目录)
_TS_DIRS = {
    "plugins":  ("BepInEx/plugins",  True),
    "patchers": ("BepInEx/patchers", True),
    "monomod":  ("BepInEx/monomod",  True),
    "core":     ("BepInEx/core",     False),
    "config":   ("BepInEx/config",   False),
}


def install_mod(
    archive_path: str,
    game_root: str,
    game_slug: str,
    load_order: int = 0,
) -> dict:
    layout = get_game_layout(game_slug)
    patterns = layout.get("patterns", {})
    result = {"installed": [], "skipped": [], "errors": []}

    if layout.get("handler") == "ff7r":
        return _install_ff7r(archive_path, game_root, game_slug)
    if layout.get("handler") == "stardew_smapi":
        return _install_stardew_smapi(archive_path, game_root, game_slug)

    # 没有 per-game 规则时：走 Thunderstore/BepInEx 通用安装(REPO 等 Unity 游戏)。
    # 由 _install_bepinex 在解压后按真实内容判定:含 BepInEx/ 结构或 plugins/dll 才装,
    # 否则抛"暂不支持",绝不误报安装成功。
    if not patterns:
        return _install_bepinex(archive_path, game_root, game_slug)

    data_dir = os.path.join(game_root, "Data")
    # 只有当该游戏的规则确实会往 Data/ 落文件时才创建,避免给 UE 系游戏凭空造出垃圾 Data 目录
    if any(str(prefix).startswith("Data") for prefix in patterns.values()):
        os.makedirs(data_dir, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        try:
            extract_archive(archive_path, tmp)
        except (FileNotFoundError, RuntimeError):
            raise
        except Exception as e:
            raise RuntimeError(f"解压失败: {e}") from e
        # ── 智能剥壳(见 _strip_wrapper_dirs):剥掉版本号/作者名壳目录,否则路径规则匹配不上;
        #    layout 显式路由的目录名(Mods/SB/Data…)不是壳,不剥 ──
        walk_root = _strip_wrapper_dirs(tmp, keep=_layout_keep_dirs(patterns))
        if walk_root != tmp:
            result.setdefault("notes", []).append(
                f"已自动剥离压缩包顶层目录: {os.path.relpath(walk_root, tmp)}")

        operations = []
        for root, _, files in os.walk(walk_root):
            for f in files:
                full_src = os.path.join(root, f)
                member = os.path.relpath(full_src, walk_root)

                dest = _resolve_dest(member, game_root, patterns, data_dir)
                if dest is None:
                    result["skipped"].append(member)
                    continue

                operations.append({"src": full_src, "dest": dest, "record": {"file": member}})

        result["installed"] = _commit_files_transactionally(operations, game_root, game_slug)

    if layout.get("load_order_file"):
        _update_load_order(game_root, game_slug, layout, load_order)

    return result


def _install_bepinex(archive_path: str, game_root: str, game_slug: str = "") -> dict:
    """Thunderstore/BepInEx 通用安装,遵循 r2modman 默认安装规则:
      · 包含 BepInEx/(BepInExPack 或按 BepInEx 结构打包的 mod)→ 原样合并到游戏根
      · 包根的 plugins/ patchers/ monomod/ → BepInEx/<该目录>/<包名>/(按包名分层)
      · 包根的 core/ config/ → BepInEx/<该目录>/(不分层)
      · 散 .dll / 其它松散文件 → BepInEx/plugins/<包名>/
      · manifest.json / icon.png / README / CHANGELOG / LICENSE 等元数据不安装
    解压后按真实内容判定;无 BepInEx 结构也无 .dll → 抛错,绝不误报成功。"""
    result = {"installed": [], "skipped": [], "errors": []}
    pkg = os.path.splitext(os.path.basename(archive_path))[0]
    pkg = re.sub(r"^(ts|gh|gb)_", "", pkg)            # 去掉来源前缀
    pkg = re.sub(r"[-_]v?\d+([._]\d+)*$", "", pkg)    # 去掉结尾版本号
    pkg = pkg or "mod"
    real_root = os.path.realpath(game_root)

    with tempfile.TemporaryDirectory() as tmp:
        try:
            extract_archive(archive_path, tmp)
        except (FileNotFoundError, RuntimeError):
            raise
        except Exception as e:
            raise RuntimeError(f"解压失败: {e}") from e

        walk_root = _strip_wrapper_dirs(tmp, keep=set(_TS_DIRS) | {"bepinex"})

        # 定位"合并根":walk_root 自身含 BepInEx/,或某个顶层子目录含 BepInEx/
        # (BepInExPack 就是后者:BepInEx/ 藏在 BepInExPack/ 壳里,旁边还有 manifest.json)。
        merge_prefix = None                       # None=非合并模式;""=walk_root 即合并根
        if os.path.isdir(os.path.join(walk_root, "BepInEx")):
            merge_prefix = ""
        else:
            try:
                for entry in os.listdir(walk_root):
                    ep = os.path.join(walk_root, entry)
                    if os.path.isdir(ep) and os.path.isdir(os.path.join(ep, "BepInEx")):
                        merge_prefix = entry.replace("\\", "/") + "/"
                        break
            except OSError:
                pass
        has_bep = merge_prefix is not None

        members = []
        for root, _, files in os.walk(walk_root):
            for f in files:
                members.append(os.path.relpath(os.path.join(root, f), walk_root))

        # 可识别性判定:含 BepInEx/ 结构、或有已知目录、或有 dll,才认为是能装的 mod 包
        def _seg0(m: str) -> str:
            return m.replace("\\", "/").split("/", 1)[0].lower()
        recognizable = has_bep or any(
            _seg0(m) in _TS_DIRS or m.lower().endswith(".dll") for m in members
        )
        if not recognizable:
            raise UnsupportedInstallLayout(
                f"暂不支持该压缩包的自动安装:未发现 BepInEx/plugins 结构或 .dll"
                f"(game_slug={game_slug or '?'})。已停止通用规则，等待根据包内说明"
                "或来源教程生成显式安装映射。",
                archive_members=[
                    member.replace("\\", "/") for member in members
                ],
                install_notes=_read_install_notes_from_tree(walk_root),
            )

        game_has_loader = (
            os.path.isdir(os.path.join(game_root, "BepInEx", "core"))
            or os.path.isfile(os.path.join(game_root, "winhttp.dll"))
            or os.path.isdir(os.path.join(game_root, "BepInEx"))
        )

        def _route(norm: str) -> Optional[str]:
            """把包内相对路径(正斜杠)映射到游戏根下的相对目标;返回 None=不安装。"""
            # 顶层元数据永不安装
            if "/" not in norm and norm.lower() in _TS_META:
                return None
            if has_bep:
                if merge_prefix == "":
                    return norm
                if norm.startswith(merge_prefix):
                    return norm[len(merge_prefix):]              # 剥掉 BepInExPack/ 壳
                return f"BepInEx/plugins/{pkg}/{os.path.basename(norm)}"  # 壳外散文件
            seg0 = norm.split("/", 1)[0].lower()
            if "/" in norm and seg0 in _TS_DIRS:
                subdir, namespaced = _TS_DIRS[seg0]
                tail = norm.split("/", 1)[1]
                return f"{subdir}/{pkg}/{tail}" if namespaced else f"{subdir}/{tail}"
            return f"BepInEx/plugins/{pkg}/{norm}"               # 散 dll 兜底

        operations = []
        for member in members:
            norm = member.replace("\\", "/")
            rel_dest = _route(norm)
            if rel_dest is None:
                result["skipped"].append(member)
                continue

            dest = os.path.normpath(os.path.join(game_root, rel_dest.replace("/", os.sep)))
            try:
                if os.path.commonpath([real_root, os.path.realpath(dest)]) != real_root:
                    result["skipped"].append(member)
                    continue
            except ValueError:
                result["skipped"].append(member)
                continue

            operations.append({
                "src": os.path.join(walk_root, member), "dest": dest,
                "record": {"file": member},
            })

        result["installed"] = _commit_files_transactionally(operations, game_root, game_slug)

        if not has_bep and not game_has_loader:
            result.setdefault("notes", []).append(
                "未检测到 BepInEx 加载器(游戏根无 winhttp.dll / BepInEx/core),"
                "mod 已就位但可能不生效 —— 请先安装 BepInExPack。"
            )
    return result


# 落到游戏根的可执行文件 = 注入器 / 替换官方文件类,合法但需用户确认来源(软告警,不拒绝)
_EXEC_EXTS = (".exe", ".dll", ".asi")


def _validate_custom_target(game_root: str, real_root: str, dst_rel) -> tuple:
    """校验单个自定义落点。返回 (rel|None, reason)。
    rel = 相对 game_root 的正斜杠路径(合法);None = 拒绝(绝对/含../越界)。
    install_mod_custom 与 plan_custom_targets 共用,保证落位校验与登记预解析永不漂移。"""
    dst_clean = str(dst_rel).replace("\\", "/").strip().lstrip("/")
    if not dst_clean or os.path.isabs(str(dst_rel)) or ".." in dst_clean.split("/"):
        return None, f"目标路径非法(绝对/含..): {dst_rel}"
    dest = os.path.normpath(os.path.join(game_root, dst_clean.replace("/", os.sep)))
    try:
        if os.path.commonpath([real_root, os.path.realpath(dest)]) != real_root:
            return None, f"目标越出游戏目录: {dst_rel}"
    except ValueError:
        return None, f"目标路径无法解析: {dst_rel}"
    return os.path.relpath(dest, game_root).replace("\\", "/"), ""


def plan_custom_targets(game_root: str, mapping: dict) -> dict:
    """纯路径预解析(不解压):返回 {valid:[rel...], rejected:[{src,reason}]}。
    tools 层用它在建安装前快照【之前】登记快照域 —— 覆盖类安装的游戏原文件因此
    能被安装前快照纳入保护(顺序颠倒会丢原文件,见 test_custom_domain.py)。"""
    real_root = os.path.realpath(game_root)
    valid, rejected = [], []
    for src_rel, dst_rel in (mapping or {}).items():
        rel, reason = _validate_custom_target(game_root, real_root, dst_rel)
        (valid.append(rel) if rel else rejected.append({"src": src_rel, "reason": reason}))
    return {"valid": valid, "rejected": rejected}


def preview_custom_install(
    archive_path: str,
    game_root: str,
    game_slug: str,
    mapping: dict,
) -> dict:
    """Inspect explicit archive mappings without writing to the game."""
    plan = plan_custom_targets(game_root, mapping)
    real_root = os.path.realpath(game_root)
    installed_files = {
        os.path.normcase(os.path.realpath(path)): owner
        for path, owner in _get_installed_files_map(game_slug).items()
    }
    archive_files = set()
    with tempfile.TemporaryDirectory() as tmp:
        extract_archive(archive_path, tmp)
        walk_root = _strip_wrapper_dirs(tmp)
        for current, _, files in os.walk(walk_root):
            for filename in files:
                archive_files.add(
                    os.path.relpath(
                        os.path.join(current, filename), walk_root,
                    ).replace("\\", "/")
                )

    rejected_by_source = {
        str(item.get("src") or ""): str(item.get("reason") or "")
        for item in plan.get("rejected", [])
    }
    checked = []
    missing_sources = []
    target_conflicts = []
    for src_rel, dst_rel in (mapping or {}).items():
        source = str(src_rel).replace("\\", "/").lstrip("/")
        if source not in archive_files:
            missing_sources.append(source)
            continue
        rel, reason = _validate_custom_target(game_root, real_root, dst_rel)
        if not rel:
            rejected_by_source[source] = reason
            continue
        destination = os.path.normpath(
            os.path.join(game_root, rel.replace("/", os.sep))
        )
        destination_key = os.path.normcase(os.path.realpath(destination))
        owner = installed_files.get(destination_key, "")
        exists = os.path.exists(destination)
        disabled_exists = os.path.exists(destination + ".disabled")
        conflict = None
        if owner:
            conflict = {
                "source": source,
                "target": rel,
                "path": destination,
                "kind": "installed_mod_file",
                "owned_by": owner,
            }
        elif exists or disabled_exists:
            conflict = {
                "source": source,
                "target": rel,
                "path": destination,
                "kind": "unmanaged_existing_file",
                "owned_by": "",
                "disabled_copy": bool(disabled_exists and not exists),
            }
        if conflict:
            target_conflicts.append(conflict)
        checked.append({
            "source": source,
            "target": rel,
            "exists": bool(exists or disabled_exists),
        })

    return {
        "archive_file_count": len(archive_files),
        "mapping_count": len(mapping or {}),
        "checked_mappings": checked,
        "missing_archive_sources": missing_sources,
        "rejected_targets": [
            {"src": source, "reason": reason}
            for source, reason in rejected_by_source.items()
        ],
        "target_conflicts": target_conflicts,
        "safe_to_install": not (
            missing_sources or rejected_by_source or target_conflicts
        ),
    }


def install_mod_custom(archive_path: str, game_root: str, game_slug: str,
                       mapping: dict) -> dict:
    """T2 通用安装:按 agent 产出的显式 mapping(包内相对路径 → 游戏内相对路径)落位。

    mapping 的"包内相对路径"须与 conflict_check 展示的一致 —— 两者用同款单目录剥壳。
    三层校验(用户拍板"软告警放行"):
      ① 硬拒绝(该条 skip):目标是绝对路径 / 含 .. / 越出 game_root(commonpath 守卫)
      ② 源须存在:mapping 的包内路径必须在解压包里,否则 skip
      ③ 软告警(仍安装):覆盖已存在文件、或可执行文件落游戏根(疑似注入器/替换官方文件)
    返回 installed(每项含 rel=相对 game_root 正斜杠,供快照域登记)/skipped/errors/warnings。
    """
    result = {"installed": [], "skipped": [], "errors": [], "warnings": []}
    if not mapping:
        result["skipped"].append({"src": "", "reason": "mapping 为空"})
        return result
    real_root = os.path.realpath(game_root)

    with tempfile.TemporaryDirectory() as tmp:
        try:
            extract_archive(archive_path, tmp)
        except (FileNotFoundError, RuntimeError):
            raise
        except Exception as e:
            raise RuntimeError(f"解压失败: {e}") from e
        walk_root = _strip_wrapper_dirs(tmp)   # 与 conflict_check 同款剥壳,保证包内路径对得上

        operations = []
        for src_rel, dst_rel in mapping.items():
            src_norm = str(src_rel).replace("\\", "/").lstrip("/")
            src_full = os.path.join(walk_root, src_norm.replace("/", os.sep))
            # ② 源存在
            if not os.path.isfile(src_full):
                result["skipped"].append({"src": src_rel, "reason": "包内不存在该文件"})
                continue
            # ① 路径合法性(绝对/../越界)—— 与 plan_custom_targets 同一实现
            rel, reason = _validate_custom_target(game_root, real_root, dst_rel)
            if not rel:
                result["skipped"].append({"src": src_rel, "reason": reason})
                continue
            dest = os.path.normpath(os.path.join(game_root, rel.replace("/", os.sep)))

            # ③ 软告警(不拒绝)。existed 须在 copy2 前捕获 —— 拷完后 dest 必然存在。
            existed = os.path.exists(dest)
            if existed:
                result["warnings"].append(f"覆盖已存在文件: {rel}")
            if os.path.splitext(dest)[1].lower() in _EXEC_EXTS and rel.count("/") == 0:
                result["warnings"].append(
                    f"可执行文件落游戏根: {rel}(疑似注入器/替换官方文件,请确认来源可信)")

            operations.append({
                "src": src_full, "dest": dest,
                "record": {"src": src_rel, "rel": rel, "overwrote": existed},
            })

        try:
            result["installed"] = _commit_files_transactionally(operations, game_root, game_slug)
        except Exception as e:
            entry = {"src": "<transaction>", "error": str(e)}
            if isinstance(e, OSError):
                from .diagnostics import classify_oserror
                entry.update(classify_oserror(e, game_root))
            result["errors"].append(entry)

    return result


def _resolve_dest(filename: str, game_root: str, patterns: dict, data_dir: str) -> Optional[str]:
    for pattern, prefix in patterns.items():
        if re.search(pattern, filename, re.IGNORECASE):
            rel = filename
            if prefix in ("Data/",) and (rel.lower().startswith("data/") or rel.lower().startswith("data\\")):
                rel = rel[5:]
            if prefix in ("meshes/", "textures/", "scripts/") and (rel.lower().startswith(f"data/{prefix.lower()}")):
                rel = rel[5:]
            clean = rel.replace("\\", "/")
            if prefix:
                # 扁平化目标(UE 的 ~mods、MelonLoader 的 Mods 都只认目录根):
                # 取 basename,避免 zip 内嵌套目录导致路径叠加/加载器扫不到
                if prefix.endswith(("~mods/", "Mods/")):
                    clean = os.path.basename(clean)
                clean = f"{prefix}{clean}"
            dest = os.path.normpath(os.path.join(game_root, clean.replace("/", os.sep)))
            real_root = os.path.realpath(game_root)
            real_dest = os.path.realpath(dest)
            try:
                if os.path.commonpath([real_root, real_dest]) != real_root:
                    return None
            except ValueError:
                return None
            return dest
    return None


def _update_load_order(game_root: str, game_slug: str, layout: dict, load_order: int):
    if game_slug != "skyrimspecialedition":
        return

    local_appdata = os.environ.get("LOCALAPPDATA", os.path.expanduser("~/AppData/Local"))
    plugins_dir = os.path.join(local_appdata, layout.get("load_order_subpath", ""))
    plugins_file = os.path.join(plugins_dir, layout.get("load_order_file", "plugins.txt"))

    if not os.path.exists(plugins_dir):
        os.makedirs(plugins_dir, exist_ok=True)

    existing = {}
    if os.path.exists(plugins_file):
        with open(plugins_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("*"):
                    existing[line[1:]] = True
                elif line:
                    existing[line] = False

    with open(plugins_file, "w", encoding="utf-8") as f:
        for plugin, active in existing.items():
            f.write(f"{'*' if active else ''}{plugin}\n")

    return plugins_file


def read_readme_zip(archive_path: str) -> str:
    with tempfile.TemporaryDirectory() as tmp:
        extract_archive(archive_path, tmp)
        return _read_install_notes_from_tree(tmp)


def uninstall_mod(mod_id: str, game_root: str, files_installed: list[str],
                  game_slug: str = "", shared_files: set = None) -> dict:
    """卸载 mod。
    shared_files: 被其他已装 mod 也拥有的文件(绝对路径、normcase)。这些文件只从本 mod
                  记录移除,【绝不删磁盘】,防止卸载 A 时删掉 B 依赖的共享文件
                  (根因修复:UE4SS 与 CNS 共享 UE4SS-settings.ini 的互删事故)。
    """
    result = {
        "removed": [], "kept_shared": [], "not_found": [],
        "blocked_unsafe": [], "errors": [],
    }
    shared = shared_files or set()

    for f in files_installed:
        managed_path, unsafe_reason = resolve_managed_game_path(f, game_root)
        if not managed_path:
            result["blocked_unsafe"].append({
                "file": str(f), "reason": unsafe_reason,
            })
            continue
        f = managed_path

        # ── 共享文件保护:仍被其他 mod 拥有 → 不动磁盘 ──
        if os.path.normcase(os.path.abspath(f)) in shared:
            result["kept_shared"].append(f)
            continue

        backup = _backup_lookup(f, game_root, game_slug)
        if os.path.exists(f):
            try:
                os.remove(f)
                result["removed"].append(f)
            except Exception as e:
                result["errors"].append({"file": f, "error": str(e)})
        elif backup:
            # 文件已不在,备份成了孤儿账 → 清掉
            try:
                os.remove(backup)
                result["removed"].append(backup)
                backup = ""
            except Exception as e:
                result["errors"].append({"file": f, "error": str(e)})
        else:
            result["not_found"].append(f)

        # 卸载后把被覆盖的原文件还原回去。
        # 注意用 shutil.move 而非 os.rename:集中备份区在 C 盘,游戏可能在其他盘,跨设备 rename 会炸。
        if backup and os.path.exists(backup):
            try:
                shutil.move(backup, f)
                result.setdefault("restored_original", []).append(f)
            except Exception:
                pass

    return result


def conflict_check(archive_path: str, game_root: str, game_slug: str) -> dict:
    layout = get_game_layout(game_slug)
    patterns = layout.get("patterns", {})

    # 先无条件列出压缩包内容(即使没有安装规则、或结构特殊导致匹配不上,
    # 也让调用方能"透视"包内文件,不必要求用户手动解压查看)
    archive_contents = []
    incoming_files = []
    strip_note = None
    try:
        with tempfile.TemporaryDirectory() as tmp:
            extract_archive(archive_path, tmp)
            # 智能剥壳:单一顶层目录(GitHub 版本号壳等)剥掉再匹配
            walk_root = tmp
            while True:
                ents = [e for e in os.listdir(walk_root) if e.lower() != "__macosx"]
                if len(ents) == 1 and os.path.isdir(os.path.join(walk_root, ents[0])):
                    walk_root = os.path.join(walk_root, ents[0])
                else:
                    break
            if walk_root != tmp:
                strip_note = os.path.relpath(walk_root, tmp)
            for root, _, files in os.walk(walk_root):
                for f in files:
                    member = os.path.relpath(os.path.join(root, f), walk_root)
                    archive_contents.append(member.replace("\\", "/"))
                    if patterns:
                        dest = _resolve_dest(member, game_root, patterns,
                                             os.path.join(game_root, "Data"))
                        if dest:
                            incoming_files.append(dest)
    except Exception as e:
        return {
            "conflicts": [], "missing_deps": [], "incoming_files_count": 0,
            "archive_contents": [], "safe_to_install": False,
            "error": f"无法读取压缩包内容: {e}",
        }

    if layout.get("handler") == "ff7r":
        plugin_roots = {
            m.split("/", 1)[0].lower()
            for m in archive_contents if m.lower().endswith(".uplugin") and "/" in m
        }
        incoming_files = [d for d in (
            _ff7r_dest(member, plugin_roots, game_root) for member in archive_contents
        ) if d]

    if not patterns:
        return {
            "conflicts": [], "missing_deps": [], "incoming_files_count": 0,
            "archive_contents": archive_contents[:200],
            "archive_file_count": len(archive_contents),
            "stripped_top_dir": strip_note,
            "safe_to_install": False,
            "warning": f"暂不支持游戏 '{game_slug}' 的安装路径规则,无法判断落位;"
                       f"但已列出包内 {len(archive_contents)} 个文件供参考(见 archive_contents)。",
        }

    installed_mods = _get_installed_files_map(game_slug)
    conflicts = [{"file": f, "owned_by": installed_mods[f]}
                 for f in incoming_files if f in installed_mods]

    return {
        "conflicts": conflicts,
        "missing_deps": [],
        "incoming_files_count": len(incoming_files),
        "archive_contents": archive_contents[:200],
        "archive_file_count": len(archive_contents),
        "stripped_top_dir": strip_note,
        "safe_to_install": len(conflicts) == 0,
    }


def _get_installed_files_map(game_slug: str = "") -> dict[str, str]:
    result = {}
    try:
        from . import db
        mods = db.get_installed_mods(game_slug)
        for m in mods:
            files = json.loads(m.files_installed) if isinstance(m.files_installed, str) else (m.files_installed or [])
            for f in files:
                result[f] = m.name
    except Exception:
        pass
    return result


def disable_mod(files_installed: list[str], game_root: str) -> dict:
    """禁用 mod：重命名文件加 .disabled 后缀"""
    result = {
        "disabled": [], "changed": [], "not_found": [],
        "blocked_unsafe": [], "errors": [],
    }
    for f in files_installed:
        managed_path, unsafe_reason = resolve_managed_game_path(f, game_root)
        if not managed_path:
            result["blocked_unsafe"].append({
                "file": str(f), "reason": unsafe_reason,
            })
            continue
        f = managed_path
        if os.path.exists(f):
            try:
                os.rename(f, f + ".disabled")
                result["disabled"].append(f)
                result["changed"].append(f)
            except Exception as e:
                result["errors"].append({"file": f, "error": str(e)})
        elif os.path.exists(f + ".disabled"):
            result["disabled"].append(f)
        else:
            result["not_found"].append(f)
    return result


def is_mod_disabled(files_installed: list[str]) -> bool:
    """Derive disabled state from disk while keeping original paths in the ledger."""
    if not files_installed:
        return False
    for tracked in files_installed:
        original = tracked[:-9] if tracked.endswith(".disabled") else tracked
        if os.path.exists(original) or not os.path.exists(original + ".disabled"):
            return False
    return True


def enable_mod(files_installed: list[str], game_root: str) -> dict:
    """启用 mod：去掉 .disabled 后缀"""
    result = {
        "enabled": [], "changed": [], "not_found": [],
        "blocked_unsafe": [], "errors": [],
    }
    for f in files_installed:
        managed_path, unsafe_reason = resolve_managed_game_path(f, game_root)
        if not managed_path:
            result["blocked_unsafe"].append({
                "file": str(f), "reason": unsafe_reason,
            })
            continue
        f = managed_path
        target = f + ".disabled" if not f.endswith(".disabled") else f
        original = f.replace(".disabled", "") if f.endswith(".disabled") else f
        if os.path.exists(target):
            try:
                os.rename(target, original)
                result["enabled"].append(original)
                result["changed"].append(original)
            except Exception as e:
                result["errors"].append({"file": f, "error": str(e)})
        elif os.path.exists(original):
            result["enabled"].append(original)
        else:
            result["not_found"].append(f)
    return result
