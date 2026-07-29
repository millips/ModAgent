import os
import re
import json
from . import db
from . import nexus

GAME_MOD_PATHS = {
    "cyberpunk2077": [
        ("archive/pc/mod/", ".archive"),
        ("bin/x64/plugins/", ".dll"),
        ("bin/x64/plugins/", ".asi"),
        ("bin/x64/plugins/cyber_engine_tweaks/mods/", ".lua"),
        ("red4ext/plugins/", ".dll"),
        ("r6/scripts/", ".reds"),
        ("r6/tweaks/", ".yaml"),
        ("r6/tweaks/", ".yml"),
    ],
    "skyrimspecialedition": [
        ("Data/", ".esp"),
        ("Data/", ".esm"),
        ("Data/", ".esl"),
        ("Data/SKSE/Plugins/", ".dll"),
    ],
    "fallout4": [
        ("Data/", ".esp"),
        ("Data/", ".esm"),
        ("Data/", ".esl"),
    ],
    "stellarblade": [
        ("SB/Content/Paks/~mods/", ".pak"),
        ("SB/Content/Paks/~mods/", ".ucas"),
        ("SB/Content/Paks/~mods/", ".utoc"),
        ("SB/Content/Paks/LogicMods/", ".pak"),
        ("SB/Content/Paks/LogicMods/", ".ucas"),
        ("SB/Content/Paks/LogicMods/", ".utoc"),
        ("SB/Content/Paks/mods/", ".pak"),
        ("SB/Content/Paks/mods/", ".ucas"),
        ("SB/Content/Paks/mods/", ".utoc"),
    ],
}

EXTERNAL_MOD_EXTENSIONS = {
    ".archive", ".pak", ".ucas", ".utoc", ".dll", ".asi", ".reds",
    ".yaml", ".yml", ".lua", ".esp", ".esm", ".esl", ".zip", ".7z", ".rar",
}

WELL_KNOWN_CP77 = {
    "cyber_engine_tweaks": "Cyber Engine Tweaks",
    "CET": "Cyber Engine Tweaks",
    "redscript": "redscript",
    "RED4ext": "RED4ext",
    "ArchiveXL": "ArchiveXL",
    "TweakXL": "TweakXL",
    "Codeware": "Codeware",
    "Input Loader": "Input Loader",
    "Mod Settings": "Mod Settings",
    "Native Settings UI": "Native Settings UI",
    "Equipment-EX": "Equipment-EX",
    "EquipmentEx": "Equipment-EX",
    "Virtual Atelier": "Virtual Atelier",
    "VirtualAtelier": "Virtual Atelier",
    "ACU": "Appearance Creator Unity",
    "AMM": "Appearance Menu Mod",
    "Appearance Menu Mod": "Appearance Menu Mod",
    "Berserk Unbound": "Berserk Unbound",
    "EBB": "EBB Body",
    "EBB Body": "EBB Body",
    "VTK": "VTK HD Body",
    "VTK Vanilla HD": "VTK HD Body",
    "vtk_VanillaHD": "VTK HD Body",
    "ANGEL": "ANGEL Body",
    "ANGEL Body": "ANGEL Body",
    "Peachu": "Peachu Tech Set",
    "XRX": "XRX Stockings",
    "XRX_Stockings": "XRX Stockings",
    "Hyst": "Hyst Angel Body",
    "Hyst_Angel": "Hyst Angel Body",
    "Atomiic EVE": "Atomiic EVE",
    "Atomiic_EVE": "Atomiic EVE",
    "hair_profiles_ccxl": "Hair Profiles CCXL",
    "id_hair_profiles": "Hair Profiles CCXL",
    "xBaebsae_VanillaHD": "Vanilla HD Refits",
    "xBaebsae": "Vanilla HD Refits",
    "BOOTY": "BOOTY Netrunner Suit",
    "BOOTY_defaultNetrunnerSuit": "BOOTY Netrunner Suit",
    "NovaLUT": "NovaLUT",
}


# 通用 mod 加载器目录（不依赖具体游戏名，自动识别）
GENERIC_LOADER_DIRS = [
    "BepInEx/plugins",     # BepInEx: REPO / Lethal Company / Valheim / 雨中冒险2 等一大类
    "BepInEx/patchers",
    "Mods",                # MelonLoader / 通用
    "mods",
]
_LOADER_SKIP = {"mmhook", "cache", "core", "config", "logs"}


def _parse_loader_name(folder: str):
    """Thunderstore 命名 Author-Package-Version → (Package, Version)。"""
    m = re.match(r"^(.+?)-(.+?)-(\d+[\d.]*)$", folder)
    if m:
        return m.group(2).replace("_", " "), m.group(3)
    return folder, "unknown"


