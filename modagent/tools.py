import asyncio
import glob
import json
import os
import time
from typing import Optional

from .config import Config, Tier
from . import db
from . import nexus
from . import downloader
from . import installer
from . import snapshot
from . import diagnostics
from . import progress
from . import patcher
from . import games as games_mod


def _resolve_github_release_url(url: str) -> dict:
    """把 GitHub releases 页面/仓库 URL 解析成真实的 zip 资产直链。
    识别形如 github.com/OWNER/REPO/releases[/...]、releases/tag/X、或裸仓库地址。
    已经是 .../releases/download/.../*.zip 直链的,原样返回。
    返回 {url, name, version, note} 或 {error}。
    """
    import re as _re
    import urllib.request as _u

    u = (url or "").strip()
    # 已是资产直链:直接用
    if "/releases/download/" in u and u.lower().endswith((".zip", ".7z", ".rar")):
        return {"url": u, "name": u.rsplit("/", 1)[-1]}

    m = _re.search(r"github\.com/([^/]+)/([^/]+?)(?:\.git)?(?:/|$)", u)
    if not m:
        return {"error": "不是可识别的 GitHub 链接"}
    owner, repo = m.group(1), m.group(2)

    # 指定了 tag 就取该 release,否则取 latest
    tagm = _re.search(r"/releases/tag/([^/?#]+)", u)
    if tagm:
        api = f"https://api.github.com/repos/{owner}/{repo}/releases/tags/{tagm.group(1)}"
    else:
        api = f"https://api.github.com/repos/{owner}/{repo}/releases/latest"

    try:
        req = _u.Request(api, headers={"User-Agent": "ModAgent", "Accept": "application/vnd.github+json"})
        with _u.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        return {"error": f"读取 GitHub Releases 失败: {e}"}

    assets = data.get("assets", []) or []
    zips = [a for a in assets if str(a.get("name", "")).lower().endswith((".zip", ".7z", ".rar"))]
    if not zips:
        return {"error": "该 Release 没有可下载的压缩包资产"}

    # 选择策略:排除 dev/debug/source 类,优先文件名最短的正式版(dev 版常带 zDEV/DEBUG 前缀且体积大)
    def _is_dev(a):
        n = str(a.get("name", "")).lower()
        return any(k in n for k in ("zdev", "-dev", "debug", "source", "src", "symbols", "pdb"))
    prod = [a for a in zips if not _is_dev(a)] or zips
    prod.sort(key=lambda a: (len(a.get("name", "")), a.get("size", 0)))
    chosen = prod[0]

    return {
        "url": chosen.get("browser_download_url"),
        "name": chosen.get("name"),
        "version": data.get("tag_name", ""),
        "note": f"从 GitHub Releases 自动解析:{data.get('tag_name','')} → {chosen.get('name')}"
                + (f"(跳过了 {len(zips)-len(prod)} 个 dev/调试资产)" if len(prod) < len(zips) else ""),
    }
from . import scanner


