"""战役3:诊断与自愈。
  · classify_oserror —— 把文件操作的 OSError 翻译成可行动的 {code, reason, action}
  · game_diagnose    —— 按框架定位日志、抓 Error/Warning、归因到已装 mod(块2)
  · export_diag_bundle —— 诊断包脱敏导出(块3)
"""
import errno
import glob
import json
import os
import platform
import re
import shutil
import sys
import time
import zipfile
from dataclasses import asdict, is_dataclass

from .config import CONFIG_DIR


def _human(n: float) -> str:
    for u in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f}{u}"
        n /= 1024
    return f"{n:.1f}PB"


def _free_space(path: str) -> str:
    """path 所在盘的剩余空间(人类可读);取不到返回空串。"""
    for p in (path, os.path.dirname(path) or ".", "."):
        try:
            if p and os.path.exists(p):
                return _human(shutil.disk_usage(p).free)
        except OSError:
            continue
    return ""


def classify_oserror(exc: OSError, path: str = "") -> dict:
    """把文件操作的 OSError 翻译成 {code, reason, action}。
    Windows 上文件被游戏锁定是安装/回滚失败的头号原因,单列出来并优先判断
    (它表现为 winerror 32 sharing violation,或 EACCES,极易和纯权限问题混淆)。"""
    e = getattr(exc, "errno", None)
    win = getattr(exc, "winerror", None)

    # 文件被占用(游戏/Steam/杀软正打开它)—— Windows sharing/lock violation
    if win in (32, 33):
        return {"code": "locked",
                "reason": "文件被其他程序占用(正被打开或锁定)",
                "action": "游戏或相关程序可能正在运行。请完全退出游戏(含 Steam 后台、"
                          "反作弊/Overlay 进程)后重试同一操作。"}
    # 磁盘满
    if e == errno.ENOSPC or win == 112:
        free = _free_space(path)
        return {"code": "disk_full",
                "reason": "磁盘空间不足" + (f"(该盘剩余 {free})" if free else ""),
                "action": "清理该磁盘或把游戏/快照库移到更大的盘后重试。"}
    # 权限(只读 / 需管理员 / Program Files)
    if e in (errno.EACCES, errno.EPERM) or win == 5:
        return {"code": "permission",
                "reason": "无权限访问(文件被锁、设为只读、或目录需要管理员权限)",
                "action": "①先确认游戏已完全退出——文件锁是最常见原因;"
                          "②检查目标文件是否被设为只读;"
                          "③游戏若装在 Program Files,考虑把它移到普通目录(如 D:\\Games)后重试。"}
    if e == errno.ENOENT:
        return {"code": "not_found",
                "reason": "目标文件或目录不存在",
                "action": "确认游戏路径正确、文件未被其他工具移动或删除。"}
    if e == errno.EROFS:
        return {"code": "readonly",
                "reason": "目标位于只读文件系统",
                "action": "该位置不可写,检查磁盘挂载/权限设置。"}
    return {"code": "unknown",
            "reason": str(exc) or "未知的文件系统错误",
            "action": "请导出诊断包(game_diagnose 的 export)连同此错误反馈给开发者。"}


# ─────────────────────────────────────────────────────────────
# 块2:game_diagnose —— 按框架定位日志、抓 Error/Warning、归因到已装 mod
# ─────────────────────────────────────────────────────────────

# 抓可疑行的启发式。关键教训(真实 Palworld UE4SS.log 实测):通用正则会两头翻车——
# 漏真错误(mod 失败信号是 "not valid" 不含 error/fail),又误报噪音(框架启动 dump 的成员
# 变量偏移 "FArchiveState::ArIsError = 0x29" 含 Error 字样但非错误)。故:先过噪音,再抓错误,
# 并对带 mod 名的框架强信号单独结构化归因。
_ERR_RE = re.compile(r"(error|exception|fail|fatal|could not|unable to|missing|"
                     r"not valid|invalid|null\s*reference|unresolved)", re.I)
_WARN_RE = re.compile(r"\bwarn", re.I)
_DEP_RE = re.compile(r"(could not find|missing dependency|depend|unresolved|requires|no such|prerequisite)", re.I)
_VER_RE = re.compile(r"(incompatible|mismatch|expected .* got|wrong version|unsupported version)", re.I)

# 噪音:框架启动时 dump 的成员变量偏移(Name::field = 0xHEX),含 Error/Missing 字样但是地址不是错误
_NOISE_RE = re.compile(r"::\w+\s*=\s*0x[0-9A-Fa-f]+")

# Global Unity/BepInEx exception loggers describe who printed an exception,
# not who caused it.  They must never be used as Mod ownership evidence.
_LOGGER_FRAME_RE = re.compile(
    r"(?:PartShrinkerLogFilter:LogException|"
    r"UnityEngine\.DebugLogHandler:LogException|"
    r"UnityEngine\.Debug:CallOverridenDebugHandler)",
    re.I,
)