def _file_signature(files) -> tuple[str, ...]:
    return tuple(sorted({
        os.path.normcase(os.path.realpath(os.path.abspath(str(path))))
        for path in (files or []) if str(path or "").strip()
    }))


def _stored_files(value) -> list:
    try:
        parsed = json.loads(value) if isinstance(value, str) else (value or [])
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    return parsed if isinstance(parsed, list) else []


def _scan_generic_loaders(game_root: str) -> list:
    """探测通用加载器目录，每个子文件夹 / 松散 .dll 视为一个 mod（不依赖游戏名）。"""
    results = []
    for rel in GENERIC_LOADER_DIRS:
        base = os.path.join(game_root, rel.replace("/", os.sep))
        if not os.path.isdir(base):
            continue
        try:
            entries = os.listdir(base)
        except PermissionError:
            continue
        for entry in entries:
            full = os.path.join(base, entry)
            if os.path.isdir(full):
                if entry.lower() in _LOADER_SKIP:
                    continue
                files = [os.path.join(r, f) for r, _, fs in os.walk(full) for f in fs]
                if not files:
                    continue
                name, ver = _parse_loader_name(entry)
                results.append({"name": name, "version": ver, "files": files, "filenames": [entry]})
            elif os.path.isfile(full) and entry.lower().endswith((".dll",)):
                name, ver = _parse_loader_name(os.path.splitext(entry)[0])
                results.append({"name": name, "version": ver, "files": [full], "filenames": [entry]})
    return results


def _scan_steam_workshop(game_root: str) -> list:
    """探测 Steam 创意工坊目录（在 game_root 之外）：每个 <workshop_id> 文件夹 = 一个 mod，批量查标题。"""
    try:
        from .sources import steam_workshop as sw
    except Exception:
        return []
    appid = sw.resolve_appid(game_root)
    if not appid:
        return []
    wc = sw.workshop_content_dir(game_root, appid)
    if not os.path.isdir(wc):
        return []
    items, ids = [], []
    for entry in os.listdir(wc):
        full = os.path.join(wc, entry)
        if os.path.isdir(full) and entry.isdigit() and any(os.scandir(full)):
            items.append((entry, full))
            ids.append(entry)
    # 命名源优先级(证据分级:本地 > 网络):Info.json 的 ModName(UE4SS/PalSchema 生态离线
    # 100% 可靠)> Steam get_titles(公开 API,但瞬态不稳,一失败就落占位名固化)> 占位。
    titles = sw.get_titles(ids) if ids else {}
    out = []
    for wid, full in items:
        lname, lver = _workshop_local_meta(full)
        name = lname or titles.get(wid) or f"Workshop {wid}"
        # 工坊由 Steam 托管、卸载=取消订阅，DB 只存文件夹路径即可（不存上千个文件）
        out.append({
            "id": "ws_" + wid,
            "name": name,
            "files": [full], "filenames": [wid], "version": lver,
        })
    return out


def _workshop_local_meta(mod_dir: str) -> tuple:
    """读工坊 mod 目录里的 Info.json 拿 (ModName, Version)。UE4SS/PalSchema 生态的工坊 mod
    都带它,离线可靠、还含作用线索(Tags);读不到返回 ('', '')。"""
    try:
        p = os.path.join(mod_dir, "Info.json")
        if os.path.isfile(p):
            with open(p, encoding="utf-8") as f:
                d = json.load(f)
            return (d.get("ModName") or "").strip(), (str(d.get("Version") or "")).strip()
    except Exception:
        pass
    return "", ""


def _scan_external_mod_root(root: str) -> list[dict]:
    """Group a Vortex/MO2/Fluffy/custom directory by top-level entry."""
    root = os.path.abspath(os.path.expanduser(root or ""))
    if not os.path.isdir(root):
        return []
    try:
        entries = list(os.scandir(root))
    except (OSError, PermissionError):
        return []
    results = []
    for entry in entries:
        if entry.name.lower() in _LOADER_SKIP or entry.name.startswith("."):
            continue
        if entry.is_dir(follow_symlinks=False):
            files = [
                os.path.join(base, filename)
                for base, _, filenames in os.walk(entry.path)
                for filename in filenames
                if os.path.splitext(filename)[1].lower() in EXTERNAL_MOD_EXTENSIONS
            ]
            if files:
                name, version = _parse_loader_name(entry.name)
                results.append({
                    "name": name, "version": version, "files": files,
                    "filenames": [os.path.basename(item) for item in files],
                    "source_root": root,
                })
        elif entry.is_file() and os.path.splitext(entry.name)[1].lower() in EXTERNAL_MOD_EXTENSIONS:
            name, version = _parse_loader_name(os.path.splitext(entry.name)[0])
            results.append({
                "name": name, "version": version, "files": [entry.path],
                "filenames": [entry.name], "source_root": root,
            })
    return results


