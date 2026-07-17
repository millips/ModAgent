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
    ],
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


def scan_existing_mods(game_root: str, game_slug: str, api_key: str) -> dict:
    identified = []
    unidentified = []
    detected = 0
    existing_names = {m.name.lower() for m in db.get_installed_mods(game_slug)}

    # 0) 通用加载器探测（BepInEx/MelonLoader 等，文件夹式 mod，不依赖游戏名）
    for g in _scan_generic_loaders(game_root):
        detected += 1
        if g["name"].lower() in existing_names:
            continue
        identified.append({
            "mod_id": "", "name": g["name"], "version": g["version"],
            "files": g["files"], "filenames": g["filenames"],
            "endorsements": 0, "confidence": "local", "game_slug": game_slug,
        })
        existing_names.add(g["name"].lower())

    # 0.5) Steam 创意工坊探测（文件在 game_root 之外的 workshop 目录，已订阅的 mod）
    for w in _scan_steam_workshop(game_root):
        detected += 1
        if w["name"].lower() in existing_names:
            continue
        identified.append({
            "mod_id": w["id"], "name": w["name"], "version": w["version"],
            "files": w["files"], "filenames": w["filenames"],
            "endorsements": 0, "confidence": "steam_workshop", "game_slug": game_slug,
        })
        existing_names.add(w["name"].lower())

    # 没有该游戏的 Nexus 文件规则就到此为止（BepInEx 类游戏走通用探测即可）
    if game_slug not in GAME_MOD_PATHS:
        return {"detected": detected, "identified": identified, "unidentified": unidentified}

    patterns = GAME_MOD_PATHS.get(game_slug, [("", ".zip")])
    found_files = _scan_dirs(game_root, patterns)
    detected += len(found_files)

    if not found_files:
        return {"detected": detected, "identified": identified, "unidentified": unidentified}

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
        full_paths = [os.path.join(game_root, f[0]) for f in files]
        filenames = [f[1] for f in files]
        confidence = files[0][2] or "unknown"

        wk = next((identify_well_known(fn, game_slug) for _, fn, _ in files if identify_well_known(fn, game_slug)), None)
        if wk:
            identified.append({
                "mod_id": "", "name": wk["name"], "files": full_paths, "filenames": filenames,
                "endorsements": 0, "confidence": "well_known", "game_slug": game_slug,
            })
            continue

        match = _verify_on_nexus(name, game_slug, api_key)
        if match:
            mod_id = str(match["mod_id"])
            existing = db.get_mod(mod_id, game_slug)
            if existing:
                continue
            identified.append({
                "mod_id": mod_id, "name": match["name"], "files": full_paths, "filenames": filenames,
                "nexus_name": match["name"], "endorsements": match.get("endorsements", 0),
                "confidence": match.get("confidence", "medium"), "game_slug": game_slug,
            })
        else:
            unidentified.append({"files": full_paths, "filenames": filenames, "guess": name})

    return {"detected": detected, "identified": identified, "unidentified": unidentified}


def import_mods(mods_to_import: list[dict]) -> int:
    import hashlib
    count = 0
    existing = db.get_installed_mods()
    existing_names = {m.name.lower() for m in existing}
    for m in mods_to_import:
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
            game_slug=m.get("game_slug", ""),
        )
        db.add_mod(mod)
        existing_names.add(m["name"].lower())
        count += 1
    return count


def _scan_dirs(game_root: str, patterns: list[tuple[str, str]]) -> list[tuple[str, str]]:
    found = []
    seen = set()
    for subdir, ext in patterns:
        full = os.path.join(game_root, subdir)
        if not os.path.isdir(full):
            continue
        try:
            for f in os.listdir(full):
                fp = os.path.join(full, f)
                if os.path.isfile(fp) and f.lower().endswith(ext.lower()):
                    rel = os.path.join(subdir, f)
                    if rel not in seen:
                        seen.add(rel)
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
    clean = re.sub(r"^[#\d\s]+", "", clean)
    clean = re.sub(r"\b(v\d+[\d\.]*)\b", "", clean, flags=re.IGNORECASE)
    clean = re.sub(r"\b(\d+[\d\.]*k?)\b", "", clean)
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