# 框架强信号(带 mod 名的明确失败,可直接结构化归因,比通用文本匹配可靠得多):
# UE4SS "ModClass for 'DekBasicMinimap_P' is not valid" = 该 mod 蓝图类加载失败,
# 最常见原因是 mod 太久没更新、与当前游戏版本不兼容。
_UE4SS_MODFAIL_RE = re.compile(r"ModClass for '([^']+)' is not valid", re.I)


def _read_tail(path: str, max_bytes: int = 200_000) -> str:
    """只读日志尾部(大日志可达几十 MB),按 UTF-8 宽松解码。"""
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - max_bytes))
            return f.read().decode("utf-8", errors="replace")
    except OSError:
        return ""


def _framework_logs(game_root: str) -> list:
    """探测该游戏根下存在的框架日志。返回 [(框架名, 日志路径)]。"""
    cands = [
        ("BepInEx", os.path.join(game_root, "BepInEx", "LogOutput.log")),
        ("MelonLoader", os.path.join(game_root, "MelonLoader", "Latest.log")),
    ]
    # UE4SS: <project>/Binaries/Win64/ue4ss/UE4SS.log(项目前缀因游戏而异,glob 定位)
    for p in glob.glob(os.path.join(game_root, "*", "Binaries", "Win64", "ue4ss", "UE4SS.log")):
        cands.append(("UE4SS", p))
    return [(fw, p) for fw, p in cands if os.path.isfile(p)]


def _mod_tokens(installed_mods) -> dict:
    """每个 mod → 归因关键词(名字 + 文件 basename 去扩展名)。太短的词丢弃防误匹配。"""
    toks = {}
    for m in installed_mods or []:
        name = (getattr(m, "name", "") or "").strip()
        keys = set()
        if len(name) >= 4:
            keys.add(name.lower())
        files = getattr(m, "files_installed", "") or "[]"
        try:
            parsed = json.loads(files) if isinstance(files, str) else files
            for f in (parsed or []):
                b = os.path.splitext(os.path.basename(str(f)))[0].lower()
                if len(b) >= 4:
                    keys.add(b)
        except Exception:
            pass
        if keys:
            toks[getattr(m, "id", name) or name] = {"name": name or "(未命名)", "keys": keys}
    return toks


def game_diagnose(game_root: str, game_slug: str = "", installed_mods=None,
                  max_lines: int = 40) -> dict:
    """按框架定位日志,抓最近 Error/Warning,归因到已装 mod,给出可行动建议。
    纯读取,不改任何文件。"""
    if not game_root or not os.path.isdir(game_root):
        return {"frameworks": [], "findings": [], "error": "游戏目录不存在"}
    logs = _framework_logs(game_root)
    if not logs:
        return {"frameworks": [], "findings": [],
                "note": "未找到已知框架的日志(BepInEx/MelonLoader/UE4SS)。"
                        "游戏可能未装加载器,或还没运行过一次生成日志。"}

    tokens = _mod_tokens(installed_mods)

    def _match_mod(name_in_log: str):
        """把日志里的名字(如 pak 名 DekBasicMinimap_P)匹配到已装 mod,返回展示名或原名。"""
        low = name_in_log.lower()
        for info in tokens.values():
            if any(k in low or low in k for k in info["keys"]):
                return info["name"]
        return name_in_log

    findings = []
    for fw, path in logs:
        lines = _read_tail(path).splitlines()
        errs, warns = [], []
        modfails = {}                       # 框架强信号:mod名 → 出现次数(明确的加载失败)
        for ln in lines:
            s = ln.strip()
            if not s or _NOISE_RE.search(s):     # ① 先过噪音(成员偏移 dump)
                continue
            if _LOGGER_FRAME_RE.search(s):
                continue
            m = _UE4SS_MODFAIL_RE.search(s)      # ② 框架强信号:带 mod 名的明确失败
            if m:
                modfails[m.group(1)] = modfails.get(m.group(1), 0) + 1
                continue                          # 强信号不再进通用错误桶(避免重复+噪音)
            if _ERR_RE.search(s):
                errs.append(s)
            elif _WARN_RE.search(s):
                warns.append(s)
        errs, warns = errs[-max_lines:], warns[-max_lines:]

        # 强信号归因(可靠):明确失败的 mod → 匹配已装 mod
        strong = [{"mod": _match_mod(nm), "raw_name": nm, "hits": n,
                   "signal": "蓝图类加载失败(ModClass not valid)"}
                  for nm, n in sorted(modfails.items(), key=lambda x: -x[1])]

        # 通用归因(兜底):剩余错误行里出现某 mod 关键词
        attributed = {}
        for ln in errs + warns:
            low = ln.lower()
            for mid, info in tokens.items():
                if any(k in low for k in info["keys"]):
                    a = attributed.setdefault(mid, {"name": info["name"], "lines": []})
                    if len(a["lines"]) < 5:
                        a["lines"].append(ln)

        # 建议:强信号优先(给准确的"不兼容"结论,而非笼统"缺依赖")
        suggestions = []
        for s in strong:
            suggestions.append(
                f"「{s['mod']}」蓝图类加载失败(日志 {s['hits']} 次)——最常见原因是该 mod 太久没更新、"
                f"与当前游戏版本不兼容。建议禁用或找替代;若刚更新过游戏,可等作者适配。"
                f"(注:依赖它的功能会连带失效,如它带的配置项会让 Mod Config 类菜单不显示)")
        for a in attributed.values():
            suggestions.append(f"错误提及 mod「{a['name']}」→ 尝试禁用/更新,或查与其他 mod 的兼容性。")
        joined = "\n".join(errs)
        if not strong and _DEP_RE.search(joined):
            suggestions.append("日志出现依赖/缺失字样 → 疑似缺前置,检查相关 mod 的依赖是否装齐。")
        if _VER_RE.search(joined):
            suggestions.append("日志出现版本不兼容字样 → 核对 mod 与游戏/加载器版本。")
        if not strong and not attributed and errs:
            suggestions.append("有报错但未能归因到具体 mod → 导出诊断包人工排查,"
                               "或逐个禁用近期安装的 mod 二分定位。")
        if not errs and not warns and not strong:
            suggestions.append("日志未见明显报错 —— 若仍有问题,可能是 mod 未生效(加载器没起)"
                               "或问题不写日志,建议导出诊断包。")

        findings.append({
            "framework": fw, "log": path,
            "error_count": len(errs), "warning_count": len(warns),
            "broken_mods": strong,          # 结构化的"明确损坏"清单(最可靠的诊断产物)
            "recent_errors": errs[-10:], "recent_warnings": warns[-5:],
            "attributed_mods": [{"id": mid, **a} for mid, a in attributed.items()],
            "suggestions": suggestions,
        })
    return {"frameworks": [fw for fw, _ in logs], "findings": findings}