def build_tools_definitions(tier: str) -> list[dict]:
    all_tools = [
        _t("scan_existing_mods", "扫描当前游戏目录，识别已手动安装的 Mod 文件（非 ModAgent 安装的），对比 Nexus 数据库确认身份。首次使用或发现游戏目录有文件但 db 为空时自动触发。",
           {}, []),
        _t("import_existing_mods", "将 scan_existing_mods 识别出的 Mod 批量导入数据库。导入后标记为 imported（非 ModAgent 安装）。",
           {"mods": {"type": "array", "items": {"type": "object", "properties": {
               "mod_id": {"type": "string"}, "name": {"type": "string"}, "version": {"type": "string"},
               "files": {"type": "array", "items": {"type": "string"}}},
               "required": ["mod_id", "name"]}}},
           ["mods"]),
        _t("mod_recommend", "根据用户自然语言描述智能推荐 Mod——多源聚合:自动识别当前游戏的可用来源(Nexus/创意工坊/Thunderstore/GameBanana/GitHub)并发搜索,按来源分组返回(各源热度口径不同,不跨源排序)。模糊需求('来点好玩的''综合热度')首选本工具;失败的源在 sources_failed 里,如实告知用户。",
           {"query": {"type": "string", "description": "用户原始需求描述(英文关键词命中率更高)"}},
           ["query"]),
        _t("nexus_search", "按关键词搜索 Nexus Mods。返回 mod_id / 名称 / 摘要 / 评分。",
           {"query": {"type": "string", "description": "搜索关键词（英文最佳）"}},
           ["query"]),
        _t("collection_view", "读取 Nexus 合集(Collection)里包含的所有 Mod。用户给合集链接(含 /collections/xxx)或合集 slug 时调用。",
           {"collection": {"type": "string", "description": "合集 slug（如 fgavn5）或完整合集 URL"}},
           ["collection"]),
        _t("download_from_url", "从 Nexus 以外的来源下载 mod：支持 GitHub Releases、Thunderstore、GameBanana。用户粘贴这些站点链接时调用；下载后用返回的 local_path 调 mod_install 安装。",
           {"url": {"type": "string", "description": "GitHub / Thunderstore / GameBanana 的 mod 链接"}},
           ["url"]),
        _t("thunderstore_search", "在 Thunderstore 上按关键词搜索当前游戏的 mod（BepInEx 类游戏，如 REPO/Lethal Company/Valheim/雨中冒险2）。自动匹配当前游戏的社区，返回带链接的列表，用户挑中后用 download_from_url 下载。无需登录。",
           {"query": {"type": "string", "description": "搜索关键词（留空则按热度列热门 mod）"}},
           []),
        _t("workshop_search", "在 Steam 创意工坊搜索当前游戏的 mod（仅限支持工坊的 Steam 游戏，如 Civ VI/RimWorld/Don't Starve）。返回带 workshop_id 的列表。",
           {"query": {"type": "string", "description": "搜索关键词"}},
           ["query"]),
        _t("github_search", "在 GitHub 搜当前游戏的 mod/工具(很多注入器、脚本框架、UE4SS 类工具型 mod 只发在 GitHub)。自动把当前游戏名并入查询;返回仓库列表(星数/更新时间/是否归档)。结果可能混入非 mod 仓库,凭 summary 判断后再推荐;选中后用 download_from_url 下载(直接吃仓库/releases 链接)。未登录限流约 10 次/分,别连发。",
           {"query": {"type": "string", "description": "搜索关键词(英文效果好,如 minimap / ue4ss / cheat)"}},
           ["query"]),
        _t("gamebanana_search", "在 GameBanana 搜当前游戏的 mod(皮肤/角色/贴图类内容多;FPS/格斗/Sonic/FNF 生态强)。自动匹配当前游戏;返回带链接列表,选中后用 download_from_url 下载。",
           {"query": {"type": "string", "description": "搜索关键词"}},
           ["query"]),
        _t("workshop_install", "订阅安装 Steam 创意工坊 mod（Steam 客户端会自动下载到本地）。⚠️ 安装前必须先征得用户确认。需要 Steam 客户端在运行且浏览器已登录 Steam。",
           {"workshop_id": {"type": "string", "description": "工坊物品 ID（纯数字）"},
            "dependencies": {"type": "array", "items": {"type": "string"},
                             "description": "可选：该 Mod 实际依赖的已安装本地 Mod ID"}},
           ["workshop_id"]),
        _t("workshop_uninstall", "取消订阅一个 Steam 创意工坊 mod（Steam 会移除其文件）。",
           {"workshop_id": {"type": "string"}},
           ["workshop_id"]),
        _t("nexus_get_detail", "获取单个 Mod 的完整详情，包括版本、依赖、安装说明等。安装前必调用。",
           {"mod_id": {"type": "integer", "description": "Mod ID"}},
           ["mod_id"]),
        _t("mod_download", "下载 Mod 文件到本地缓存。通常只需 mod_id；若返回多个变体(variants)，再次调用并传入所选变体的 file_id 即可下载指定变体。",
           {"mod_id": {"type": "integer"},
            "file_id": {"type": "integer", "description": "可选。当 mod 有多个 MAIN 变体时，指定要下载的变体 file_id"}},
           ["mod_id"]),
        _t("batch_download", "批量下载多个 Mod，顺序执行逐一回报进度。",
           {"mods": {"type": "array", "items": {"type": "object", "properties": {
               "mod_id": {"type": "integer"}, "file_id": {"type": "integer"},
               "mod_name": {"type": "string"}, "version": {"type": "string"}},
               "required": ["mod_id", "file_id", "mod_name", "version"]}}},
           ["mods"]),
        _t("mod_install_batch", "批量安装多个已下载的 Mod(整批共享一张安装前快照,单个失败不影响其余)。要装多个 mod 时【必须】用本工具而不是连续调用 mod_install——单轮工具调用有次数上限,连发会被截断。",
           {"mod_ids": {"type": "array", "items": {"type": "string"},
                        "description": "要安装的 mod id 列表(与 mod_install 的 mod_id 同规则)"}},
           ["mod_ids"]),
        _t("mod_install", "安装已下载的 Mod 到游戏目录。只需 mod_id：local_path 不传会自动按 mod_id 找已下载的 zip，snapshot_id 不传会自动建安装前快照。安装多个请改用 mod_install_batch。",
           {"mod_id": {"type": "integer"},
            "local_path": {"type": "string", "description": "可选，已下载的 zip 路径；不传则自动按 mod_id 查找"},
            "snapshot_id": {"type": "string", "description": "可选，已有快照 ID；不传则自动创建"},
            "dependencies": {"type": "array", "items": {"type": "string"},
                             "description": "可选：跨来源场景下，传实际已安装的本地前置 Mod ID"}},
           ["mod_id"]),
        _t("mod_install_custom", "通用安装:开放模式游戏、或自动落位规则接不住的非常规结构包用它。"
           "用法:先 conflict_check 透视包内文件树 + read_readme 读安装说明,自己产出 mapping="
           "{包内相对路径: 游戏内相对路径}(游戏内路径相对游戏根、正斜杠、不含 ..),再调本工具。"
           "代码侧会先把落点登记进快照域再建安装前快照(即便覆盖游戏原文件也能安全回滚),并做"
           "越界/../绝对路径校验;可执行文件落游戏根仅告警不拒绝。",
           {"local_path": {"type": "string", "description": "已下载的 zip 路径(非绝对路径则在下载目录按文件名找)"},
            "mapping": {"type": "object", "description": "{包内相对路径: 游戏内相对路径};包内路径须与 conflict_check 展示的一致"},
            "snapshot_id": {"type": "string", "description": "可选,已有快照 ID;不传自动建安装前快照"},
            "dependencies": {"type": "array", "items": {"type": "string"},
                             "description": "可选：该 Mod 实际依赖的已安装本地 Mod ID"}},
           ["local_path", "mapping"]),
        _t("mod_uninstall", "卸载已安装的 Mod(从游戏目录移除文件;工坊 mod 则退订)。破坏性操作:首次调用返回预览(将删文件数/是否退订/是否有其他 mod 依赖它)并要求确认——把预览展示给用户、得到明确同意后携 confirmed=true 重新调用;未经确认不得自行重调。卸载前自动建快照可回滚。",
           {"mod_id": {"type": "string"},
            "confirmed": {"type": "boolean", "description": "用户已看过卸载预览并明确同意"}},
           ["mod_id"]),
        _t("conflict_check", "检测 Mod 安装后是否与其他已安装 Mod 产生文件冲突。",
           {"local_path": {"type": "string", "description": "下载的 Mod zip 路径"}},
           ["local_path"]),
        _t("list_local_mods", "列出'投放文件夹'和下载缓存里待安装的本地 mod 压缩包(zip/rar/7z)。"
           "用途:安装用户手动下载的 mod——没法自动搜/下的站(三宫六院/3DM/网盘/私享)下好后放进投放"
           "文件夹,调本工具列出,用返回的 path 走 conflict_check 透视 → mod_install_custom 安装。"
           "返回含投放文件夹绝对路径(可告诉用户往哪放)。",
           {}, []),
        _t("snapshot_create", "创建当前游戏文件快照（安装/卸载/修改前必须调用）。全新无 mod 的游戏会创建'原版基线'快照(回滚到它=清空所有 mod)。快照同时记录创意工坊订阅清单(工坊内容在 steamapps 下、不在游戏目录),回滚时会自动同步订阅状态。",
           {"trigger_mod_name": {"type": "string"}},
           ["trigger_mod_name"]),
        _t("snapshot_restore", "回滚游戏文件到指定快照状态(只删快照域内的新增文件,游戏本体永不触碰)。若快照记录了工坊订阅清单,会自动退订快照后新订的、重订被退的;Chrome 不可用时返回 manual_* 清单让用户手动处理。只能回滚当前游戏的快照。开放模式游戏首次调用会返回预览清单(将删除/将还原)并要求确认:把清单展示给用户、征得明确同意后,携 confirmed=true 重新调用。",
           {"snapshot_id": {"type": "string"},
            "confirmed": {"type": "boolean", "description": "开放模式游戏需要:用户已看过预览清单并明确同意回滚"}},
           ["snapshot_id"]),
        _t("snapshot_delete", "删除一个快照(磁盘目录 + DB 记录)。只能删当前游戏的快照;删除不影响已安装的 mod 文件。删除后无法再回滚到该状态,请先向用户确认。",
           {"snapshot_id": {"type": "string"}},
           ["snapshot_id"]),
        _t("snapshot_list", "列出所有快照记录，含时间、触发 Mod、文件数。",
           {}, []),
        _t("mod_patch", "修改 Mod 配置文件中的数值。支持 JSON/INI/CFG/TXT/XML。",
           {"mod_id": {"type": "integer"}, "instruction": {"type": "string"},
            "file_hint": {"type": "string", "description": "可选，目标文件名提示"}},
           ["mod_id", "instruction"]),
        _t("read_readme", "读取 Mod 的 README 或安装说明。支持本地 zip 和 Nexus 在线两种来源。",
           {"mod_id": {"type": "integer", "description": "Mod ID（在线读取）"},
            "archive_path": {"type": "string", "description": "本地 zip 路径（二选一）"}},
           ["mod_id"]),
        _t("game_diagnose", "游戏装了 mod 后出问题(崩溃/黑屏/mod 不生效)时用它诊断:按框架"
           "(BepInEx/MelonLoader/UE4SS)自动定位日志,抓最近的报错/警告,结合已装 mod 清单归因到"
           "具体 mod,给出建议(禁用/更新/补依赖)。纯读取不改任何文件。传 export=true 会额外生成一个"
           "脱敏诊断包 zip(框架日志+操作记录+版本环境,绝不含任何 API key)供用户手动上报给开发者。",
           {"export": {"type": "boolean", "description": "true=额外生成脱敏诊断包 zip"}}, []),
        _t("mod_update_check", "检查已安装 Mod 是否有新版本可更新。",
           {}, []),
        _t("mod_update", "更新指定 Mod 到最新版本。",
           {"mod_id": {"type": "string"}},
           ["mod_id"]),
        _t("scan_games", "扫描本机所有 Steam 游戏，匹配 Nexus 已知游戏。",
           {}, []),
        _t("get_installed", "列出当前游戏已安装的所有 Mod。",
           {}, []),
        _t("game_file_check", "只读诊断:检查游戏目录内某文件/文件夹是否存在,返回大小与修改时间;"
           "对文本文件可读取末尾若干行(如查看 SB/Binaries/Win64/ue4ss/UE4SS.log 判断 UE4SS 是否被游戏加载)。"
           "path 为相对游戏根目录的路径,禁止越界。",
           {"path": {"type": "string", "description": "相对游戏根目录的路径,如 SB/Binaries/Win64/ue4ss/UE4SS.log"},
            "tail": {"type": "integer", "description": "可选:读取文本文件末尾 N 行(上限200)"}}, ["path"]),
        _t("list_downloads", "列出当前游戏【下载缓存目录】里已下载的所有 mod 压缩包(文件名、mod_id、大小)。"
           "用户说\"把我下好的都装上\"这类批量安装需求时,先调此工具看清有哪些已下载文件,再逐个 mod_install,"
           "不要反过来让用户手动列出文件清单。",
           {}, []),
        _t("mod_disable", "禁用一个 Mod；若有其他 Mod 依赖它，必须先确认并级联禁用依赖链。",
           {"mod_id": {"type": "string"},
            "confirmed": {"type": "boolean", "description": "用户确认依赖影响后传 true"}}, ["mod_id"]),
        _t("mod_enable", "启用一个被禁用的 Mod；若有依赖，必须先确认并按顺序启用已安装依赖。",
           {"mod_id": {"type": "string"},
            "confirmed": {"type": "boolean", "description": "用户确认依赖启用计划后传 true"}}, ["mod_id"]),
        _t("mod_dependency_set", "修复跨来源依赖映射：把目标 Mod 的前置依赖明确关联到已安装的本地 Mod ID。首次调用仅返回预览，用户确认后携 confirmed=true 重调。",
           {"mod_id": {"type": "string"},
            "dependencies": {"type": "array", "items": {"type": "string"}},
            "confirmed": {"type": "boolean", "description": "用户已确认依赖映射"}},
           ["mod_id", "dependencies"]),
    ]
    return all_tools


def _t(name: str, desc: str, props: dict, required: list[str]) -> dict:
    return {"type": "function", "function": {
        "name": name, "description": desc,
        "parameters": {"type": "object", "properties": props, "required": required},
    }}


def _mod_files(mod) -> list:
    try:
        value = json.loads(mod.files_installed) if isinstance(mod.files_installed, str) else (mod.files_installed or [])
        return value if isinstance(value, list) else []
    except (TypeError, ValueError, json.JSONDecodeError):
        return []


def _toggle_mod_info(mod, disabled=None) -> dict:
    info = {"id": str(mod.id), "name": mod.name, "version": mod.version}
    info["disabled"] = installer.is_mod_disabled(_mod_files(mod)) if disabled is None else disabled
    return info


def _validate_local_dependencies(value, game_slug: str, target_id: str = "") -> tuple[list[str], list[str]]:
    dependency_ids = db.parse_dependencies(value)
    missing = []
    valid = []
    for dependency_id in dependency_ids:
        if dependency_id == str(target_id) or not db.get_mod(dependency_id, game_slug):
            missing.append(dependency_id)
        else:
            valid.append(dependency_id)
    return valid, missing


