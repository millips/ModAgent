import os
import json
import re

NEXUS_GAME_MAP = {
    "Skyrim Special Edition": ("skyrimspecialedition", 1704),
    "SkyrimSE": ("skyrimspecialedition", 1704),
    "skyrim special edition": ("skyrimspecialedition", 1704),
    "Cyberpunk 2077": ("cyberpunk2077", 3333),
    "cyberpunk 2077": ("cyberpunk2077", 3333),
    "Fallout 4": ("fallout4", 1151),
    "Fallout4": ("fallout4", 1151),
    "The Witcher 3": ("thewitcher3", 952),
    "The Witcher 3 Wild Hunt": ("thewitcher3", 952),
    "Baldur's Gate 3": ("baldursgate3", 3474),
    "Baldurs Gate 3": ("baldursgate3", 3474),
    "Starfield": ("starfield", 4187),
    "Red Dead Redemption 2": ("reddeadredemption2", 3729),
    "Elden Ring": ("eldenring", 4281),
    "ELDEN RING": ("eldenring", 4281),
    "Monster Hunter World": ("monsterhunterworld", 2531),
    "Monster Hunter Rise": ("monsterhunterrise", 4116),
    "Stardew Valley": ("stardewvalley", 1303),
    "Mount & Blade II Bannerlord": ("mountandblade2bannerlord", 3174),
    "Resident Evil 4": ("residentevil42023", 4689),
    "Resident Evil 4 (2023)": ("residentevil42023", 4689),
    "Mass Effect Legendary Edition": ("masseffectlegendaryedition", 2831),
    "Dark Souls III": ("darksouls3", 134),
    "Sekiro": ("sekiro", 2406),
    "Kingdom Come Deliverance II": ("kingdomcomedeliverance2", 7656),
    "Fallout New Vegas": ("newvegas", 130),
    "The Elder Scrolls V Skyrim": ("skyrimspecialedition", 1704),
    # 剑星:一直靠手动配置的 game_slug 在跑,map 里从来没有 → 检测流程匹配不到(7-12 发现并补上)
    "Stellar Blade": ("stellarblade", 7804),
    "StellarBlade": ("stellarblade", 7804),
    # v0.9 公测三款(slug/game_id 已用 Nexus API /v1/games/<slug>.json 核实)
    "Palworld": ("palworld", 6063),
    "Phasmophobia": ("phasmophobia", 3463),
    "REPO": ("repo", 7398),
    "R.E.P.O.": ("repo", 7398),
}