# ─────────────────────────────────────────────────────────────
# 块3:诊断包导出 —— 框架日志 + 操作记录 + 版本环境,绝不含任何 key
# ─────────────────────────────────────────────────────────────

# 兜底脱敏:即便日志/记录里意外混入密钥,也在打包前抹掉。
# sk-/tvly- 段允许连字符与下划线(现代 key 如 OpenAI sk-proj-xxx 含连字符),否则会在
# 第一个连字符处截断、漏掉后半段(test_diag_bundle D2 抓到过这个真实漏洞)。
_SECRET_RE = re.compile(r"(sk-[A-Za-z0-9_-]{12,}|tvly-[A-Za-z0-9_-]{12,}|[A-Fa-f0-9]{32,})")


def _scrub(text: str) -> str:
    return _SECRET_RE.sub("***REDACTED***", text or "")


def _redact_config(cfg) -> dict:
    """配置快照脱敏:任何名字含 key/token/secret 的字段一律抹掉(不赌具体字段名)。"""
    if cfg is None:
        return {}
    try:
        d = asdict(cfg) if is_dataclass(cfg) else dict(vars(cfg))
    except TypeError:
        return {}
    for k in list(d):
        if any(s in k.lower() for s in ("key", "token", "secret", "password")):
            d[k] = "***REDACTED***" if d[k] else "(未设置)"
    return d


def export_diag_bundle(game_root: str, game_slug: str = "", cfg=None,
                       installed_mods=None, operation_log=None,
                       out_dir: str = "", app_version: str = "") -> dict:
    """打诊断包 zip:框架日志 + 操作记录 + 版本/环境 + 脱敏配置。
    绝不含任何 API key —— 配置按字段名脱敏,所有文本再过一遍 _scrub 兜底。"""
    if not game_root or not os.path.isdir(game_root):
        return {"error": "游戏目录不存在,无法生成诊断包"}
    ts = time.strftime("%Y%m%d_%H%M%S")
    out_dir = out_dir or os.path.join(CONFIG_DIR, "diagnostics")
    os.makedirs(out_dir, exist_ok=True)
    zip_path = os.path.join(out_dir, f"modagent_diag_{game_slug or 'game'}_{ts}.zip")

    logs = _framework_logs(game_root)
    manifest = {
        "generated_at": ts,
        "app_version": app_version or "unknown",
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "game_slug": game_slug,
        "game_root": game_root,
        "frameworks": [fw for fw, _ in logs],
        "config_redacted": _redact_config(cfg),
        "installed_mods": [
            {"id": getattr(m, "id", ""), "name": getattr(m, "name", ""),
             "version": getattr(m, "version", ""), "installed_by": getattr(m, "installed_by", "")}
            for m in (installed_mods or [])
        ],
    }

    contains = ["manifest.json"]
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("manifest.json", _scrub(json.dumps(manifest, ensure_ascii=False, indent=2)))
        if operation_log is not None:
            z.writestr("operation_log.json",
                       _scrub(json.dumps(operation_log, ensure_ascii=False, indent=2)))
            contains.append("operation_log.json")
        for fw, path in logs:
            arc = f"logs/{fw}_{os.path.basename(path)}"
            z.writestr(arc, _scrub(_read_tail(path, max_bytes=1_000_000)))
            contains.append(arc)

    return {"bundle": zip_path, "size_bytes": os.path.getsize(zip_path),
            "contains": contains, "redacted": True,
            "note": "诊断包已生成并脱敏(不含任何 API key)。可手动发给开发者协助排查。"}