def _execute_toggle_plan(mods, enabling: bool) -> dict:
    """Preflight and execute a toggle chain; roll back newly renamed files on failure."""
    issues = []
    for mod in mods:
        for tracked in _mod_files(mod):
            original = tracked[:-9] if tracked.endswith(".disabled") else tracked
            disabled = original + ".disabled"
            original_exists = os.path.exists(original)
            disabled_exists = os.path.exists(disabled)
            if not original_exists and not disabled_exists:
                issues.append({"mod_id": mod.id, "file": original, "problem": "文件不存在"})
            elif original_exists and disabled_exists:
                issues.append({"mod_id": mod.id, "file": original, "problem": "启用版与禁用版同时存在"})
    if issues:
        return {"error": "依赖链文件状态异常，操作前预检未通过；请先执行 Mod 对账。",
                "preflight_failed": issues[:20]}

    details = []
    changed = []
    operation = installer.enable_mod if enabling else installer.disable_mod
    for mod in mods:
        result = operation(_mod_files(mod))
        details.append({"mod_id": mod.id, "name": mod.name, **result})
        changed.extend(result.get("changed", []))
        if result.get("errors") or result.get("not_found"):
            rollback = (installer.disable_mod if enabling else installer.enable_mod)(list(reversed(changed)))
            rollback_failed = bool(rollback.get("errors") or rollback.get("not_found"))
            return {
                "error": "文件启停过程中发生错误；已尝试撤销本轮变更。",
                "rolled_back": not rollback_failed,
                "details": details,
                "rollback": rollback,
            }
    return {"details": details}


