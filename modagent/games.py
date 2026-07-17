import os
import json

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


def verify_game_alive(game_root: str) -> dict:
    """活体验证:判断 game_root 是不是一个真实可玩的游戏安装(而非卸载残骸/空壳)。
    供安装前守卫和游戏体检使用。返回 {alive, shipping_exe, reason}。"""
    if not game_root or not os.path.isdir(game_root):
        return {"alive": False, "shipping_exe": None, "reason": "目录不存在"}
    exe = _find_shipping_exe(game_root)
    if exe:
        return {"alive": True, "shipping_exe": exe,
                "reason": f"找到游戏本体可执行文件: {os.path.basename(exe)}"}
    return {"alive": False, "shipping_exe": None,
            "reason": "目录内未找到游戏本体可执行文件(*-Shipping.exe 或足够大的主 exe)——"
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


def health_check_games(configured_root: str = "", configured_slug: str = "") -> dict:
    """游戏体检:重新检测所有 Steam 游戏 + 校验当前配置的游戏根目录是否活体。
    供前端"游戏体检"按钮使用。"""
    detected = detect_steam_games()
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