def scan_existing_mods(game_root: str, game_slug: str, api_key: str,
                       extra_roots: list[str] | None = None,
                       game_instance_id: str = "") -> dict:
    storage_id = game_instance_id or game_slug
    # Heal historical aliases before comparing a fresh disk scan with the
    # inventory.  Some older flows recorded the upstream row and then imported
    # the package-directory name (for example MoneyValueTracker and
    # 39_MoneyValueTracker) as a second row even though both owned the exact
    # same DLL.  This is metadata-only: game files are never removed here.
    db.merge_duplicate_inventory_rows(storage_id)
    identified = []
    unidentified = []
    detected = 0
    existing_mods = db.get_installed_mods(storage_id)
    existing_names = {m.name.lower() for m in existing_mods}
    existing_file_signatures = {
        signature
        for mod in existing_mods
        if (signature := _file_signature(
            _stored_files(mod.files_installed)
        ))
    }
    existing_owned_file_sets = [frozenset(item) for item in existing_file_signatures]

    def already_owned_by_package(signature) -> bool:
        """True when every scanned file already belongs to one package row."""
        candidate = frozenset(signature or ())
        return bool(candidate) and any(
            candidate <= owned for owned in existing_owned_file_sets
        )
    scanned_roots = [os.path.abspath(game_root)] if game_root else []
    missing_roots = []
    manifest_roots: set[str] = set()

    # Prefer authoritative local metadata over folder-name guessing. SMAPI
    # manifests are offline, fast, and prove the version on this machine.
    if game_slug == "stardewvalley" and game_root:
        try:
            from . import stardew
            for item in stardew.installed_manifests(game_root):
                mod_dir = os.path.realpath(os.path.join(
                    game_root, item.get("relative_dir") or ""
                ))
                if not os.path.isdir(mod_dir):
                    continue
                files = [
                    os.path.join(current, filename)
                    for current, _, filenames in os.walk(mod_dir)
                    for filename in filenames
                ]
                if not files:
                    continue
                signature = _file_signature(files)
                if signature and signature in existing_file_signatures:
                    continue
                manifest_roots.add(os.path.normcase(mod_dir))
                detected += 1
                name = str(item.get("name") or item.get("unique_id") or "").strip()
                if not name or name.lower() in existing_names:
                    continue
                identified.append({
                    "mod_id": "",
                    "name": name,
                    "version": str(item.get("version") or "unknown"),
                    "files": files,
                    "filenames": [os.path.basename(mod_dir)],
                    "endorsements": 0,
                    "confidence": "local_manifest",
                    "local_unique_id": str(item.get("unique_id") or ""),
                    "game_slug": storage_id,
                })
                existing_names.add(name.lower())
                existing_file_signatures.add(signature)
        except Exception:
            # A malformed third-party manifest must not suppress generic scan.
            manifest_roots.clear()

    # 0) 通用加载器探测（BepInEx/MelonLoader 等，文件夹式 mod，不依赖游戏名）
    for g in _scan_generic_loaders(game_root):
        if manifest_roots and any(
            any(
                os.path.commonpath([
                    os.path.normcase(os.path.realpath(path)), manifest_root
                ]) == manifest_root
                for manifest_root in manifest_roots
            )
            for path in g.get("files") or []
        ):
            continue
        detected += 1
        signature = _file_signature(g.get("files"))
        if already_owned_by_package(signature):
            continue
        if g["name"].lower() in existing_names:
            continue
        identified.append({
            "mod_id": "", "name": g["name"], "version": g["version"],
            "files": g["files"], "filenames": g["filenames"],
            "endorsements": 0, "confidence": "local", "game_slug": storage_id,
        })
        existing_names.add(g["name"].lower())
        existing_file_signatures.add(signature)
        existing_owned_file_sets.append(frozenset(signature))

    # 0.5) Steam 创意工坊探测（文件在 game_root 之外的 workshop 目录，已订阅的 mod）
    for w in _scan_steam_workshop(game_root):
        detected += 1
        signature = _file_signature(w.get("files"))
        if already_owned_by_package(signature):
            continue
        if w["name"].lower() in existing_names:
            continue
        identified.append({
            "mod_id": w["id"], "name": w["name"], "version": w["version"],
            "files": w["files"], "filenames": w["filenames"],
            "endorsements": 0, "confidence": "steam_workshop", "game_slug": storage_id,
        })
        existing_names.add(w["name"].lower())
        existing_file_signatures.add(signature)
        existing_owned_file_sets.append(frozenset(signature))

    # 0.75) Explicit manager/custom directories. MO2 virtual mods, purged
    # Vortex staging and Fluffy libraries are not necessarily visible below
    # the game root, so they must be supplied and remembered explicitly.
    for extra_root in dict.fromkeys(extra_roots or []):
        normalized = os.path.abspath(os.path.expanduser(extra_root or ""))
        if not os.path.isdir(normalized):
            missing_roots.append(normalized)
            continue
        scanned_roots.append(normalized)
        for item in _scan_external_mod_root(normalized):
            detected += 1
            signature = _file_signature(item.get("files"))
            if already_owned_by_package(signature):
                continue
            key = item["name"].lower()
            if key in existing_names:
                continue
            identified.append({
                "mod_id": "", "name": item["name"], "version": item["version"],
                "files": item["files"], "filenames": item["filenames"],
                "endorsements": 0, "confidence": "external_directory",
                "game_slug": storage_id, "source_root": item["source_root"],
            })
            existing_names.add(key)
            existing_file_signatures.add(signature)
            existing_owned_file_sets.append(frozenset(signature))

    # 没有该游戏的 Nexus 文件规则就到此为止（BepInEx 类游戏走通用探测即可）
    if game_slug not in GAME_MOD_PATHS:
        return {"detected": detected, "identified": identified, "unidentified": unidentified,
                "scanned_roots": scanned_roots, "missing_roots": missing_roots}

    patterns = GAME_MOD_PATHS.get(game_slug, [("", ".zip")])
    found_files = _scan_dirs(game_root, patterns)
    detected += len(found_files)

    if not found_files:
        return {"detected": detected, "identified": identified, "unidentified": unidentified,
                "scanned_roots": scanned_roots, "missing_roots": missing_roots}

    # Group files by guessed mod name
    groups: dict[str, list[tuple[str, str, str]]] = {}
    for rel_path, filename in found_files:
        candidate = _guess_mod_name(filename, game_slug)
        wk = identify_well_known(filename, game_slug)
        name = wk["name"] if wk else candidate
        if name not in groups:
            groups[name] = []
        groups[name].append((rel_path, filename, wk["confidence"] if wk else ""))

    for name, files in groups.items():
        if name.lower() in existing_names:
            continue
        full_paths = [os.path.join(game_root, f[0]) for f in files]
        signature = _file_signature(full_paths)
        if already_owned_by_package(signature):
            continue
        filenames = [f[1] for f in files]
        confidence = files[0][2] or "unknown"

        wk = next((identify_well_known(fn, game_slug) for _, fn, _ in files if identify_well_known(fn, game_slug)), None)
        if wk:
            identified.append({
                "mod_id": "", "name": wk["name"], "files": full_paths, "filenames": filenames,
                "endorsements": 0, "confidence": "well_known", "game_slug": storage_id,
            })
            existing_names.add(wk["name"].lower())
            existing_file_signatures.add(signature)
            existing_owned_file_sets.append(frozenset(signature))
            continue

        # Inventory is deliberately offline. Network matching here multiplied
        # one scan into hundreds of CDP/API calls and caused large libraries to
        # time out before anything reached the database. Source alignment is a
        # separate, retryable phase and never controls whether a local file is
        # acknowledged as installed.
        identified.append({
            "mod_id": "", "name": name, "version": "unknown",
            "files": full_paths, "filenames": filenames,
            "endorsements": 0, "confidence": "local_unverified",
            "game_slug": storage_id,
        })
        existing_names.add(name.lower())
        existing_file_signatures.add(signature)
        existing_owned_file_sets.append(frozenset(signature))

    return {"detected": detected, "identified": identified, "unidentified": unidentified,
            "scanned_roots": scanned_roots, "missing_roots": missing_roots}