def execute(name: str, args: dict, cfg: Config) -> str:
    api_key = cfg.nexus_api_key
    slug = cfg.game_slug
    gid = cfg.game_id
    root = cfg.game_root

    # T00 - scan existing mods in game directory
    if name == "scan_existing_mods":
        if not root:
            return json.dumps({"error": "请先选择游戏目录"}, ensure_ascii=False)
        result = scanner.scan_existing_mods(root, slug, api_key)
        identified = result.get("identified", [])
        if identified:
            scanner.import_mods(identified)
        return json.dumps(result, indent=2, ensure_ascii=False)

    elif name == "import_existing_mods":
        count = scanner.import_mods(args.get("mods", []))
        return json.dumps({"imported": count, "note": "已导入，标记为 imported"}, ensure_ascii=False)

    # T01
    elif name == "mod_recommend":
        return json.dumps(_recommend(args.get("query", ""), cfg), indent=2, ensure_ascii=False)

    # T02
    elif name == "nexus_search":
        import re as _re
        q = (args.get("query") or "").strip()
        # 粘贴 Nexus 链接或直接给 mod_id → 绕过受限的搜索索引，直接解析详情
        m = _re.search(r"nexusmods\.com/(?:games/)?[\w-]+/mods/(\d+)", q) or _re.fullmatch(r"\d{2,7}", q)
        if m:
            mid = int(m.group(1) if m.lastindex else m.group(0))
            try:
                d = nexus.get_detail(mid, slug, api_key, cdp_port=cfg.chrome_cdp_port)
                return json.dumps({"direct": True, "results": [{
                    "mod_id": d.get("mod_id"), "name": d.get("name"), "summary": d.get("summary", ""),
                    "version": d.get("version", ""), "file_id": d.get("file_id"),
                }]}, indent=2, ensure_ascii=False)
            except Exception as e:
                return json.dumps({"error": f"按 ID/链接获取详情失败: {e}"}, ensure_ascii=False)
        results = nexus.search(q, slug, api_key, cdp_port=cfg.chrome_cdp_port, game_id=gid, tavily_key=cfg.tavily_api_key)
        if not results:
            return json.dumps({"error": "未找到匹配的 Mod。Nexus 搜索索引只覆盖近期更新的 mod，老/热门 mod（如服装、身体类）常搜不到。请直接粘贴该 mod 的 Nexus 链接或 mod_id 数字，我可以直接获取。"}, ensure_ascii=False)
        return json.dumps([{
            "mod_id": r.get("mod_id"), "name": r.get("name"), "summary": r.get("summary", ""),
            "endorsements": r.get("endorsement_count", 0), "version": r.get("version", ""),
            "updated": r.get("updated_time", ""),
        } for r in results[:10]], indent=2, ensure_ascii=False)

    elif name == "collection_view":
        import re as _re
        raw = (args.get("collection") or "").strip()
        m = _re.search(r"collections/([A-Za-z0-9]+)", raw)
        cslug = m.group(1) if m else raw
        if not cslug:
            return json.dumps({"error": "请提供合集 slug 或合集 URL"}, ensure_ascii=False)
        data = asyncio.run(downloader.fetch_collection_cdp(cslug, cfg.chrome_cdp_port))
        if not data:
            return json.dumps({"error": f"无法读取合集 {cslug}：请确认 Chrome 已登录 Nexus，且合集 slug/链接正确。"}, ensure_ascii=False)
        return json.dumps(data, ensure_ascii=False, indent=2)

    elif name == "thunderstore_search":
        from .sources import thunderstore
        q = (args.get("query") or "").strip()
        try:
            comm = thunderstore.find_community(cfg.game_name)
        except Exception as e:
            return json.dumps({"error": f"获取 Thunderstore 社区失败: {e}"}, ensure_ascii=False)
        if not comm:
            return json.dumps({"error": f"《{cfg.game_name}》似乎不在 Thunderstore 上（社区名未匹配）。"}, ensure_ascii=False)
        try:
            results = thunderstore.search(comm, q)
        except Exception as e:
            return json.dumps({"error": f"Thunderstore 搜索失败: {e}"}, ensure_ascii=False)
        if not results:
            return json.dumps({"note": f"在 Thunderstore「{comm}」社区没搜到「{q}」。", "community": comm, "results": []}, ensure_ascii=False)
        return json.dumps({"community": comm, "results": results}, ensure_ascii=False, indent=2)

    elif name == "workshop_search":
        from .sources import steam_workshop as sw
        appid = sw.resolve_appid(root)
        if not appid:
            return json.dumps({"error": "无法解析当前游戏的 Steam AppID（可能不是 Steam 安装，或未选游戏）"}, ensure_ascii=False)
        try:
            results = asyncio.run(sw.search(args.get("query", ""), appid, cfg.chrome_cdp_port))
        except Exception as e:
            return json.dumps({"error": f"工坊搜索失败: {e}"}, ensure_ascii=False)
        if not results:
            return json.dumps({"appid": appid, "results": [], "note": "没搜到（或该游戏没有创意工坊内容）"}, ensure_ascii=False)
        return json.dumps({"appid": appid, "results": results}, ensure_ascii=False, indent=2)

    elif name == "github_search":
        from .sources import github as gh
        q = (args.get("query") or "").strip()
        if not q:
            return json.dumps({"error": "请提供搜索关键词"}, ensure_ascii=False)
        try:
            results = gh.search(q, getattr(cfg, "game_name", "") or slug)
        except RuntimeError as e:
            return json.dumps({"error": str(e)}, ensure_ascii=False)
        if not results:
            return json.dumps({"note": f"GitHub 没搜到「{q}」相关仓库(已并入当前游戏名限定)。",
                               "results": []}, ensure_ascii=False)
        return json.dumps({"results": results,
                           "note": "结果可能混入非 mod 仓库(工具/教程),凭 summary/星数判断后再推荐;"
                                   "archived=true 表示作者已弃更。下载:download_from_url 直接吃仓库链接。"},
                          ensure_ascii=False, indent=1)

    elif name == "gamebanana_search":
        from .sources import gamebanana as gb
        q = (args.get("query") or "").strip()
        game_name = getattr(cfg, "game_name", "") or ""
        gid = gb.find_game(game_name)
        if not gid:
            return json.dumps({"note": f"GameBanana 没匹配到游戏「{game_name}」(未收录或站点不可达),"
                                       "换其他来源搜吧。", "results": []}, ensure_ascii=False)
        try:
            results = gb.search(gid, q)
        except Exception as e:
            return json.dumps({"error": f"GameBanana 搜索失败: {e}"}, ensure_ascii=False)
        if not results:
            return json.dumps({"note": f"GameBanana 的「{game_name}」板块没搜到「{q}」。",
                               "results": [], "game_id": gid}, ensure_ascii=False)
        return json.dumps({"game_id": gid, "results": results,
                           "note": "has_files=false 的条目没有可下载文件;下载:download_from_url 吃 url。"},
                          ensure_ascii=False, indent=1)

    elif name == "workshop_install":
        import re as _re
        from .sources import steam_workshop as sw
        appid = sw.resolve_appid(root)
        if not appid:
            return json.dumps({"error": "无法解析 Steam AppID"}, ensure_ascii=False)
        wid = _re.sub(r"\D", "", str(args.get("workshop_id", "")))
        if not wid:
            return json.dumps({"error": "请提供 workshop_id（纯数字）"}, ensure_ascii=False)
        explicit_deps = None
        if "dependencies" in args:
            explicit_deps, missing_deps = _validate_local_dependencies(
                args.get("dependencies"), slug, "ws_" + wid)
            if missing_deps:
                return json.dumps({"error": "依赖映射包含未安装的本地 Mod ID",
                                   "missing_dependencies": missing_deps}, ensure_ascii=False)
        try:
            sub = asyncio.run(sw.subscribe(wid, appid, cfg.chrome_cdp_port))
        except Exception as e:
            return json.dumps({"error": f"订阅失败: {e}"}, ensure_ascii=False)
        if not sub.get("ok"):
            return json.dumps({"error": f"订阅失败（status={sub.get('status')} {sub.get('error', '')}）。请确认 Chrome 已登录 Steam 且账号拥有该游戏。"}, ensure_ascii=False)
        key = "ws_" + wid
        progress.start([{"mod_id": key, "name": f"工坊 {wid}（Steam 下载中）"}])
        progress.set_status(key, "downloading")
        dl = asyncio.run(sw.wait_for_download(root, appid, wid, timeout=180,
                                              progress_callback=lambda f: progress.set_pct(key, int(f * 100))))
        progress.set_status(key, "done" if dl.get("downloaded") else "failed",
                            "" if dl.get("downloaded") else "Steam 未在限时内下完，请确认 Steam 客户端在运行")
        progress.finish()
        mod = db.InstalledMod(
            id=key, name=f"Workshop {wid}", version="", snapshot_id="",
            load_order=db.get_max_load_order(slug) + 1, file_id=int(wid) if wid.isdigit() else 0,
            files_installed=json.dumps(dl.get("files", [])),
            dependencies=json.dumps(explicit_deps or []),
            installed_by="steam_workshop", game_slug=slug)
        db.add_mod(mod)
        return json.dumps({"workshop_id": wid, "subscribed": True, "downloaded": dl.get("downloaded", False),
                           "files": len(dl.get("files", [])), "path": dl.get("path", ""),
                           "note": "工坊 mod 由 Steam 管理,存放在 steamapps\\workshop\\content\\ 下,不在游戏目录;"
                                   "撤销方式是退订(workshop_uninstall)。快照会记录订阅清单,回滚时自动同步订阅状态。"},
                          ensure_ascii=False)

    elif name == "workshop_uninstall":
        import re as _re
        from .sources import steam_workshop as sw
        appid = sw.resolve_appid(root)
        wid = _re.sub(r"\D", "", str(args.get("workshop_id", "")))
        res = {"ok": False}
        if appid and wid:
            try:
                res = asyncio.run(sw.unsubscribe(wid, appid, cfg.chrome_cdp_port))
            except Exception as e:
                return json.dumps({"error": f"取消订阅失败: {e}"}, ensure_ascii=False)
        db.remove_mod("ws_" + wid, slug)
        return json.dumps({"workshop_id": wid, "unsubscribed": res.get("ok", False)}, ensure_ascii=False)

    elif name == "download_from_url":
        if not Tier.can(cfg.tier, "download"):
            return json.dumps({"error": "当前层级不支持下载"}, ensure_ascii=False)
        from . import sources
        url = (args.get("url") or "").strip()
        if not url:
            return json.dumps({"error": "请提供 GitHub/Thunderstore/GameBanana 链接"}, ensure_ascii=False)
        gh_note = None
        # GitHub releases 页面/仓库链接 → 自动解析出正式版 zip 直链(免用户手动复制资产地址)
        if "github.com/" in url and "/releases/download/" not in url:
            gh = _resolve_github_release_url(url)
            if gh.get("error"):
                return json.dumps({"error": f"GitHub 链接解析失败: {gh['error']}。"
                                   f"你也可以直接粘贴 releases 页面里 .zip 资产的下载地址。"}, ensure_ascii=False)
            url = gh["url"]
            gh_note = gh.get("note")
        key = "url"
        progress.start([{"mod_id": key, "name": url[:48]}])
        progress.set_status(key, "downloading")
        try:
            r = sources.download_from_url(url, slug, progress_callback=lambda f: progress.set_pct(key, int(f * 100)))
        except Exception as e:
            progress.set_status(key, "failed", str(e))
            progress.finish()
            return json.dumps({"error": f"下载失败: {e}"}, ensure_ascii=False)
        progress.set_name(key, r.get("name", ""))
        progress.set_status(key, "done")
        progress.finish()
        path = os.path.abspath(r.get("local_path", ""))
        return json.dumps({
            "local_path": path, "name": r.get("name", ""), "source": r.get("source", ""),
            "version": r.get("version", ""),
            "github_resolved": gh_note,
            "file_size_mb": round(os.path.getsize(path) / 1048576, 1) if path and os.path.exists(path) else 0,
        }, ensure_ascii=False)

    # T03
    elif name == "nexus_get_detail":
        detail = nexus.get_detail(args["mod_id"], slug, api_key, cdp_port=cfg.chrome_cdp_port)
        return json.dumps(detail, indent=2, ensure_ascii=False)

    # T04
    elif name == "mod_download":
        if not Tier.can(cfg.tier, "download"):
            return json.dumps({"error": "当前层级不支持下载", "suggestion": "升级到 Pro 订阅"}, ensure_ascii=False)
        _mid = args["mod_id"]
        progress.start([{"mod_id": _mid, "name": f"mod {_mid}"}])
        progress.set_status(_mid, "downloading")
        try:
            result = asyncio.run(downloader.download_mod(
                mod_id=_mid, game_slug=slug, game_id=gid,
                api_key=api_key, cdp_port=cfg.chrome_cdp_port,
                progress_callback=lambda f: progress.set_pct(_mid, int(f * 100)),
                file_id=args.get("file_id")))
        except Exception as e:
            progress.set_status(_mid, "failed", str(e))
            progress.finish()
            return json.dumps({"error": f"mod_download 执行失败: {e}"}, ensure_ascii=False)
        if not result.get("variants"):
            progress.set_name(_mid, result.get("mod_name", "") or f"mod {_mid}")
            progress.set_status(_mid, "done")
        progress.finish()
        if result.get("variants"):
            variants = [{"file_id": v.get("file_id"), "name": v.get("name", ""),
                         "version": v.get("version", ""), "size_kb": v.get("size_kb", v.get("size", 0))}
                        for v in result["variants"]]
            return json.dumps({
                "variants": variants,
                "note": "该 Mod 有多个 MAIN 变体，请选择其一后再次调用 mod_download，并传入对应的 file_id。",
                "mod_id": result.get("mod_id"),
            }, ensure_ascii=False)
        path = os.path.abspath(result.get("local_path", ""))
        return json.dumps({"mod_id": result.get("mod_id"), "local_path": path, "mod_name": result.get("mod_name", ""),
                           "version": result.get("version", ""), "cached": result.get("cached", False),
                           "file_size_mb": round(os.path.getsize(path) / 1048576, 1) if path and os.path.exists(path) else 0}, ensure_ascii=False)

    # T05
    elif name == "batch_download":
        mods = args.get("mods", [])
        success, failed = [], []
        progress.start([{"mod_id": m["mod_id"], "name": m.get("mod_name", "")} for m in mods])

        async def _batch():
            for m in mods:
                mid = m["mod_id"]
                progress.set_status(mid, "downloading")
                try:
                    await downloader.download_mod(
                        mod_id=mid, game_slug=slug, game_id=gid,
                        api_key=api_key, cdp_port=cfg.chrome_cdp_port,
                        progress_callback=lambda f, _m=mid: progress.set_pct(_m, int(f * 100)))
                    progress.set_status(mid, "done")
                    success.append(mid)
                except Exception as e:
                    progress.set_status(mid, "failed", str(e))
                    failed.append({"mod_id": mid, "error": str(e)})

        asyncio.run(_batch())
        progress.finish()
        return json.dumps({"success": success, "failed": failed}, ensure_ascii=False)

    # T06
    elif name == "mod_install_batch":
        if not Tier.can(cfg.tier, "install"):
            return json.dumps({"error": "当前层级不支持安装"}, ensure_ascii=False)
        ids = args.get("mod_ids") or []
        if not isinstance(ids, list) or not ids:
            return json.dumps({"error": "请提供 mod_ids 列表"}, ensure_ascii=False)
        if len(ids) > 30:
            return json.dumps({"error": f"单批最多 30 个(收到 {len(ids)}),请分批"}, ensure_ascii=False)
        # 整批共享一张安装前快照(治 22 连发时每装一个拍一张的浪费)
        try:
            batch_snap = snapshot.snapshot_create(root, slug,
                                                  trigger_mod_name=f"批量安装 {len(ids)} 个前")
        except (ValueError, FileNotFoundError, RuntimeError) as e:
            return json.dumps({"error": f"批量安装前快照失败,安装未开始: {e}"}, ensure_ascii=False)
        results = []
        for mid in ids:
            r = json.loads(execute("mod_install", {"mod_id": mid, "snapshot_id": batch_snap}, cfg))
            if "error" in r:
                results.append({"mod_id": mid, "ok": False, "error": r["error"]})
            else:
                results.append({"mod_id": mid, "ok": True, "name": r.get("name", ""),
                                "files": len(r.get("files_installed", []))})
        ok_n = sum(1 for r in results if r["ok"])
        return json.dumps({"snapshot_id": batch_snap, "total": len(ids), "succeeded": ok_n,
                           "failed": len(ids) - ok_n, "results": results},
                          ensure_ascii=False, indent=1)

    elif name == "mod_install":
        if not Tier.can(cfg.tier, "install"):
            return json.dumps({"error": "当前层级不支持安装"}, ensure_ascii=False)
        mid = args.get("mod_id")
        local_path = args.get("local_path") or ""
        if local_path and not os.path.isabs(local_path):
            local_path = os.path.join(downloader.DOWNLOADS_DIR, slug, os.path.basename(local_path))
        # Nexus mod：可只给 mod_id，自动在下载目录里找
        if (not local_path or not os.path.exists(local_path)) and mid not in (None, ""):
            matches = glob.glob(os.path.join(downloader.DOWNLOADS_DIR, slug, f"{mid}_*.zip"))
            if matches:
                local_path = matches[0]
        if not local_path or not os.path.exists(local_path):
            return json.dumps({
                "error": "未找到要安装的文件。请先用 mod_download（Nexus）或 download_from_url（GitHub/Thunderstore/GameBanana）下载，再用返回的 local_path 安装。",
            }, ensure_ascii=False)
        # 非 Nexus 来源没有 mod_id → 用文件名生成本地 id
        if mid in (None, ""):
            mid = "src_" + os.path.splitext(os.path.basename(local_path))[0][:48]
        explicit_deps = None
        if "dependencies" in args:
            explicit_deps, missing_deps = _validate_local_dependencies(args.get("dependencies"), slug, str(mid))
            if missing_deps:
                return json.dumps({"error": "依赖映射包含未安装的本地 Mod ID",
                                   "missing_dependencies": missing_deps}, ensure_ascii=False)

        # ── 活体守卫:拒绝把 mod 装进卸载残骸/空壳目录 ──
        # (根因防护:游戏卸载后目录残留,若配置仍指向它,安装会"成功"却永不生效——
        #  N 键三个月无反应的总根源就是装进了 E 盘的空壳。)
        alive = games_mod.verify_game_alive(root)
        if not alive.get("alive"):
            return json.dumps({
                "error": f"拒绝安装:当前游戏目录未通过活体检测。{alive.get('reason','')}",
                "game_root": root,
                "hint": "该目录可能是游戏卸载后的残骸,或路径已失效。请在设置中把游戏根目录"
                        "更正为真实安装位置(可用游戏体检/重新检测),确认能找到游戏本体 exe 后再安装。",
            }, ensure_ascii=False)

        snap_id = args.get("snapshot_id", "")
        if not snap_id:
            snap_id = snapshot.snapshot_create(root, slug, trigger_mod_name=f"安装前快照")
        lo = db.get_max_load_order(slug) + 1
        result = installer.install_mod(local_path, root, slug, lo)
        files_installed = [f["dest"] for f in result.get("installed", [])]
        # 自动落位规则没接住任何文件(开放模式/非常规结构包)→ 引导 agent 走通用安装,不写空账
        if not files_installed:
            return json.dumps({
                "snapshot_id": snap_id, "installed": 0,
                "skipped": result.get("skipped", [])[:50],
                "notes": result.get("notes", []),
                "hint": "没有文件匹配到自动落位规则(可能是开放模式游戏或非常规包结构)。"
                        "请用 conflict_check 透视包内文件树 + read_readme 读安装说明,产出 "
                        "{包内相对路径: 游戏内相对路径} 映射,改用 mod_install_custom 安装。",
            }, ensure_ascii=False, indent=1)
        mod_name = ""
        mod_ver = ""
        mod_deps = []
        if str(mid).isdigit():  # 仅 Nexus 数字 id 才查 Nexus 名称
            try:
                info = nexus.get_mod(int(mid), slug, api_key, cdp_port=cfg.chrome_cdp_port)
                mod_name = info.get("name", "")
                mod_ver = info.get("version", "")
                mod_deps = db.parse_dependencies(info.get("dependencies", []))
            except Exception:
                pass
        if explicit_deps is not None:
            mod_deps = explicit_deps
        if not mod_name:
            mod_name = os.path.splitext(os.path.basename(local_path))[0]
        mod = db.InstalledMod(
            id=str(mid), name=mod_name, version=mod_ver, snapshot_id=snap_id,
            load_order=lo, file_id=0, files_installed=json.dumps(files_installed),
            dependencies=json.dumps(mod_deps),
            game_slug=slug,
        )
        db.add_mod(mod)
        return json.dumps({"snapshot_id": snap_id, "files_installed": files_installed,
                           "load_order": lo, "name": mod_name, "warnings": result.get("errors", [])}, indent=2, ensure_ascii=False)

    # T06b:通用安装(显式 mapping)——开放模式/非常规结构包
    elif name == "mod_install_custom":
        if not Tier.can(cfg.tier, "install"):
            return json.dumps({"error": "当前层级不支持安装"}, ensure_ascii=False)
        local_path = args.get("local_path") or ""
        if local_path and not os.path.isabs(local_path):
            local_path = os.path.join(downloader.DOWNLOADS_DIR, slug, os.path.basename(local_path))
        if not local_path or not os.path.exists(local_path):
            return json.dumps({
                "error": "未找到要安装的文件。请先下载,再用返回的 local_path 调本工具。"},
                ensure_ascii=False)
        mapping = args.get("mapping")
        if not isinstance(mapping, dict) or not mapping:
            return json.dumps({
                "error": "mapping 不能为空。请先用 conflict_check 透视文件树 + read_readme 读说明,"
                         "产出 {包内相对路径: 游戏内相对路径} 再调本工具。"}, ensure_ascii=False)

        # 活体守卫(同 mod_install:拒绝装进卸载残骸/空壳目录)
        alive = games_mod.verify_game_alive(root)
        if not alive.get("alive"):
            return json.dumps({
                "error": f"拒绝安装:当前游戏目录未通过活体检测。{alive.get('reason','')}",
                "hint": "请在设置中把游戏根目录更正为真实安装位置后再装。"}, ensure_ascii=False)

        mid = "custom_" + os.path.splitext(os.path.basename(local_path))[0][:40]
        explicit_deps = None
        if "dependencies" in args:
            explicit_deps, missing_deps = _validate_local_dependencies(args.get("dependencies"), slug, mid)
            if missing_deps:
                return json.dumps({"error": "依赖映射包含未安装的本地 Mod ID",
                                   "missing_dependencies": missing_deps}, ensure_ascii=False)

        # ── 关键顺序(snapshot 第1块测试证明,错序会丢游戏原文件)──
        # ① 先把合法落点登记进快照域 → ② 建安装前快照(覆盖类的游戏原文件因此入快照受保护)
        # → ③ 落位。plan 只做路径校验(不解压),与 install_mod_custom 内部共用同一校验。
        plan = installer.plan_custom_targets(root, mapping)
        if plan["valid"]:
            db.add_custom_domain_files(slug, plan["valid"])
        snap_id = args.get("snapshot_id") or snapshot.snapshot_create(
            root, slug, trigger_mod_name=f"{mid} 自定义安装前")

        result = installer.install_mod_custom(local_path, root, slug, mapping)
        files_installed = [i["dest"] for i in result.get("installed", [])]

        if not files_installed:
            return json.dumps({
                "error": "没有文件成功安装(全部被校验拦下或包内缺失)。",
                "snapshot_id": snap_id,
                "skipped": result.get("skipped", []),
                "rejected": plan.get("rejected", []),
                "warnings": result.get("warnings", [])}, ensure_ascii=False, indent=1)

        db.add_mod(db.InstalledMod(
            id=mid, name=mid, version="", snapshot_id=snap_id,
            load_order=db.get_max_load_order(slug) + 1,
            files_installed=json.dumps(files_installed),
            dependencies=json.dumps(explicit_deps or []),
            installed_by="custom", game_slug=slug,
        ))
        return json.dumps({
            "snapshot_id": snap_id, "installed": len(files_installed),
            "files_installed": files_installed,
            "custom_domain_registered": sorted(i["rel"] for i in result.get("installed", [])),
            "skipped": result.get("skipped", []),
            "rejected": plan.get("rejected", []),
            "warnings": result.get("warnings", []),
            "name": mid}, ensure_ascii=False, indent=1)

    # T07
    elif name == "mod_uninstall":
        if not Tier.can(cfg.tier, "install"):
            return json.dumps({"error": "当前层级不支持卸载"}, ensure_ascii=False)
        mid = args["mod_id"]
        mod = db.get_mod(mid, slug)
        if not mod:
            return json.dumps({"error": f"未找到 Mod: {mid}"}, ensure_ascii=False)

        is_ws = str(mid).startswith("ws_")
        deps = db.get_dependents(mid, slug)
        # ── 卸载确认门(破坏性操作,确定性守门放代码,同 snapshot_restore 回滚预览门)──
        # 不带 confirmed 先返回预览;安装有确认门,卸载更该有(对称保护)。
        if not args.get("confirmed"):
            _files = ([] if is_ws else
                      (json.loads(mod.files_installed) if isinstance(mod.files_installed, str)
                       else (mod.files_installed or [])))
            return json.dumps({
                "requires_confirmation": True,
                "mod_id": mid, "mod_name": mod.name,
                "kind": "工坊订阅(卸载=退订)" if is_ws else "本地文件",
                "will_unsubscribe": is_ws,
                "will_delete_count": len(_files),
                "will_delete_sample": [str(f) for f in _files[:20]],
                "dependents": [d["name"] for d in deps],
                "note": ("卸载前会自动建快照,可回滚。"
                         + (f"⚠️ 有 {len(deps)} 个 mod 依赖它("
                            + "、".join(d["name"] for d in deps) + "),卸载可能导致它们失效。"
                            if deps else "")
                         + "请把以上影响展示给用户,得到明确同意后携 confirmed=true 重新调用;"
                           "未经用户确认不得自行重调。"),
            }, ensure_ascii=False, indent=1)

        # Steam 工坊 mod：卸载 = 取消订阅（Steam 托管文件，不能直接删）
        if is_ws:
            import re as _re
            from .sources import steam_workshop as sw
            appid = sw.resolve_appid(root)
            wid = _re.sub(r"\D", "", str(mid))
            res = {"ok": False}
            if appid and wid:
                try:
                    res = asyncio.run(sw.unsubscribe(wid, appid, cfg.chrome_cdp_port))
                except Exception as e:
                    return json.dumps({"error": f"取消订阅失败: {e}"}, ensure_ascii=False)
            db.remove_mod(mid, slug)
            return json.dumps({"workshop_id": wid, "unsubscribed": res.get("ok", False),
                               "note": "已从 Steam 取消订阅" if res.get("ok") else "已移除记录（取消订阅可能未生效，请确认已登录 Steam）"}, ensure_ascii=False)
        files = json.loads(mod.files_installed) if isinstance(mod.files_installed, str) else (mod.files_installed or [])
        snap_id = snapshot.snapshot_create(root, slug, trigger_mod_name=f"{mod.name} 卸载前")
        shared = db.get_shared_files(mid, files, slug)
        result = installer.uninstall_mod(mid, root, files, game_slug=slug, shared_files=shared)
        db.remove_mod(mid, slug)
        return json.dumps({"removed": len(result["removed"]),
                           "kept_shared": len(result.get("kept_shared", [])),
                           "snapshot_id": snap_id,
                           "dependents_warned": [d["name"] for d in deps],
                           "details": result}, indent=2, ensure_ascii=False)

    # T08
    elif name == "conflict_check":
        result = installer.conflict_check(args["local_path"], root, slug)
        return json.dumps(result, indent=2, ensure_ascii=False)

    # T08b:列出投放文件夹 + 下载缓存里的本地 mod 压缩包(手动下载资源的入口)
    elif name == "list_local_mods":
        dropbox = downloader.ensure_dropbox_dir(slug)
        result, seen = [], set()
        for d, label in ((dropbox, "投放文件夹"),
                         (os.path.join(downloader.DOWNLOADS_DIR, slug), "下载缓存")):
            if not os.path.isdir(d):
                continue
            for f in sorted(os.listdir(d)):
                full = os.path.join(d, f)
                if not (os.path.isfile(full) and f.lower().endswith((".zip", ".rar", ".7z"))):
                    continue
                if f.lower() in seen:
                    continue
                seen.add(f.lower())
                try:
                    sz = round(os.path.getsize(full) / 1048576, 1)
                except OSError:
                    sz = 0
                result.append({"name": f, "path": full, "size_mb": sz, "source": label})
        out = {"local_mods": result, "dropbox_path": dropbox}
        if not result:
            out["note"] = (f"投放文件夹和下载缓存里没有 mod 压缩包。请让用户把手动下载好的 mod"
                           f"(zip/rar/7z)放进投放文件夹: {dropbox},放好后重试。")
        return json.dumps(out, ensure_ascii=False, indent=1)

    # T09
    elif name == "snapshot_create":
        sid = snapshot.snapshot_create(root, slug, trigger_mod_name=args.get("trigger_mod_name", ""))
        return json.dumps({"snapshot_id": sid}, ensure_ascii=False)

    # T10
    elif name == "snapshot_restore":
        # 跨游戏回滚守卫:restore 按 manifest 的 game_root 动手,当前游戏是 A 时
        # 回滚 B 的快照会去改 B 的目录——行为正确但极易造成用户/agent 认知混乱,拒绝。
        _snap = db.get_snapshot(args["snapshot_id"])
        if _snap is not None and _snap.game_slug and _snap.game_slug != slug:
            return json.dumps({
                "error": f"快照 {args['snapshot_id']} 属于游戏 {_snap.game_slug},当前游戏是 {slug}。"
                         "跨游戏回滚已拒绝;请先切换到对应游戏再回滚。"}, ensure_ascii=False)
        # 开放模式(嗅探域)强制预览确认:快照域来自目录名嗅探、无人工核对,
        # "将删除"清单必须先过用户的眼(确定性守门放代码,不赌 agent 自觉)。
        if slug not in snapshot.GAME_SNAPSHOT_SPECS and not args.get("confirmed"):
            pv = snapshot.snapshot_restore_preview(args["snapshot_id"])
            cap = 50
            for k in ("to_delete", "to_restore", "missing_in_snapshot"):
                if len(pv.get(k) or []) > cap:
                    total = len(pv[k])
                    pv[k] = pv[k][:cap] + [f"...(共 {total} 个,已截断)"]
            return json.dumps({
                "requires_confirmation": True,
                "preview": pv,
                "note": "该游戏为开放模式(快照域来自目录嗅探)。请把「将删除/将还原」清单原样展示给用户,"
                        "得到明确同意后再携 confirmed=true 重新调用 snapshot_restore;未经用户确认不得自行重调。",
            }, ensure_ascii=False, indent=2)
        res = snapshot.snapshot_restore(args["snapshot_id"])
        ws = res.get("workshop") or {}
        # 被自动退订的工坊 mod,同步清掉 DB 记录(账本跟事实走)
        for pid in ws.get("unsubscribed", []):
            db.remove_mod("ws_" + pid, slug)
        # 回滚联动清账:快照后安装的 mod 文件刚被回滚删掉,DB 记录不能留成幽灵账。
        # 判定 = 记录里有文件、且所有文件在磁盘上都不存在(连 .disabled 禁用副本也没有)。
        # 工坊 mod 不在此列(文件由 Steam 托管,上面按订阅差集单独处理)。
        mods_cleaned = []
        for m in db.get_installed_mods(slug):
            if str(m.id).startswith("ws_"):
                continue
            try:
                mfiles = json.loads(m.files_installed or "[]")
            except Exception:
                mfiles = []
            if mfiles and all(not os.path.exists(f) and not os.path.exists(f + ".disabled")
                              for f in mfiles):
                db.remove_mod(m.id, slug)
                mods_cleaned.append({"id": m.id, "name": m.name})
        out = {"snapshot_id": args["snapshot_id"],
               "deleted": res.get("deleted", 0),
               "restored": res.get("restored", 0),
               "files_restored": res.get("files_restored", 0),
               "mods_cleaned": mods_cleaned,
               "workshop": res.get("workshop")}
        _failed = res.get("failed") or {}
        _all_failed = _failed.get("delete", []) + _failed.get("restore", [])
        if _all_failed:
            out["failed"] = _failed
            lead = _all_failed[0]   # 同一次回滚的失败通常同因(游戏在跑),取首项归因作主导建议
            out["warning"] = (f"{len(_all_failed)} 个文件操作失败({lead.get('reason','未知原因')}),"
                              f"回滚不完整。{lead.get('action','')}")
        return json.dumps(out, ensure_ascii=False)

    elif name == "snapshot_delete":
        _snap = db.get_snapshot(args["snapshot_id"])
        if _snap is None:
            return json.dumps({"error": f"快照不存在: {args['snapshot_id']}"}, ensure_ascii=False)
        if _snap.game_slug and _snap.game_slug != slug:
            return json.dumps({
                "error": f"快照 {args['snapshot_id']} 属于游戏 {_snap.game_slug},当前游戏是 {slug}。"
                         "跨游戏删除已拒绝;请先切换到对应游戏。"}, ensure_ascii=False)
        res = snapshot.snapshot_delete(args["snapshot_id"])
        return json.dumps(res, ensure_ascii=False)

    # T11
    elif name == "snapshot_list":
        # 按当前游戏过滤 + 附真实存储路径(此前 agent 猜 %APPDATA%,见接力文档 C-1.5)
        snaps = db.list_snapshots(slug)
        others = len(db.list_snapshots()) - len(snaps)
        hint = f"\n(另有 {others} 个快照属于其他游戏,已隐藏)" if others else ""
        store = os.path.join(snapshot.SNAPSHOTS_DIR, slug)
        if not snaps:
            return f"当前游戏({slug})暂无快照。存储目录: {store}" + hint
        lines = []
        for s in snaps:
            ts = time.strftime("%Y-%m-%d %H:%M", time.localtime(s.timestamp))
            fc = len(json.loads(s.files)) if isinstance(s.files, str) else 0
            label = "原版基线" if fc == 0 else f"{fc} 文件"
            lines.append(f"[{s.id}] {s.trigger_mod_name} · {label} · {ts}")
        return f"当前游戏({slug})的快照(存储于 {store}):\n" + "\n".join(lines) + hint

    # T12
    elif name == "mod_patch":
        if not Tier.can(cfg.tier, "patch"):
            return json.dumps({"error": "当前层级不支持补丁。需要 Pro/Super。"}, ensure_ascii=False)
        mod = db.get_mod(str(args["mod_id"]), slug)
        target = args.get("file_hint", "")
        instruction = args.get("instruction", "")
        if mod and not target:
            files = json.loads(mod.files_installed) if isinstance(mod.files_installed, str) else (mod.files_installed or [])
            for f in files:
                if f.endswith((".json", ".ini", ".cfg", ".txt", ".xml")):
                    target = f
                    break
        if not target:
            return json.dumps({"error": "找不到可修改的配置文件，请指定 file_hint"}, ensure_ascii=False)
        result = patcher.patch_file(target, instruction)
        return json.dumps(result, indent=2, ensure_ascii=False)

    # T15
    elif name == "read_readme":
        archive = args.get("archive_path", "")
        if archive and os.path.exists(archive):
            content = installer.read_readme_zip(archive)
            return content[:3000] if content else "未找到 README 文件。"
        mod_id = args.get("mod_id")
        if mod_id:
            detail = nexus.get_mod_description(mod_id, slug, api_key, cfg.chrome_cdp_port)
            return json.dumps(detail, indent=2, ensure_ascii=False)
        return json.dumps({"error": "请提供 mod_id 或 archive_path"}, ensure_ascii=False)

    # T15b:框架日志诊断(export=true 额外打脱敏诊断包)
    elif name == "game_diagnose":
        if args.get("export"):
            r = diagnostics.export_diag_bundle(
                root, slug, cfg, db.get_installed_mods(slug),
                db.get_operation_log(limit=500), app_version=__import__("modagent").__version__)
        else:
            r = diagnostics.game_diagnose(root, slug, db.get_installed_mods(slug))
        return json.dumps(r, ensure_ascii=False, indent=1)

    # T16
    elif name == "mod_update_check":
        # 按当前游戏过滤；Nexus 详情查询使用受限并发，避免几十个 Mod 串行卡数分钟。
        mods = db.get_installed_mods(slug)
        if not mods:
            return f"当前游戏({slug})暂无已安装 Mod。"
        updates = []
        nexus_mods = [m for m in mods if str(m.id).isdigit()]
        unchecked = len(mods) - len(nexus_mods)
        dependencies_refreshed = 0
        failed_checks = []

        def inspect_mod(m):
            try:
                info = nexus.get_mod(int(m.id), slug, api_key, cdp_port=cfg.chrome_cdp_port)
                return m, info, ""
            except Exception as exc:
                return m, {}, str(exc)

        if nexus_mods:
            from concurrent.futures import ThreadPoolExecutor, as_completed
            workers = min(12, len(nexus_mods))
            with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="mod-update-check") as pool:
                futures = [pool.submit(inspect_mod, m) for m in nexus_mods]
                for future in as_completed(futures):
                    m, info, error = future.result()
                    if error:
                        failed_checks.append({"mod_id": m.id, "name": m.name, "error": error[:160]})
                        continue
                    dependencies = db.parse_dependencies(info.get("dependencies", []))
                    # 非空账本可能是用户修复过的跨来源映射，不用 Nexus 数字 ID 覆盖它。
                    if dependencies and not db.parse_dependencies(m.dependencies):
                        m.dependencies = json.dumps(dependencies)
                        db.update_mod(m)
                        dependencies_refreshed += 1
                    latest = str(info.get("version") or "").strip()
                    if latest and latest != m.version:
                        updates.append({"mod_id": m.id, "name": m.name, "current": m.version,
                                        "latest": latest, "changelog": ""})
        updates.sort(key=lambda item: item["name"].lower())
        return json.dumps({"updates_available": updates,
                           "dependencies_refreshed": dependencies_refreshed,
                           "checked_nexus": len(nexus_mods) - len(failed_checks),
                           "failed_checks": failed_checks,
                           "unchecked_non_nexus": unchecked,
                           "note": "工坊 mod 由 Steam 自动更新;URL 来源的 mod 无版本查询渠道"
                                   if unchecked else ""},
                          indent=2, ensure_ascii=False)

    # T17
    elif name == "mod_update":
        mod = db.get_mod(args["mod_id"], slug)
        if not mod:
            return json.dumps({"error": f"Mod {args['mod_id']} 未安装"}, ensure_ascii=False)
        main = nexus.get_main_file(int(mod.id), slug, api_key)
        if not main:
            return json.dumps({"error": "无法获取最新版本信息"}, ensure_ascii=False)
        file_id = main.get("file_id")
        if not file_id:
            return json.dumps({"error": "无法获取文件 ID"}, ensure_ascii=False)
        path_result = asyncio.run(downloader.download_mod(
            mod_id=int(mod.id), game_slug=slug, game_id=gid,
            api_key=api_key, cdp_port=cfg.chrome_cdp_port))
        path = path_result.get("local_path")
        snap_id = snapshot.snapshot_create(root, slug, trigger_mod_name=f"{mod.name} 更新前")
        files = json.loads(mod.files_installed) if isinstance(mod.files_installed, str) else (mod.files_installed or [])
        try:
            uninstall_result = installer.uninstall_mod(mod.id, root, files, game_slug=slug)
            if uninstall_result.get("errors"):
                raise RuntimeError("旧版本文件未能完整移除")
            lo = db.get_max_load_order(slug) + 1
            result = installer.install_mod(path, root, slug, lo)
            new_files = [f["dest"] for f in result.get("installed", [])]
            if not new_files or result.get("errors"):
                raise RuntimeError("新版本未能完整落位")
        except Exception as exc:
            try:
                rollback = snapshot.snapshot_restore(snap_id)
                failed = rollback.get("failed") or {}
                rollback_ok = not failed.get("delete") and not failed.get("restore")
            except Exception as rollback_exc:
                rollback = {"error": str(rollback_exc)}
                rollback_ok = False
            return json.dumps({
                "error": f"更新失败: {exc}",
                "snapshot_id": snap_id,
                "restored_previous": rollback_ok,
                "rollback": rollback,
                "note": "已自动恢复更新前版本" if rollback_ok else "自动恢复未完整成功，请关闭游戏后从快照页手动回滚",
            }, indent=2, ensure_ascii=False)
        mod.version = main.get("version", mod.version)
        try:
            info = nexus.get_mod(int(mod.id), slug, api_key, cdp_port=cfg.chrome_cdp_port)
            mod.dependencies = json.dumps(db.parse_dependencies(info.get("dependencies", [])))
        except Exception:
            pass
        mod.files_installed = json.dumps(new_files, ensure_ascii=False)
        mod.snapshot_id = snap_id
        db.update_mod(mod)
        return json.dumps({"updated": mod.name, "version": mod.version, "snapshot_id": snap_id}, indent=2, ensure_ascii=False)

    # T19
    elif name == "scan_games":
        detected = games_mod.detect_steam_games()
        return json.dumps({"games": detected}, indent=2, ensure_ascii=False)

    # T20
    elif name == "get_installed":
        # 按当前游戏过滤(DB 一直支持,此前工具层没传 slug → agent 看到全游戏大杂烩,
        # 例:当前 Palworld 却列出 215 条 Civ6/2077/剑星混合记录)
        mods = db.get_installed_mods(slug)
        others = len(db.get_installed_mods()) - len(mods)
        hint = f"\n(另有 {others} 条记录属于其他游戏,已隐藏;切换游戏后可见)" if others else ""
        if not mods:
            return f"当前游戏({slug})暂无已安装 Mod。" + hint
        lines = []
        for i, m in enumerate(mods):
            tag = "" if m.installed_by == "modagent" else f" [{m.installed_by}]"
            lines.append(f"{i+1}. [{m.name}] v{m.version}{tag} (ID:{m.id}, LO:{m.load_order})")
        return f"当前游戏({slug})已安装 {len(mods)} 个 Mod:\n" + "\n".join(lines) + hint

    elif name == "mod_dependency_set":
        mod = db.get_mod(args["mod_id"], slug)
        if not mod:
            return json.dumps({"error": f"未找到 Mod: {args['mod_id']}"}, ensure_ascii=False)
        dependencies, missing = _validate_local_dependencies(
            args.get("dependencies", []), slug, str(mod.id))
        if missing:
            return json.dumps({"error": "只能关联当前游戏中已经安装的本地 Mod ID",
                               "missing_dependencies": missing}, ensure_ascii=False)
        current_ids = db.parse_dependencies(mod.dependencies)
        current = [_toggle_mod_info(item) for item in
                   (db.get_mod(dep_id, slug) for dep_id in current_ids) if item]
        proposed = [_toggle_mod_info(db.get_mod(dep_id, slug)) for dep_id in dependencies]
        if not args.get("confirmed"):
            return json.dumps({
                "requires_confirmation": True,
                "action": "dependency_set",
                "target": _toggle_mod_info(mod),
                "current_dependencies": current,
                "proposed_dependencies": proposed,
                "note": "这只修复 ModAgent 的依赖账本，不会安装、启用或禁用文件。映射错误会影响后续级联启停，请确认等价关系。",
            }, indent=2, ensure_ascii=False)
        mod.dependencies = json.dumps(dependencies)
        db.update_mod(mod)
        return json.dumps({"updated": True, "target": _toggle_mod_info(mod),
                           "dependencies": proposed}, indent=2, ensure_ascii=False)

    elif name == "mod_disable":
        mod = db.get_mod(args["mod_id"], slug)
        if not mod:
            return json.dumps({"error": f"未找到 Mod: {args['mod_id']}"}, ensure_ascii=False)
        dependents = db.get_dependent_chain(mod.id, slug)
        dependent_info = [_toggle_mod_info(item) for item in dependents]
        if dependents and not args.get("confirmed"):
            return json.dumps({
                "requires_confirmation": True, "action": "disable",
                "target": _toggle_mod_info(mod), "dependents": dependent_info,
                "will_disable": dependent_info + [_toggle_mod_info(mod)],
                "note": "此 Mod 是其他 Mod 的前置依赖；继续会连带禁用整个依赖链。",
            }, indent=2, ensure_ascii=False)
        plan = dependents + [mod]
        operation = _execute_toggle_plan(plan, enabling=False)
        if operation.get("error"):
            return json.dumps(operation, indent=2, ensure_ascii=False)
        details = operation["details"]
        total_files = sum(len(item["disabled"]) for item in details)
        changed = [_toggle_mod_info(item, disabled=True) for item in plan]
        return json.dumps({"disabled": total_files, "disabled_mods": changed,
                           "cascade": bool(dependents), "details": details},
                          indent=2, ensure_ascii=False)

    elif name == "mod_enable":
        mod = db.get_mod(args["mod_id"], slug)
        if not mod:
            return json.dumps({"error": f"未找到 Mod: {args['mod_id']}"}, ensure_ascii=False)
        dependencies, missing = db.get_dependency_chain(mod.id, slug)
        dependency_info = [_toggle_mod_info(item) for item in dependencies]
        if missing:
            return json.dumps({
                "blocked": True, "action": "enable", "target": _toggle_mod_info(mod),
                "dependencies": dependency_info, "missing_dependencies": missing,
                "note": "缺少前置依赖，已阻止启用；请先安装缺失依赖。",
            }, indent=2, ensure_ascii=False)
        if dependencies and not args.get("confirmed"):
            return json.dumps({
                "requires_confirmation": True, "action": "enable",
                "target": _toggle_mod_info(mod), "dependencies": dependency_info,
                "will_enable": dependency_info + [_toggle_mod_info(mod)],
                "note": "此 Mod 需要以下前置依赖；继续会先启用依赖，再启用目标 Mod。",
            }, indent=2, ensure_ascii=False)
        plan = dependencies + [mod]
        operation = _execute_toggle_plan(plan, enabling=True)
        if operation.get("error"):
            return json.dumps(operation, indent=2, ensure_ascii=False)
        details = operation["details"]
        total_files = sum(len(item["enabled"]) for item in details)
        changed = [_toggle_mod_info(item, disabled=False) for item in plan]
        return json.dumps({"enabled": total_files, "enabled_mods": changed,
                           "dependencies_enabled": len(dependencies), "details": details},
                          indent=2, ensure_ascii=False)

    elif name == "game_file_check":
        rel = (args.get("path") or "").strip().replace("\\", "/").lstrip("/")
        gr = os.path.realpath(root or "")
        if not gr or not os.path.isdir(gr):
            return json.dumps({"error": "未配置有效的游戏根目录"}, ensure_ascii=False)
        full = os.path.realpath(os.path.join(gr, rel))
        if not (full == gr or full.startswith(gr + os.sep)):
            return json.dumps({"error": "路径越界:只允许查看游戏目录内的文件"}, ensure_ascii=False)
        if not os.path.exists(full):
            return json.dumps({"exists": False, "path": rel}, ensure_ascii=False)
        info = {"exists": True, "path": rel, "is_dir": os.path.isdir(full)}
        if info["is_dir"]:
            try:
                info["entries"] = sorted(os.listdir(full))[:60]
            except Exception as e:
                info["list_error"] = str(e)
        else:
            stt = os.stat(full)
            info["size_bytes"] = stt.st_size
            info["mtime"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(stt.st_mtime))
            n = args.get("tail")
            if n:
                try:
                    with open(full, "r", encoding="utf-8", errors="replace") as f:
                        lines = f.readlines()
                    info["tail"] = "".join(lines[-min(int(n), 200):])[-6000:]
                except Exception as e:
                    info["tail_error"] = str(e)
        return json.dumps(info, ensure_ascii=False)

    elif name == "list_downloads":
        d = os.path.join(downloader.DOWNLOADS_DIR, slug)
        if not os.path.isdir(d):
            return json.dumps({"count": 0, "files": [],
                               "note": f"下载目录不存在或为空: {d}"}, ensure_ascii=False)
        import re as _re
        items = []
        for f in sorted(os.listdir(d)):
            if not f.lower().endswith((".zip", ".7z", ".rar")):
                continue
            full = os.path.join(d, f)
            try:
                size_mb = round(os.path.getsize(full) / 1048576, 1)
            except OSError:
                size_mb = 0
            m = _re.match(r"^(\d+)_(.+?)\.(zip|7z|rar)$", f, _re.I)
            mid = m.group(1) if m else ""
            nm = (m.group(2) if m else os.path.splitext(f)[0]).replace("_", " ")
            items.append({"file": f, "mod_id": mid, "name": nm, "size_mb": size_mb})
        return json.dumps({"count": len(items), "files": items}, ensure_ascii=False)

    return json.dumps({"error": f"未知工具: {name}"}, ensure_ascii=False)