def _parse_acf(acf_path: str) -> dict:
    """极简 acf(VDF)解析:提取 installdir、name、appid 等键值。"""
    info = {}
    try:
        with open(acf_path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                parts = line.strip().split('"')
                # 形如: "installdir"\t\t"StellarBlade"
                if len(parts) >= 4 and parts[1] in ("installdir", "name", "appid", "StateFlags"):
                    info[parts[1]] = parts[3]
    except Exception:
        pass
    return info


# 常见的"游戏本体可执行文件"特征:UE 的 *-Shipping.exe,或体积较大的主 exe。
_SHIPPING_RE = ("-shipping.exe", "-win64-shipping.exe", "-wingdk-shipping.exe")


def _find_shipping_exe(game_root: str, max_depth: int = 4) -> str | None:
    """在游戏目录内有界搜索游戏本体 exe(优先 UE 的 *-Shipping.exe;否则取最大的 exe)。
    只用于判断"这是不是一个活的游戏安装",不扫全盘。"""
    if not game_root or not os.path.isdir(game_root):
        return None
    best_shipping = None
    biggest = (0, None)
    root_depth = game_root.rstrip(os.sep).count(os.sep)
    for root, dirs, files in os.walk(game_root):
        if root.count(os.sep) - root_depth > max_depth:
            dirs[:] = []
            continue
        for f in files:
            fl = f.lower()
            if fl.endswith(".exe"):
                full = os.path.join(root, f)
                if any(fl.endswith(s) for s in _SHIPPING_RE):
                    return full  # shipping exe 是最强信号,立即返回
                try:
                    sz = os.path.getsize(full)
                except OSError:
                    sz = 0
                # 排除明显的第三方工具(安装器/mod管理器等),它们通常带这些词
                if not any(k in fl for k in ("install", "setup", "unins", "launcher", "mod", "crash", "redist", "vcredist", "directx", "dxsetup")):
                    if sz > biggest[0]:
                        biggest = (sz, full)
    if best_shipping:
        return best_shipping
    # 没有 shipping exe:只有当最大 exe 也足够大(>20MB,游戏本体量级)才认
    return biggest[1] if biggest[0] > 20 * 1024 * 1024 else None


def _find_unity_exe(game_root: str) -> tuple[str | None, list[str]]:
    """Recognise Unity installs by structure instead of executable size."""
    try:
        entries = os.listdir(game_root)
    except OSError:
        return None, []

    by_lower = {entry.casefold(): entry for entry in entries}
    for entry in entries:
        if not entry.lower().endswith(".exe"):
            continue
        stem = os.path.splitext(entry)[0]
        data_name = by_lower.get(f"{stem}_data".casefold())
        if not data_name:
            continue
        data_dir = os.path.join(game_root, data_name)
        if not os.path.isdir(data_dir):
            continue

        evidence = [f"matching_data_dir:{data_name}"]
        for marker in ("UnityPlayer.dll", "GameAssembly.dll"):
            actual = by_lower.get(marker.casefold())
            if actual and os.path.isfile(os.path.join(game_root, actual)):
                evidence.append(actual)
        for marker in ("globalgamemanagers", "resources.assets"):
            if os.path.isfile(os.path.join(data_dir, marker)):
                evidence.append(f"{data_name}/{marker}")
        return os.path.join(game_root, entry), evidence
    return None, []


def _find_dotnet_game_exe(game_root: str) -> tuple[str | None, list[str]]:
    """Recognise small .NET game launchers using neighbouring runtime evidence."""
    try:
        entries = os.listdir(game_root)
    except OSError:
        return None, []

    by_lower = {entry.casefold(): entry for entry in entries}
    for entry in entries:
        if not entry.lower().endswith(".exe"):
            continue
        stem = os.path.splitext(entry)[0]
        evidence = []
        for suffix in (".dll", ".deps.json", ".runtimeconfig.json"):
            actual = by_lower.get(f"{stem}{suffix}".casefold())
            if actual and os.path.isfile(os.path.join(game_root, actual)):
                evidence.append(actual)

        # Stardew Valley is a small .NET launcher backed by MonoGame content.
        if stem.casefold() in {"stardew valley", "stardewvalley"}:
            for marker in ("Stardew Valley.dll", "MonoGame.Framework.dll"):
                actual = by_lower.get(marker.casefold())
                if actual and os.path.isfile(os.path.join(game_root, actual)):
                    evidence.append(actual)
            content = by_lower.get("content")
            if content and os.path.isdir(os.path.join(game_root, content)):
                evidence.append(content)

        has_app_dll = any(
            item.casefold() == f"{stem}.dll".casefold() for item in evidence
        )
        has_runtime = any(
            item.lower().endswith((".deps.json", ".runtimeconfig.json"))
            or item.casefold() in {"content", "monogame.framework.dll"}
            for item in evidence
        )
        if has_app_dll and has_runtime:
            return os.path.join(game_root, entry), list(dict.fromkeys(evidence))
    return None, []


def verify_game_alive(game_root: str, explicit_executable: str = "") -> dict:
    """活体验证:判断 game_root 是不是一个真实可玩的游戏安装(而非卸载残骸/空壳)。
    供安装前守卫和游戏体检使用。返回 {alive, shipping_exe, reason}。"""
    if not game_root or not os.path.isdir(game_root):
        return {"alive": False, "shipping_exe": None, "reason": "目录不存在"}
    if explicit_executable:
        root = os.path.realpath(game_root)
        executable = os.path.realpath(explicit_executable)
        try:
            inside_root = os.path.commonpath([root, executable]) == root
        except ValueError:
            inside_root = False
        if (inside_root and os.path.isfile(executable)
                and executable.lower().endswith(".exe")):
            return {
                "alive": True,
                "shipping_exe": executable,
                "engine": "manual",
                "evidence": ["user_selected_executable"],
                "reason": f"用户已明确选择游戏主程序: {os.path.basename(executable)}",
            }
        return {
            "alive": False,
            "shipping_exe": None,
            "reason": "手动选择的 EXE 不存在、不是可执行文件，或不在游戏目录内",
        }
    unity_exe, unity_evidence = _find_unity_exe(game_root)
    if unity_exe:
        stem = os.path.splitext(os.path.basename(unity_exe))[0]
        return {
            "alive": True,
            "shipping_exe": unity_exe,
            "engine": "unity",
            "evidence": unity_evidence,
            "reason": (
                f"检测到 Unity 游戏结构: {os.path.basename(unity_exe)} + "
                f"{stem}_Data"
            ),
        }
    dotnet_exe, dotnet_evidence = _find_dotnet_game_exe(game_root)
    if dotnet_exe:
        return {
            "alive": True,
            "shipping_exe": dotnet_exe,
            "engine": "dotnet",
            "evidence": dotnet_evidence,
            "reason": (
                f"检测到 .NET 游戏结构: {os.path.basename(dotnet_exe)}，"
                "并找到配套运行时/内容文件"
            ),
        }
    exe = _find_shipping_exe(game_root)
    if exe:
        return {"alive": True, "shipping_exe": exe,
                "reason": f"找到游戏本体可执行文件: {os.path.basename(exe)}"}
    return {"alive": False, "shipping_exe": None,
            "reason": "目录内未找到可信的游戏主程序或配套运行时结构——"
                      "疑似卸载残骸/空壳目录,或游戏本体不在此路径"}


def _adaptation_level(slug: str, game_path: str) -> str:
    """适配级别(前端"稳定/开放"分层的依据):
      'layout'  = 有特化 installer 规则(GAME_LAYOUTS)
      'bepinex' = 游戏目录已有 BepInEx —— 引擎级通用适配(_install_bepinex 生态)
      ''        = 未适配 → 开放模式(搜索/安装走通用兜底,落位无保证)"""
    if slug:
        from .installer import GAME_LAYOUTS
        if slug in GAME_LAYOUTS:
            return "layout"
    if os.path.isdir(os.path.join(game_path, "BepInEx")):
        return "bepinex"
    return ""


def detect_steam_games() -> list[dict]:
    """以 appmanifest_*.acf 为权威源枚举 Steam 已装游戏。
    关键:卸载游戏后 Steam 会删除对应 acf,因此 acf 存在 = 该库确实装着此游戏,
    从根本上避免把卸载残骸(common 下留下的空壳文件夹)误当成有效游戏。
    每个结果再做活体验证(shipping exe),给出 real 标记。"""
    results = []
    seen_paths = set()

    for lib_path in _find_steam_libraries():
        steamapps = os.path.join(lib_path, "steamapps")
        if not os.path.isdir(steamapps):
            continue
        try:
            acfs = [f for f in os.listdir(steamapps)
                    if f.lower().startswith("appmanifest_") and f.lower().endswith(".acf")]
        except OSError:
            continue

        for acf in acfs:
            info = _parse_acf(os.path.join(steamapps, acf))
            installdir = info.get("installdir")
            if not installdir:
                continue
            full_path = os.path.join(steamapps, "common", installdir)
            if not os.path.isdir(full_path):
                # acf 在但目录没了(异常状态):跳过
                continue
            norm = os.path.realpath(full_path).lower()
            if norm in seen_paths:
                continue
            seen_paths.add(norm)

            name = info.get("name", installdir)
            match = _match_game(installdir) or _match_game(name)
            slug, gid = match if match else ("", 0)

            alive = verify_game_alive(full_path)
            level = _adaptation_level(slug, full_path)
            results.append({
                "name": name,
                "path": full_path,
                "slug": slug,
                "game_id": gid,
                "appid": info.get("appid", ""),
                "real": alive["alive"],
                "shipping_exe": alive["shipping_exe"],
                "adapted": bool(level),
                "adapted_by": level,
                "source": "steam_acf",
            })

    # 同名去重：优先 [有 Nexus 匹配] > [活体] > 其它
    def _rank(g):
        return (0 if g["game_id"] != 0 else 1, 0 if g["real"] else 1)

    best = {}
    for g in results:
        key = g["name"].lower()
        if key not in best or _rank(g) < _rank(best[key]):
            best[key] = g

    deduped = list(best.values())
    deduped.sort(key=lambda g: (g["game_id"] == 0, g["name"].lower()))
    return deduped


def _safe_game_name(value: str, fallback_path: str) -> str:
    name = str(value or "").strip()
    if name:
        return name
    return os.path.basename(os.path.normpath(fallback_path)) or "未命名游戏"


def _local_slug(name: str) -> str:
    clean = re.sub(r"[^a-z0-9]+", "_", (name or "game").lower()).strip("_")
    return "local_" + (clean[:40] or "game")


def _game_record(name: str, game_path: str, source: str,
                 executable: str = "", **extra) -> dict | None:
    """Create one normalized launcher-agnostic game record."""
    if not game_path:
        return None
    path = os.path.abspath(os.path.expandvars(os.path.expanduser(game_path)))
    if not os.path.isdir(path):
        return None
    title = _safe_game_name(name, path)
    match = _match_game(title) or _match_game(os.path.basename(path))
    slug, gid = match if match else ("", 0)
    alive = verify_game_alive(path, executable)
    level = _adaptation_level(slug, path)
    record = {
        "name": title,
        "path": path,
        "slug": slug,
        "game_id": gid,
        "real": bool(alive.get("alive")),
        "shipping_exe": alive.get("shipping_exe"),
        "adapted": bool(level),
        "adapted_by": level,
        "source": source,
    }
    if executable:
        record["executable"] = os.path.realpath(executable)
    record.update({key: value for key, value in extra.items() if value not in (None, "")})
    return record


def _dedupe_games(items: list[dict]) -> list[dict]:
    """Deduplicate by real install path while preserving the strongest evidence."""
    best: dict[str, dict] = {}

    def rank(game: dict) -> tuple:
        return (
            0 if game.get("source") == "manual" else 1,
            0 if game.get("real") else 1,
            0 if game.get("game_id") else 1,
            0 if game.get("adapted") else 1,
        )

    for game in items:
        path = game.get("path")
        if not path:
            continue
        key = os.path.normcase(os.path.realpath(path))
        if key not in best or rank(game) < rank(best[key]):
            best[key] = game
    results = list(best.values())
    results.sort(key=lambda game: (
        not game.get("adapted", False),
        not game.get("real", False),
        game.get("name", "").casefold(),
    ))
    return results


def detect_epic_games() -> list[dict]:
    """Read Epic's installed-game manifests; no launcher process is required."""
    program_data = os.environ.get("ProgramData", r"C:\ProgramData")
    manifest_dirs = [
        os.path.join(program_data, "Epic", "EpicGamesLauncher", "Data", "Manifests"),
    ]
    results = []
    for manifest_dir in manifest_dirs:
        if not os.path.isdir(manifest_dir):
            continue
        try:
            manifests = [os.path.join(manifest_dir, name)
                         for name in os.listdir(manifest_dir)
                         if name.lower().endswith(".item")]
        except OSError:
            continue
        for manifest in manifests:
            try:
                with open(manifest, "r", encoding="utf-8-sig") as handle:
                    data = json.load(handle)
            except (OSError, ValueError):
                continue
            record = _game_record(
                data.get("DisplayName") or data.get("AppName"),
                data.get("InstallLocation", ""),
                "epic_manifest",
                catalog_item_id=data.get("CatalogItemId", ""),
                app_name=data.get("AppName", ""),
            )
            if record:
                results.append(record)
    return results


def _registry_value(key, names: tuple[str, ...]):
    import winreg
    for name in names:
        try:
            value, _ = winreg.QueryValueEx(key, name)
            if value:
                return str(value).strip().strip('"')
        except OSError:
            continue
    return ""


def _registry_subkey_games(base_paths: list[tuple], source: str) -> list[dict]:
    if os.name != "nt":
        return []
    try:
        import winreg
    except ImportError:
        return []
    results = []
    views = [0, getattr(winreg, "KEY_WOW64_32KEY", 0),
             getattr(winreg, "KEY_WOW64_64KEY", 0)]
    for hive, base_path in base_paths:
        for view in dict.fromkeys(views):
            try:
                base = winreg.OpenKey(hive, base_path, 0, winreg.KEY_READ | view)
            except OSError:
                continue
            try:
                child_count = winreg.QueryInfoKey(base)[0]
                for index in range(child_count):
                    try:
                        child_name = winreg.EnumKey(base, index)
                        child = winreg.OpenKey(base, child_name)
                    except OSError:
                        continue
                    try:
                        game_path = _registry_value(child, (
                            "Install Dir", "InstallDir", "InstallLocation",
                            "InstallPath", "path",
                        ))
                        display_icon = _registry_value(child, ("DisplayIcon",))
                        if not game_path and display_icon:
                            icon_path = display_icon.split(",")[0].strip().strip('"')
                            if os.path.isfile(icon_path):
                                game_path = os.path.dirname(icon_path)
                        name = _registry_value(child, (
                            "DisplayName", "GameName", "gameName", "Title",
                        )) or child_name
                        record = _game_record(name, game_path, source)
                        if record:
                            results.append(record)
                    finally:
                        child.Close()
            finally:
                base.Close()
    return results


def detect_ea_games() -> list[dict]:
    """Detect EA App/Origin installs through their game registry and shallow libraries."""
    results = []
    if os.name == "nt":
        import winreg
        bases = []
        for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            for path in (
                r"SOFTWARE\EA Games",
                r"SOFTWARE\Electronic Arts\EA Games",
                r"SOFTWARE\Origin Games",
            ):
                bases.append((hive, path))
        results.extend(_registry_subkey_games(bases, "ea_registry"))
    results.extend(_scan_named_libraries(("EA Games", "Origin Games"), "ea_library"))
    return results


def detect_gog_games() -> list[dict]:
    results = []
    if os.name == "nt":
        import winreg
        bases = [
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\GOG.com\Games"),
            (winreg.HKEY_CURRENT_USER, r"SOFTWARE\GOG.com\Games"),
        ]
        results.extend(_registry_subkey_games(bases, "gog_registry"))
    results.extend(_scan_named_libraries(("GOG Games",), "gog_library"))
    return results


def _scan_named_libraries(names: tuple[str, ...], source: str) -> list[dict]:
    """Shallow-scan conventional launcher libraries, never the whole drive."""
    roots = set()
    for drive in _get_drives():
        for name in names:
            roots.add(os.path.join(drive, name))
            roots.add(os.path.join(drive, "Program Files", name))
            roots.add(os.path.join(drive, "Program Files (x86)", name))
    results = []
    for root in roots:
        if not os.path.isdir(root):
            continue
        try:
            children = os.listdir(root)
        except OSError:
            continue
        for child in children:
            path = os.path.join(root, child)
            record = _game_record(child, path, source)
            if record and record["real"]:
                results.append(record)
    return results


def detect_wegame_games() -> list[dict]:
    """Detect the common WeGameApps/rail_apps layout without crawling disks."""
    roots = set()
    for drive in _get_drives():
        roots.update({
            os.path.join(drive, "WeGameApps", "rail_apps"),
            os.path.join(drive, "Program Files", "WeGameApps", "rail_apps"),
            os.path.join(drive, "Program Files (x86)", "WeGameApps", "rail_apps"),
        })
    results = []
    for root in roots:
        if not os.path.isdir(root):
            continue
        try:
            children = os.listdir(root)
        except OSError:
            continue
        for child in children:
            path = os.path.join(root, child)
            record = _game_record(child, path, "wegame_rail")
            if record and record["real"]:
                results.append(record)
    return results


def _xbox_library_root(drive_root: str) -> str:
    """Read Xbox Gaming Services' drive marker (RGBX + UTF-16LE path)."""
    marker = os.path.join(drive_root, ".GamingRoot")
    try:
        with open(marker, "rb") as handle:
            raw = handle.read(4096)
    except OSError:
        return ""
    if len(raw) < 10 or raw[:4] != b"RGBX":
        return ""
    try:
        relative = raw[8:].decode("utf-16-le").rstrip("\0").strip()
    except UnicodeDecodeError:
        return ""
    if not relative or os.path.isabs(relative):
        return ""
    candidate = os.path.abspath(os.path.join(drive_root, relative))
    try:
        if os.path.commonpath([os.path.abspath(drive_root), candidate]) != os.path.abspath(drive_root):
            return ""
    except ValueError:
        return ""
    return candidate


def _xbox_manifest_metadata(game_root: str) -> dict:
    """Read the authoritative display name and executable from GDK metadata."""
    try:
        names = {
            name.casefold(): name for name in os.listdir(game_root)
            if name.casefold() == "microsoftgame.config"
        }
        manifest_name = names.get("microsoftgame.config")
        if not manifest_name:
            return {}
        import xml.etree.ElementTree as ET
        root = ET.parse(os.path.join(game_root, manifest_name)).getroot()
    except (OSError, ET.ParseError):
        return {}

    shell = root.find(".//ShellVisuals")
    executable = root.find(".//ExecutableList/Executable")
    identity = root.find(".//Identity")
    store = root.find(".//StoreId")
    executable_name = (
        str(executable.attrib.get("Name") or "") if executable is not None else ""
    )
    executable_path = os.path.join(game_root, executable_name) if executable_name else ""
    if executable_path and not os.path.isfile(executable_path):
        executable_path = ""
    return {
        "display_name": (
            str(shell.attrib.get("DefaultDisplayName") or "")
            if shell is not None else ""
        ),
        "executable": executable_path,
        "package_identity": (
            str(identity.attrib.get("Name") or "") if identity is not None else ""
        ),
        "store_id": str(store.text or "").strip() if store is not None else "",
    }


def detect_xbox_games(drive_roots: list[str] | None = None) -> list[dict]:
    """Detect mod-accessible Xbox/Microsoft Store installs.

    Modern Xbox installs expose a per-drive .GamingRoot marker and place each
    title below <library>/<title>/Content.  The Content directory is the real
    game root used by mod tools.  Legacy WindowsApps packages are deliberately
    not crawled: their ACL/virtualisation makes direct file modification unsafe.
    """
    roots = set()
    for drive in drive_roots or _get_drives():
        library = _xbox_library_root(drive)
        if library:
            roots.add(library)
        # Older "enable advanced management features" installs used this
        # conventional location without a readable marker.
        roots.add(os.path.join(drive, "XboxGames"))
        roots.add(os.path.join(drive, "Program Files", "ModifiableWindowsApps"))

    results = []
    for library in roots:
        if not os.path.isdir(library):
            continue
        try:
            children = os.listdir(library)
        except OSError:
            continue
        for child in children:
            package_dir = os.path.join(library, child)
            if not os.path.isdir(package_dir):
                continue
            content_dir = os.path.join(package_dir, "Content")
            game_root = content_dir if os.path.isdir(content_dir) else package_dir
            metadata = _xbox_manifest_metadata(game_root)
            record = _game_record(
                metadata.get("display_name") or child,
                game_root,
                "xbox_gaming_root",
                executable=metadata.get("executable") or "",
                xbox_library=library,
                xbox_package_dir=package_dir,
                xbox_store_id=metadata.get("store_id") or "",
                xbox_package_identity=metadata.get("package_identity") or "",
                platform="xbox",
            )
            # Component/DLC packages share the library but generally contain no
            # playable executable.  Only expose independently verifiable games.
            if record and record["real"]:
                results.append(record)
    return results


def normalize_manual_game(entry: dict) -> dict | None:
    path = str(entry.get("path") or entry.get("game_root") or "")
    executable = str(entry.get("executable") or "")
    record = _game_record(
        entry.get("name") or entry.get("game_name"),
        path,
        "manual",
        executable=executable,
    )
    if not record:
        return None
    if entry.get("slug"):
        record["slug"] = str(entry["slug"])
        record["game_id"] = int(entry.get("game_id") or 0)
        level = _adaptation_level(record["slug"], record["path"])
        record["adapted"] = bool(level)
        record["adapted_by"] = level
    record["manual"] = True
    return record


def detect_installed_games(manual_games: list[dict] | None = None) -> list[dict]:
    """Unified discovery for launchers plus user-authoritative manual imports."""
    results = []
    detectors = (
        detect_steam_games,
        detect_epic_games,
        detect_ea_games,
        detect_gog_games,
        detect_wegame_games,
        detect_xbox_games,
    )
    for detector in detectors:
        try:
            results.extend(detector())
        except Exception:
            # One damaged launcher database must not hide games from other sources.
            continue
    for entry in manual_games or []:
        record = normalize_manual_game(entry)
        if record:
            results.append(record)
    return _dedupe_games(results)


def upsert_manual_game(entries: list[dict] | None, name: str, game_root: str,
                       executable: str = "", slug: str = "",
                       game_id: int = 0) -> tuple[list[dict], dict]:
    path = os.path.abspath(os.path.expanduser(os.path.expandvars(game_root)))
    title = _safe_game_name(name, path)
    match = _match_game(title) or _match_game(os.path.basename(path))
    matched_slug, matched_id = match if match else ("", 0)
    saved = {
        "name": title,
        "path": path,
        "executable": os.path.realpath(executable) if executable else "",
        "slug": slug or matched_slug or _local_slug(title),
        "game_id": int(game_id or matched_id or 0),
    }
    merged = []
    target = os.path.normcase(os.path.realpath(path))
    for entry in entries or []:
        entry_path = str(entry.get("path") or entry.get("game_root") or "")
        if entry_path and os.path.normcase(os.path.realpath(entry_path)) == target:
            continue
        merged.append(entry)
    merged.append(saved)
    return merged, saved


def health_check_games(configured_root: str = "", configured_slug: str = "",
                       manual_games: list[dict] | None = None) -> dict:
    """游戏体检:重新检测所有 Steam 游戏 + 校验当前配置的游戏根目录是否活体。
    供前端"游戏体检"按钮使用。"""
    detected = detect_installed_games(manual_games)
    report = {"detected": detected, "configured": None, "new_games": []}

    if configured_root:
        alive = verify_game_alive(configured_root)
        # 当前配置的路径是否出现在检测结果里(用 realpath 比对)
        cfg_norm = os.path.realpath(configured_root).lower()
        matched = next((g for g in detected
                        if os.path.realpath(g["path"]).lower() == cfg_norm), None)
        report["configured"] = {
            "root": configured_root,
            "slug": configured_slug,
            "alive": alive["alive"],
            "reason": alive["reason"],
            "shipping_exe": alive["shipping_exe"],
            "in_detected_libraries": matched is not None,
            "detected_source": matched.get("source") if matched else None,
            # Kept for older frontends; now means "present in any detected library".
            "in_steam_library": matched is not None,
            "warning": None if alive["alive"] else
                       "当前配置的游戏目录未通过活体检测——可能是卸载残骸或路径已失效,"
                       "安装 mod 前请先在设置中更正为真实的游戏安装路径。",
        }
    return report


def detect_steam_games_legacy() -> list[dict]:
    results = []
    seen_paths = set()

    library_paths = _find_steam_libraries()

    for lib_path in library_paths:
        common_path = os.path.join(lib_path, "steamapps", "common")
        if not os.path.isdir(common_path):
            continue

        for entry in os.listdir(common_path):
            full_path = os.path.join(common_path, entry)
            if not os.path.isdir(full_path):
                continue

            norm = os.path.realpath(full_path).lower()
            if norm in seen_paths:
                continue
            seen_paths.add(norm)

            match = _match_game(entry)
            if match:
                slug, gid = match
            else:
                slug, gid = "", 0

            results.append({
                "name": entry,
                "path": full_path,
                "slug": slug,
                "game_id": gid,
            })

    # 标记真实安装：有 .exe 的才是真装的（排除卸载残留的空壳幽灵文件夹）
    def _has_exe(path):
        try:
            return any(f.lower().endswith(".exe") for f in os.listdir(path))
        except OSError:
            return False

    for g in results:
        g["real"] = _has_exe(g["path"])

    # 同名去重：优先 [有 Nexus 匹配] > [真实安装(有exe)] > 其它
    def _rank(g):
        return (0 if g["game_id"] != 0 else 1, 0 if g["real"] else 1)

    best = {}
    for g in results:
        key = g["name"].lower()
        if key not in best or _rank(g) < _rank(best[key]):
            best[key] = g

    deduped = list(best.values())
    deduped.sort(key=lambda g: (g["game_id"] == 0, g["name"].lower()))
    return deduped


def lookup_game(name_or_slug: str) -> dict | None:
    name_or_slug_lower = name_or_slug.lower()
    for folder_name, (slug, gid) in NEXUS_GAME_MAP.items():
        if folder_name.lower() == name_or_slug_lower or slug == name_or_slug_lower:
            return {"name": folder_name, "slug": slug, "game_id": gid, "path": ""}
    return None


def list_known_games() -> list[dict]:
    seen = set()
    results = []
    for name, (slug, gid) in NEXUS_GAME_MAP.items():
        if slug not in seen:
            seen.add(slug)
            results.append({"name": name, "slug": slug, "game_id": gid})
    results.sort(key=lambda g: g["name"].lower())
    return results


def _find_steam_libraries() -> list[str]:
    paths = []

    steam_default = os.path.join(os.environ.get("ProgramFiles(x86)", "C:\\Program Files (x86)"), "Steam")
    if os.path.isdir(steam_default):
        paths.append(steam_default)

    library_file = os.path.join(steam_default, "steamapps", "libraryfolders.vdf")
    if os.path.isfile(library_file):
        try:
            with open(library_file, "r", encoding="utf-8") as f:
                for line in f:
                    stripped = line.strip()
                    if stripped.startswith('"path"'):
                        p = stripped.split('"')[3].replace("\\\\", "\\")
                        if os.path.isdir(p) and p not in paths:
                            paths.append(p)
        except Exception:
            pass

    if not paths:
        for drive in _get_drives():
            for root, dirs, _ in os.walk(drive, topdown=True):
                dirs[:] = [d for d in dirs if not d.startswith("$")]
                if "SteamLibrary" in dirs:
                    p = os.path.join(root, "SteamLibrary")
                    if os.path.isdir(os.path.join(p, "steamapps", "common")):
                        paths.append(p)
                if "Steam" in dirs and "steamapps" in os.listdir(os.path.join(root, "Steam")):
                    p = os.path.join(root, "Steam")
                    if os.path.isdir(os.path.join(p, "steamapps", "common")) and p not in paths:
                        paths.append(p)
                break

    return paths


def _get_drives() -> list[str]:
    drives = []
    for letter in "CDEFGHIJKLMNOPQRSTUVWXYZ":
        p = f"{letter}:\\"
        if os.path.exists(p):
            drives.append(p)
    return drives


def _match_game(folder_name: str) -> tuple[str, int] | None:
    for name, (slug, gid) in NEXUS_GAME_MAP.items():
        if name.lower() == folder_name.lower():
            return slug, gid

    clean = folder_name.lower().replace(" ", "").replace("_", "").replace("-", "")
    for name, (slug, gid) in NEXUS_GAME_MAP.items():
        name_clean = name.lower().replace(" ", "").replace("_", "").replace("-", "")
        if name_clean == clean:
            return slug, gid

    for name, (slug, gid) in NEXUS_GAME_MAP.items():
        name_lower = name.lower()
        if name_lower in folder_name.lower() or folder_name.lower() in name_lower:
            return slug, gid

    return None


def _auto_infer(folder_name: str) -> tuple[str, int] | None:
    """自动推断游戏 slug：小写去空格 → 调 API 验证"""
    # Skip obvious non-game folders
    skip_patterns = ["bepinex", "blender", "benchmark", "server", "sdk", "editor", "tool", "demo", "alpha", "beta"]
    lower = folder_name.lower()
    if any(p in lower for p in skip_patterns):
        return None
    if lower.startswith(("#", ".", "_")):
        return None

    auto_slug = lower.replace(" ", "").replace(":", "").replace("'", "").replace("&", "and")
    if len(auto_slug) < 3:
        return None

    try:
        import ssl, urllib.request, json
        from .config import load as load_cfg
        cfg = load_cfg()
        api_key = cfg.nexus_api_key
        headers = {"Accept": "application/json"}
        if api_key:
            headers["apikey"] = api_key
        ctx = ssl._create_unverified_context()
        url = f"https://api.nexusmods.com/v1/games/{auto_slug}.json"
        req = urllib.request.Request(url, headers=headers)
        data = json.loads(urllib.request.urlopen(req, context=ctx, timeout=1).read())
        gid = data.get("id", 0)
        if gid:
            return auto_slug, gid
    except Exception:
        pass
    return None