def import_mods(mods_to_import: list[dict]) -> int:
    import hashlib
    count = 0
    pending = []
    existing_names_by_game: dict[str, set[str]] = {}
    existing_files_by_game: dict[str, set[tuple[str, ...]]] = {}
    for m in mods_to_import:
        game_slug = str(m.get("game_slug") or "")
        if game_slug not in existing_names_by_game:
            installed = db.get_installed_mods(game_slug)
            existing_names_by_game[game_slug] = {
                item.name.lower() for item in installed
            }
            existing_files_by_game[game_slug] = {
                signature
                for item in installed
                if (signature := _file_signature(
                    _stored_files(item.files_installed)
                ))
            }
        existing_names = existing_names_by_game[game_slug]
        existing_files = existing_files_by_game[game_slug]
        signature = _file_signature(m.get("files"))
        # Import is a second safety boundary.  Even if a caller bypasses the
        # normal scanner, never turn files already owned by one installed
        # package into separate variant Mods.
        if signature and any(
            set(signature) <= set(owner_signature)
            for owner_signature in existing_files
        ):
            continue
        if m["name"].lower() in existing_names:
            continue
        mod_id = str(m.get("mod_id") or "")
        if not mod_id:
            mod_id = "local_" + hashlib.md5(m["name"].encode()).hexdigest()[:8]
        files = m.get("files", [])
        mod = db.InstalledMod(
            id=mod_id,
            name=m["name"],
            version=m.get("version", "unknown"),
            snapshot_id="",
            load_order=db.get_max_load_order(game_slug) + 1 + count,
            file_id=m.get("file_id", 0),
            files_installed=json.dumps(files),
            installed_by="imported",
            game_slug=game_slug,
        )
        pending.append(mod)
        existing_names.add(m["name"].lower())
        existing_files.add(signature)
        count += 1
    db.add_mods(pending)
    return count