def _recommend_nexus(query: str, slug: str, api_key: str) -> dict:
    """Nexus 推荐(原逻辑):搜索 + 依赖解析。"""
    results = nexus.search(query[:60], slug, api_key)
    recs = []
    for r in (results or [])[:5]:
        mod_id = r.get("mod_id", 0)
        deps = nexus.resolve_deps(mod_id, slug, api_key) if mod_id else []
        recs.append({
            "mod_id": mod_id,
            "name": r.get("name", ""),
            "reason": f"评分 {r.get('endorsement_count', 0)}，最近更新 {r.get('updated_time', '')}",
            "endorsements": r.get("endorsement_count", 0),
            "dependencies": deps,
        })
    all_deps = list(set(sum([r["dependencies"] for r in recs], [])))
    return {"recommendations": recs,
            "install_plan": all_deps + [r["mod_id"] for r in recs if r["dependencies"]]}


def _recommend(query: str, cfg: Config) -> dict:
    """多源聚合推荐(#1):按 available_sources 挑当前游戏的可用源并发查询,
    按来源分组返回——各源热度口径不同(评分/订阅/下载量/星数),不做跨源硬排序,
    交 agent 综合叙述。单源失败(如工坊需 Chrome 登录)不阻塞其余源,如实入 sources_failed。
    顶层 recommendations/install_plan 保持 Nexus 结构(兼容旧调用方)。"""
    if not query:
        return {"recommendations": [], "install_plan": [], "note": "请提供需求描述"}

    from .sources import available_sources
    slug, api_key = cfg.game_slug, cfg.nexus_api_key
    src = available_sources(cfg.game_name or "", slug or "", cfg.game_root or "")

    import concurrent.futures as cf
    tasks = {}
    ex = cf.ThreadPoolExecutor(max_workers=5)
    if src.get("nexus"):
        tasks["nexus"] = ex.submit(_recommend_nexus, query, slug, api_key)
    if src.get("workshop"):
        from .sources import steam_workshop as sw
        tasks["workshop"] = ex.submit(
            lambda: asyncio.run(sw.search(query, src["workshop"], cfg.chrome_cdp_port))[:5])
    if src.get("thunderstore"):
        from .sources import thunderstore as ts
        tasks["thunderstore"] = ex.submit(ts.search, src["thunderstore"], query, 5)
    if src.get("gamebanana"):
        from .sources import gamebanana as gb
        tasks["gamebanana"] = ex.submit(gb.search, src["gamebanana"], query, 5)
    from .sources import github as gh
    tasks["github"] = ex.submit(gh.search, query, cfg.game_name or slug or "", 5)

    out = {"recommendations": [], "install_plan": [],
           "sources_consulted": [], "sources_failed": {}}
    for name, fut in tasks.items():
        # nexus 是"搜索+逐个解析依赖"(5 个 mod 十几次 API 调用),比其他源慢一个量级
        budget = 90 if name == "nexus" else 25
        try:
            r = fut.result(timeout=budget)
        except cf.TimeoutError:
            out["sources_failed"][name] = f"该源响应超时(>{budget}s),可单独用对应 search 工具重试"
            continue
        except Exception as e:
            out["sources_failed"][name] = (str(e) or type(e).__name__)[:120]
            continue
        out["sources_consulted"].append(name)
        if name == "nexus":
            out["recommendations"] = r["recommendations"]
            out["install_plan"] = r["install_plan"]
        else:
            out[name] = r
    ex.shutdown(wait=False)

    total = len(out["recommendations"]) + sum(
        len(out.get(k) or []) for k in ("workshop", "thunderstore", "gamebanana", "github"))
    if total == 0:
        out["note"] = "各来源都没找到匹配的 Mod,试试换个说法(英文关键词命中率更高)?"
    else:
        out["note"] = ("已按来源分组(recommendations=Nexus 含依赖解析,其余各源独立)。"
                       "各源热度口径不同,不要跨源硬排序;GitHub 结果可能混入非 mod 仓库,凭 summary 判断。")
    return out


def _game_paths(cfg: Config) -> list[str]:
    paths = [os.path.join(cfg.game_root, "Data")] if cfg.game_root else []
    if cfg.game_slug == "skyrimspecialedition":
        skse = os.path.join(cfg.game_root, "SKSE")
        if os.path.exists(skse):
            paths.append(skse)
    return paths