def _scan_dirs(game_root: str, patterns: list[tuple[str, str]]) -> list[tuple[str, str]]:
    found = []
    seen = set()
    for subdir, ext in patterns:
        full = os.path.join(game_root, subdir)
        if not os.path.isdir(full):
            continue
        try:
            for base, _, filenames in os.walk(full):
                for f in filenames:
                    fp = os.path.join(base, f)
                    if f.lower().endswith(ext.lower()):
                        rel = os.path.relpath(fp, game_root)
                        key = os.path.normcase(os.path.abspath(fp))
                        if key not in seen:
                            seen.add(key)
                            found.append((rel, f))
        except PermissionError:
            continue
    return found


def _guess_mod_name(filename: str, game_slug: str) -> str:
    name = os.path.splitext(filename)[0]
    name_lower = name.lower()

    if game_slug == "cyberpunk2077":
        name_clean = re.sub(r"[_\-\.\d\s]", "", name_lower)
        for key, full_name in WELL_KNOWN_CP77.items():
            key_clean = re.sub(r"[_\-\.\s\d]", "", key.lower())
            if len(key_clean) <= 4:
                if key_clean == name_clean:
                    return full_name
            else:
                if key_clean in name_clean:
                    return full_name

    clean = re.sub(r"[_\.\-]+", " ", name)
    clean = re.sub(r"^#+\s*", "", clean)
    clean = re.sub(r"\b(v\d+[\d\.]*)\b", "", clean, flags=re.IGNORECASE)
    clean = re.sub(r"\s{2,}", " ", clean).strip()

    if not clean:
        clean = name

    return clean[:60]


def _verify_on_nexus(candidate: str, game_slug: str, api_key: str) -> dict | None:
    try:
        results = nexus.search(candidate, game_slug, api_key)
        if not results:
            return None

        best = results[0]
        name_lower = best.get("name", "").lower()
        cand_lower = candidate.lower().replace(" ", "").replace("_", "").replace("-", "")

        name_stripped = name_lower.replace(" ", "").replace("_", "").replace("-", "")
        if cand_lower in name_stripped or name_stripped in cand_lower:
            return {"mod_id": best.get("mod_id"), "name": best.get("name"),
                    "endorsements": best.get("endorsement_count", 0), "confidence": "high"}

        for r in results[:5]:
            n = r.get("name", "").lower()
            n_stripped = n.replace(" ", "").replace("_", "").replace("-", "")
            if any(w in n_stripped for w in cand_lower.split() if len(w) > 2):
                return {"mod_id": r.get("mod_id"), "name": r.get("name"),
                        "endorsements": r.get("endorsement_count", 0), "confidence": "medium"}

        return {"mod_id": best.get("mod_id"), "name": best.get("name"),
                "endorsements": best.get("endorsement_count", 0), "confidence": "low"}

    except Exception:
        return None


def identify_well_known(filename: str, game_slug: str) -> dict | None:
    name = os.path.splitext(filename)[0]
    name_clean = re.sub(r"[_\-\d\s]", "", name.lower())

    if game_slug == "cyberpunk2077":
        for key, full_name in WELL_KNOWN_CP77.items():
            key_clean = re.sub(r"[_\-\d\s]", "", key.lower())
            if len(key_clean) <= 4:
                if key_clean == name_clean:
                    return {"name": full_name, "confidence": "well_known"}
            else:
                if key_clean in name_clean:
                    return {"name": full_name, "confidence": "well_known"}
    return None
