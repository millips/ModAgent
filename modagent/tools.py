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
from . import user_config
from . import confirmation
from . import games as games_mod
from . import stardew
from . import web_agent
from .inventory_match import find_installed_duplicate


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


def refresh_local_inventory(cfg: Config) -> dict:
    """Fast offline preflight used before downloads.

    It acknowledges disk state first, without website calls, so an unscanned
    existing installation cannot be duplicated merely because the UI database
    started empty.
    """
    root = str(getattr(cfg, "game_root", "") or "")
    slug = str(getattr(cfg, "game_slug", "") or "")
    if not root or not slug or not os.path.isdir(root):
        return {"detected": 0, "imported": 0}
    extra = (getattr(cfg, "manual_mod_dirs", {}) or {}).get(slug, [])
    result = scanner.scan_existing_mods(root, slug, "", extra)
    result["imported"] = scanner.import_mods(result.get("identified", []))
    return result


_refresh_local_inventory = refresh_local_inventory


def _installed_duplicate(slug: str, source: str, source_key: str,
                         target_name: str = ""):
    return find_installed_duplicate(
        slug, source, source_key, target_name=target_name
    )


def _url_source_identity(url: str) -> tuple[str, str, str]:
    """Return (source, stable key, conservative display-name hint)."""
    import re as _re
    value = (url or "").strip()
    lower = value.casefold()
    if "thunderstore.io" in lower:
        match = _re.search(r"/p/([^/]+)/([^/?#]+)", value, _re.I)
        if match:
            return "thunderstore", f"{match.group(1)}-{match.group(2)}", match.group(2)
    if "github.com" in lower:
        match = _re.search(r"github\.com/([^/]+)/([^/?#]+)", value, _re.I)
        if match:
            repo = match.group(2).removesuffix(".git")
            return "github", f"{match.group(1)}/{repo}", repo
    if "gamebanana.com" in lower:
        match = _re.search(r"/mods/(\d+)", value, _re.I)
        if match:
            return "gamebanana", match.group(1), ""
    return "", "", ""


def build_tools_definitions(tier: str) -> list[dict]:
    all_tools = [
        _t("browser_pages", "列出 ModAgent Chrome 中当前打开的受支持 Mod 站点页面。网页任务开始、页面身份不明确或出现多个标签时先调用。",
           {}, []),
        _t("browser_doctor", "诊断 ModAgent Chrome、Playwright 与 CDP 连接状态。浏览器打不开、反复开页或下载异常时先调用。",
           {}, []),
        _t("browser_observe", "读取当前网页实际渲染出的语义快照：URL、标题、正文、弹窗、错误提示以及带 target_id 的可见按钮/链接/输入框。网页搜索、登录判断、下载失败或页面改版时必须先观察再行动，禁止凭固定 SOP 猜页面。",
           {"tab_id": {"type": "string", "description": "可选；browser_pages/browser_observe 返回的标签 ID"}},
           []),
        _t("browser_click", "点击 browser_observe 返回的可见控件。使用最近一次观察结果里的 target_id；若网页重绘导致 ID 消失，工具会按文字、链接和弹窗上下文重新定位；点击后自动返回新的页面快照。",
           {"target_id": {"type": "string", "description": "browser_observe 返回的 target_id，如 ma-3-12"},
            "tab_id": {"type": "string", "description": "可选；对应页面标签 ID"}},
           ["target_id"]),
        _t("browser_input", "向 browser_observe 返回的输入框填写文本，可选择提交；操作后自动返回新的页面快照。",
           {"target_id": {"type": "string"},
            "value": {"type": "string"},
            "submit": {"type": "boolean", "description": "是否按 Enter/提交表单"},
            "tab_id": {"type": "string", "description": "可选；对应页面标签 ID"}},
           ["target_id", "value"]),
        _t("browser_wait", "等待页面达到明确条件后重新观察；优先等待文本或 URL，不要盲目固定等待。",
           {"seconds": {"type": "number", "description": "无明确条件时的等待秒数，0.2-10"},
            "text": {"type": "string", "description": "等待该文本可见"},
            "url_pattern": {"type": "string", "description": "等待 URL 匹配该模式"},
            "timeout_ms": {"type": "integer", "description": "条件等待超时，最多30000毫秒"},
            "tab_id": {"type": "string", "description": "可选；页面原始 ID 或 stable_id"}},
           []),
        _t("browser_open", "在 ModAgent Chrome 中打开受支持的 Mod 站点页面并立即观察。支持 Nexus、Steam Community、GitHub、Thunderstore、GameBanana、ModDB、CurseForge、FluffyQuack、mod.io、itch.io 等已审核站点。",
           {"url": {"type": "string"}},
           ["url"]),
        _t("scan_existing_mods", "离线递归扫描当前游戏目录和已保存的外部 Mod 目录，立即把磁盘中真实存在的 Mod 写入统一管理清单；不依赖网站成功。来源和版本请随后用 mod_source_align / mod_update_check 绑定。",
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
        _t("nexus_search", "按关键词搜索 Nexus Mods。工具/管理器/框架类查询会同时核验 Nexus 通用工具区，归并同名旧条目并标记 canonical_candidate。返回结果中的 nexus_slug 必须原样传给详情和下载工具。",
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
           {"mod_id": {"type": "integer", "description": "Mod ID"},
            "nexus_slug": {"type": "string", "description": "可选；使用 nexus_search 返回的来源 slug，例如 site 或 streetfighter6"}},
           ["mod_id"]),
        _t("mod_download", "下载 Mod 文件到本地缓存。开始前会自动重扫本地并核对来源；已有同一 Mod 时返回 already_installed 并跳过下载，升级请用 mod_update。若返回多个变体(variants)，再次调用并传入所选 file_id。",
           {"mod_id": {"type": "integer"},
            "nexus_slug": {"type": "string", "description": "可选；使用 nexus_search 返回的来源 slug，例如 site"},
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
        _t("tool_extract", "解压独立 Mod 工具/管理器（如 Fluffy Mod Manager）到 ModAgent 受控工具目录。"
           "这类程序不应装进游戏目录；下载完成并获得用户确认后调用。返回压缩包、解压目录和 EXE 的绝对路径，"
           "必须如实展示给用户；只解压，不自动运行 EXE。",
           {"local_path": {"type": "string", "description": "mod_download 返回的压缩包绝对路径"},
            "display_name": {"type": "string", "description": "工具名和版本，如 Fluffy_Mod_Manager_v3.079"}},
           ["local_path"]),
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
        _t("snapshot_restore", "回滚游戏文件到指定快照状态(只删快照域内的新增文件,游戏本体永不触碰)。若快照记录了工坊订阅清单,会同步订阅状态。只能回滚当前游戏的快照。所有游戏首次调用都只返回预览和一次性确认令牌；必须展示影响并结束当前轮，用户在新一轮明确确认后才能携 confirmed=true 与 confirmation_token 执行。",
           {"snapshot_id": {"type": "string"},
            "confirmed": {"type": "boolean", "description": "用户已在预览后的新一轮明确同意回滚"},
            "confirmation_token": {"type": "string", "description": "首次预览返回的一次性确认令牌"}},
           ["snapshot_id"]),
        _t("snapshot_delete", "删除一个快照(磁盘目录 + DB 记录)。只能删当前游戏的快照;删除不影响已安装的 mod 文件。删除后无法再回滚到该状态。首次调用只返回删除预览和一次性确认令牌；必须展示快照身份并结束当前轮，用户在新一轮明确确认后才能执行。",
           {"snapshot_id": {"type": "string"},
            "confirmed": {"type": "boolean", "description": "用户已在预览后的新一轮明确同意删除"},
            "confirmation_token": {"type": "string", "description": "首次预览返回的一次性确认令牌"}},
           ["snapshot_id"]),
        _t("snapshot_list", "列出所有快照记录，含时间、触发 Mod、文件数。",
           {}, []),
        _t("mod_patch", "修改 Mod 配置文件中的数值。支持 JSON/INI/CFG/TXT/XML。",
           {"mod_id": {"type": "integer"}, "instruction": {"type": "string"},
            "file_hint": {"type": "string", "description": "可选，目标文件名提示"}},
           ["mod_id", "instruction"]),
        _t("game_config_write", "把安装说明明确要求的文本配置安全写入 Windows 用户配置目录。"
           "只能选择 Documents、Saved Games、LocalAppData 或 RoamingAppData，且只能写相对路径下的常见文本配置；"
           "INI 默认按 section 合并并保留其他设置，已有文件会先备份。只有 README、详情页或压缩包内容提供了确切路径和内容时才可调用，禁止猜测配置。",
           {"location": {"type": "string", "enum": ["documents", "saved_games", "local_appdata", "roaming_appdata"]},
            "relative_path": {"type": "string", "description": "所选用户目录内的相对路径"},
            "content": {"type": "string", "description": "经安装说明核实的完整配置内容"},
            "mode": {"type": "string", "enum": ["merge_ini", "create_or_replace"], "description": "INI 应使用 merge_ini；默认 merge_ini"},
            "mod_id": {"type": "string", "description": "可选，关联的 Mod ID，用于备份归档"}},
           ["location", "relative_path", "content"]),
        _t("read_readme", "读取 Mod 的 README 或安装说明。支持本地 zip 和 Nexus 在线两种来源。",
           {"mod_id": {"type": "integer", "description": "Mod ID（在线读取）"},
            "archive_path": {"type": "string", "description": "本地 zip 路径（二选一）"}},
           ["mod_id"]),
        _t("game_diagnose", "游戏装了 mod 后出问题(崩溃/黑屏/mod 不生效)时用它诊断:按框架"
           "(BepInEx/MelonLoader/UE4SS)自动定位日志,抓最近的报错/警告,结合已装 mod 清单归因到"
           "具体 mod,给出建议(禁用/更新/补依赖)。纯读取不改任何文件。传 export=true 会额外生成一个"
           "脱敏诊断包 zip(框架日志+操作记录+版本环境,绝不含任何 API key)供用户手动上报给开发者。",
           {"export": {"type": "boolean", "description": "true=额外生成脱敏诊断包 zip"}}, []),
        _t("mod_source_align", "把扫描导入的本地 Mod 自动对应到 Nexus、Steam 创意工坊或 Thunderstore 的稳定维护页。"
           "返回已绑定、候选歧义、未匹配和来源失败四类；只会自动保存精确或高置信匹配，绝不把低置信候选强行绑定。",
           {"force_refresh": {"type": "boolean", "description": "忽略 Thunderstore 十分钟缓存，重新拉取完整包清单"}},
           []),
        _t(
            "mod_source_bind",
            "把一个本地已安装 Mod 绑定到用户明确确认的 Nexus Mod ID。"
            "只有用户已经明确说明实际来源 ID 时才可 confirmed=true；"
            "工具会先核验 Nexus 完整详情并保存稳定绑定，后续更新不得再靠名称猜测。",
            {
                "local_mod_id": {
                    "type": "string",
                    "description": "get_installed/mod_update_check 返回的本地 Mod ID",
                },
                "nexus_mod_id": {
                    "type": "integer",
                    "description": "用户明确确认的 Nexus Mod ID",
                },
                "confirmed": {
                    "type": "boolean",
                    "description": "用户已明确确认该本地 Mod 的实际 Nexus ID",
                },
            },
            ["local_mod_id", "nexus_mod_id"],
        ),
        _t("mod_update_check", "自动对齐来源后检查当前游戏全部已安装 Mod 的版本。"
           "返回逐项状态：可更新、已是最新、本地版本未知、外部平台托管、未绑定或检查失败；"
           "updates_available 中的项目可直接交给 mod_update 一键同步。",
           {"force_refresh": {"type": "boolean", "description": "强制刷新上游包清单"}},
           []),
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
        _t("stardew_smapi_status", "星露谷物语专用只读验收：区分 SMAPI 文件已安装、Steam 启动选项已配置、"
           "SMAPI 已实际启动、目标 Mod 已被日志加载四个阶段。返回可直接复制的完整启动参数、"
           "SMAPI-latest.txt 证据和下一步；只有 complete=true 才能宣布大功告成。",
           {}, []),
        _t("list_downloads", "列出当前游戏【下载缓存目录】里已下载的所有 mod 压缩包(文件名、mod_id、大小)。"
           "用户说\"把我下好的都装上\"这类批量安装需求时,先调此工具看清有哪些已下载文件,再逐个 mod_install,"
           "不要反过来让用户手动列出文件清单。",
           {}, []),
        _t("mod_disable", "禁用一个 Mod。首次调用只返回文件、外部配置与依赖链预览；必须展示影响并结束当前轮，用户在新一轮明确确认后才能携一次性令牌执行。完成后会复核游戏目录文件与受管外部配置，未通过不得声称已禁用或处于裸游戏状态。",
           {"mod_id": {"type": "string"},
            "confirmed": {"type": "boolean", "description": "用户在预览后的新一轮明确确认"},
            "confirmation_token": {"type": "string", "description": "首次预览返回的一次性确认令牌"}}, ["mod_id"]),
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


def _version_parts(value: str) -> tuple[int, ...]:
    import re as _re
    parts = _re.findall(r"\d+", str(value or ""))
    return tuple(int(part) for part in parts[:6])


def _same_version(left: str, right: str) -> bool:
    a = str(left or "").strip().casefold().lstrip("v")
    b = str(right or "").strip().casefold().lstrip("v")
    if a == b:
        return True
    ap, bp = _version_parts(a), _version_parts(b)
    return bool(ap and bp and ap == bp)


def _version_relation(current: str, latest: str) -> str:
    """Return older/newer/different without inventing an order for labels."""
    current_parts = _version_parts(current)
    latest_parts = _version_parts(latest)
    if current_parts and latest_parts:
        width = max(len(current_parts), len(latest_parts))
        current_parts += (0,) * (width - len(current_parts))
        latest_parts += (0,) * (width - len(latest_parts))
        if current_parts > latest_parts:
            return "newer"
        if current_parts < latest_parts:
            return "older"
    return "different"


def _execute_toggle_plan(mods, enabling: bool, game_slug: str = "") -> dict:
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
    config_result = user_config.toggle_mod_configs(
        game_slug, [str(mod.id) for mod in mods], enabling=enabling,
    ) if game_slug else {"complete": True, "changed": [], "failed": []}
    if not config_result.get("complete"):
        rollback_files = (installer.disable_mod if enabling else installer.enable_mod)(list(reversed(changed)))
        rollback_config = user_config.toggle_mod_configs(
            game_slug, [str(mod.id) for mod in mods], enabling=not enabling,
        )
        return {
            "error": "外部配置启停失败；已尝试撤销本轮文件改名，未将状态报告为完成。",
            "details": details, "external_configs": config_result,
            "rollback": {"files": rollback_files, "external_configs": rollback_config},
        }
    return {"details": details, "external_configs": config_result}


def execute(name: str, args: dict, cfg: Config) -> str:
    api_key = cfg.nexus_api_key
    slug = cfg.game_slug
    gid = cfg.game_id
    root = cfg.game_root
    nexus_identity_cache = {}

    def current_nexus_identity():
        """Resolve the remote Nexus identity without changing the local slug."""
        if nexus_identity_cache:
            return (
                nexus_identity_cache["slug"],
                nexus_identity_cache["game_id"],
                nexus_identity_cache["discovery"],
            )
        if slug and not str(slug).startswith("local_"):
            discovery = {
                "status": "available", "slug": slug, "game_id": gid,
                "evidence": "static game mapping",
            }
            resolved_slug, resolved_id = slug, gid
        else:
            discovery = nexus.discover_game(
                cfg.game_name or "", getattr(cfg, "tavily_api_key", ""),
                api_key,
            )
            resolved_slug = discovery.get("slug") or ""
            resolved_id = int(discovery.get("game_id") or 0)
        nexus_identity_cache.update(
            slug=resolved_slug, game_id=resolved_id, discovery=discovery
        )
        return resolved_slug, resolved_id, discovery

    def download_buckets(resolve_remote: bool = True) -> list[str]:
        """当前游戏的本地账本 slug 与远端 Nexus slug 共用一份缓存视图。"""
        buckets = [str(slug or "")]
        if resolve_remote:
            try:
                remote_slug, _, _ = current_nexus_identity()
                buckets.append(str(remote_slug or ""))
            except Exception:
                pass
        return list(dict.fromkeys(s for s in buckets if s))

    def find_download(mid, file_id=None) -> str:
        return downloader.find_cached_nexus_download(download_buckets(), mid, file_id)

    # T00 - scan existing mods in game directory
    if name == "browser_pages":
        return json.dumps(web_agent.list_pages(cfg.chrome_cdp_port), ensure_ascii=False)

    elif name == "browser_doctor":
        return json.dumps(web_agent.doctor(cfg.chrome_cdp_port), ensure_ascii=False)

    elif name == "browser_observe":
        return json.dumps(
            web_agent.observe(cfg.chrome_cdp_port, args.get("tab_id", "")),
            ensure_ascii=False,
        )

    elif name == "browser_click":
        return json.dumps(
            web_agent.click(
                cfg.chrome_cdp_port,
                args.get("target_id", ""),
                args.get("tab_id", ""),
            ),
            ensure_ascii=False,
        )

    elif name == "browser_input":
        return json.dumps(
            web_agent.input_text(
                cfg.chrome_cdp_port,
                args.get("target_id", ""),
                args.get("value", ""),
                args.get("tab_id", ""),
                bool(args.get("submit", False)),
            ),
            ensure_ascii=False,
        )

    elif name == "browser_wait":
        return json.dumps(
            web_agent.wait_and_observe(
                cfg.chrome_cdp_port,
                args.get("seconds", 1),
                args.get("tab_id", ""),
                args.get("text", ""),
                args.get("url_pattern", ""),
                args.get("timeout_ms", 10000),
            ),
            ensure_ascii=False,
        )

    elif name == "browser_open":
        return json.dumps(
            web_agent.open_page(cfg.chrome_cdp_port, args.get("url", "")),
            ensure_ascii=False,
        )

    elif name == "scan_existing_mods":
        if not root:
            return json.dumps({"error": "请先选择游戏目录"}, ensure_ascii=False)
        extra_roots = (getattr(cfg, "manual_mod_dirs", {}) or {}).get(slug, [])
        result = scanner.scan_existing_mods(root, slug, api_key, extra_roots)
        identified = result.get("identified", [])
        if identified:
            scanner.import_mods(identified)
        # Never inject thousands of absolute file paths into the model context.
        # The full inventory is already persisted; the tool response is a bounded report.
        public_items = [{
            "mod_id": item.get("mod_id", ""),
            "name": item.get("name", ""),
            "version": item.get("version", "unknown"),
            "confidence": item.get("confidence", ""),
            "file_count": len(item.get("files") or []),
        } for item in identified[:500]]
        return json.dumps({
            "detected": result.get("detected", 0),
            "imported": len(identified),
            "identified": public_items,
            "identified_total": len(identified),
            "truncated": len(identified) > len(public_items),
            "unidentified_count": len(result.get("unidentified") or []),
            "scanned_roots": result.get("scanned_roots", []),
            "missing_roots": result.get("missing_roots", []),
        }, indent=2, ensure_ascii=False)

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
        effective_slug, effective_gid, discovery = current_nexus_identity()
        if not effective_slug:
            return json.dumps({
                "error": "game_mapping_missing",
                "status": (discovery or {}).get("status", "not_detected"),
                "reason": (discovery or {}).get(
                    "reason", "未能确认当前游戏对应的 Nexus 专区"
                ),
                "game_name": cfg.game_name or "",
                "searched": False,
                "note": "未执行 Nexus Mod 搜索；这不代表 Nexus 没有该游戏专区。",
            }, ensure_ascii=False)
        # 粘贴 Nexus 链接或直接给 mod_id → 绕过受限的搜索索引，直接解析详情
        link_match = _re.search(
            r"nexusmods\.com/(?:games/)?([\w-]+)/mods/(\d+)", q
        )
        m = link_match or _re.fullmatch(r"\d{2,7}", q)
        if m:
            direct_slug = link_match.group(1) if link_match else effective_slug
            mid = int(link_match.group(2) if link_match else m.group(0))
            try:
                d = nexus.get_detail(mid, direct_slug, api_key, cdp_port=cfg.chrome_cdp_port)
                return json.dumps({"direct": True, "results": [{
                    "mod_id": d.get("mod_id"), "name": d.get("name"), "summary": d.get("summary", ""),
                    "version": d.get("version", ""), "file_id": d.get("file_id"),
                    "nexus_slug": direct_slug,
                }]}, indent=2, ensure_ascii=False)
            except Exception as e:
                return json.dumps({"error": f"按 ID/链接获取详情失败: {e}"}, ensure_ascii=False)
        try:
            results = nexus.search(
                q, effective_slug, api_key,
                cdp_port=cfg.chrome_cdp_port,
                game_id=effective_gid,
                tavily_key=cfg.tavily_api_key,
            )
        except nexus.NexusSearchUnavailable as e:
            return json.dumps({
                "status": e.status,
                "searched": False,
                "source": "nexus",
                "game_slug": effective_slug,
                "results": [],
                "error": e.reason,
                "note": (
                    "本次未能连接或验证 Nexus，不能解释为“没搜到”，"
                    "也不能据此判断游戏专区或相关 Mod 不存在。"
                ),
            }, ensure_ascii=False)
        for result in results:
            result.setdefault("nexus_slug", effective_slug)
        if nexus.is_tool_query(q):
            global_tools = nexus.search_tool_entries(
                q, cfg.tavily_api_key, api_key, cfg.chrome_cdp_port
            )
            known = {
                (str(item.get("nexus_slug") or effective_slug),
                 int(item.get("mod_id") or 0))
                for item in results
            }
            results.extend(
                item for item in global_tools
                if (str(item.get("nexus_slug") or ""),
                    int(item.get("mod_id") or 0)) not in known
            )
            results = nexus.rank_duplicate_entries(results)
        if not results:
            return json.dumps({
                "status": "search_empty",
                "searched": True,
                "source": "nexus",
                "game_slug": effective_slug,
                "results": [],
                "note": "本次 Nexus 搜索未找到匹配结果；不能据此判断专区或相关 Mod 不存在。",
            }, ensure_ascii=False)
        return json.dumps({
            "status": "ok",
            "searched": True,
            "source": "nexus",
            "game_slug": effective_slug,
            "tool_query_global_checked": nexus.is_tool_query(q),
            "results": [{
            "mod_id": r.get("mod_id"), "name": r.get("name"), "summary": r.get("summary", ""),
            "endorsements": r.get("endorsement_count", 0), "version": r.get("version", ""),
            "updated": r.get("updated_time", r.get("updated", "")),
            "author": r.get("author", ""), "nexus_slug": r.get("nexus_slug", effective_slug),
            "url": r.get("url", ""),
            "canonical_candidate": r.get("canonical_candidate", False),
            "superseded_by": r.get("superseded_by"),
            } for r in results[:10]],
        }, indent=2, ensure_ascii=False)

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
        attempts = 1
        try:
            results = thunderstore.search(comm, q)
            if not results:
                attempts = 2
                results = thunderstore.search(comm, q, force_refresh=True)
        except Exception as e:
            return json.dumps({
                "status": "source_unavailable",
                "searched": False,
                "source": "thunderstore",
                "community": comm,
                "attempts": attempts,
                "results": [],
                "error": f"Thunderstore 搜索失败: {e}",
                "note": "本次来源不可用，不能解释为没有相关 Mod。",
            }, ensure_ascii=False)
        if not results:
            return json.dumps({
                "status": "search_empty",
                "searched": True,
                "source": "thunderstore",
                "community": comm,
                "attempts": attempts,
                "results": [],
                "note": (
                    f"Thunderstore「{comm}」社区两次查询均未命中「{q}」；"
                    "这不代表该社区或相关 Mod 不存在，可更换关键词重试。"
                ),
            }, ensure_ascii=False)
        return json.dumps({
            "status": "ok",
            "searched": True,
            "source": "thunderstore",
            "community": comm,
            "attempts": attempts,
            "results": results,
        }, ensure_ascii=False, indent=2)

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
            return json.dumps({"status": "search_empty",
                               "note": f"GitHub 已先按当前游戏限定搜索，并自动用原关键词做全局回退；本次仍未搜到「{q}」相关仓库。这不等于仓库不存在。",
                               "results": []}, ensure_ascii=False)
        return json.dumps({"results": results,
                           "note": "游戏限定为空时已自动回退全局搜索。结果可能混入非 mod 仓库(工具/教程),凭 summary/星数判断后再推荐;"
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
        _refresh_local_inventory(cfg)
        existing_workshop = db.get_mod("ws_" + wid, slug) or db.get_mod_by_source(
            slug, "workshop", wid
        )
        if existing_workshop:
            return json.dumps({
                "status": "already_installed", "already_installed": True,
                "subscription_skipped": True, "workshop_id": wid,
                "installed_id": str(existing_workshop.id),
                "name": existing_workshop.name,
                "message": "该创意工坊项目已在当前游戏中，未重复订阅。",
            }, ensure_ascii=False)
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
        progress.start([{
            "mod_id": key,
            "name": f"工坊项目 {wid}",
            "source": "workshop",
        }])
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
        if "nexus-cdn.com/" in url or "nexusmods.com/" in url:
            return json.dumps({
                "error": "wrong_tool_for_nexus",
                "status": "use_mod_download",
                "message": "这是 Nexus 下载地址，已阻止交给通用下载器。请复用已有 mod_download 结果；若尚未完成，则用相同 mod_id/file_id 继续 mod_download。",
            }, ensure_ascii=False)
        preflight = _refresh_local_inventory(cfg)
        source_name, source_key, name_hint = _url_source_identity(url)
        existing = _installed_duplicate(slug, source_name, source_key, name_hint) if source_key else None
        if existing:
            if not db.get_mod_by_source(slug, source_name, source_key):
                db.upsert_mod_source_binding(
                    slug, str(existing.id), source_name, source_key, url,
                    .96, "download_preflight_name", "",
                )
            return json.dumps({
                "status": "already_installed", "already_installed": True,
                "download_skipped": True, "source": source_name,
                "source_key": source_key, "installed_id": str(existing.id),
                "name": existing.name, "version": existing.version,
                "preflight_detected": preflight.get("detected", 0),
                "message": "下载前扫描发现本地已有同一 Mod，已跳过重复下载。",
            }, ensure_ascii=False)
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
        progress.start([{
            "mod_id": key,
            "name": name_hint or source_key or "下载文件",
            "source": source_name,
        }])
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
        nexus_slug, _, discovery = current_nexus_identity()
        nexus_slug = (args.get("nexus_slug") or nexus_slug).strip()
        if not nexus_slug:
            return json.dumps({
                "error": "game_mapping_missing",
                "status": discovery.get("status", "not_detected"),
                "reason": discovery.get("reason", "Nexus game page was not resolved"),
            }, ensure_ascii=False)
        detail = nexus.get_detail(
            args["mod_id"], nexus_slug, api_key,
            cdp_port=cfg.chrome_cdp_port,
        )
        return json.dumps(detail, indent=2, ensure_ascii=False)

    # T04
    elif name == "mod_download":
        if not Tier.can(cfg.tier, "download"):
            return json.dumps({"error": "当前层级不支持下载", "suggestion": "升级到 Pro 订阅"}, ensure_ascii=False)
        _mid = args["mod_id"]
        preflight = _refresh_local_inventory(cfg)
        already = _installed_duplicate(slug, "nexus", str(_mid))
        if already:
            cached_path = find_download(_mid, args.get("file_id"))
            cache_cleanup = (
                downloader.cleanup_installed_archive(cached_path)
                if cached_path else {"removed": False, "reason": "not_found"}
            )
            return json.dumps({
                "status": "already_installed",
                "already_installed": True,
                "download_skipped": True,
                "mod_id": str(_mid),
                "installed_id": str(already.id),
                "name": already.name,
                "version": already.version,
                "preflight_detected": preflight.get("detected", 0),
                "cache_cleanup": cache_cleanup,
                "message": "已在当前游戏的统一管理清单中，已跳过重复下载。需要升级时请使用 mod_update。",
            }, ensure_ascii=False)
        nexus_slug, nexus_gid, discovery = current_nexus_identity()
        requested_slug = (args.get("nexus_slug") or "").strip()
        if requested_slug:
            nexus_slug = requested_slug
            nexus_gid = nexus.resolve_game_id(nexus_slug, api_key)
        elif not nexus_gid:
            nexus_gid = nexus.resolve_game_id(nexus_slug, api_key)
        if not nexus_slug:
            return json.dumps({
                "error": "game_mapping_missing",
                "status": discovery.get("status", "not_detected"),
                "reason": discovery.get("reason", "Nexus game page was not resolved"),
            }, ensure_ascii=False)
        if not nexus_gid:
            return json.dumps({
                "error": "nexus_game_id_missing",
                "nexus_slug": nexus_slug,
                "note": "无法解析该 Nexus 来源的数字 game_id，已在打开下载页之前停止，避免重复开页。请稍后重试或检查 Nexus API Key。",
            }, ensure_ascii=False)
        # A local import initially has no Nexus ID. Resolve only the requested
        # item and use a strict name match to prevent installing a second copy.
        try:
            requested_detail = nexus.get_mod(
                int(_mid), nexus_slug, api_key, cdp_port=cfg.chrome_cdp_port
            )
            already = _installed_duplicate(
                slug, "nexus", str(_mid), requested_detail.get("name", "")
            )
        except Exception:
            requested_detail = {}
            already = None
        if already:
            source_url = f"https://www.nexusmods.com/{nexus_slug}/mods/{_mid}"
            db.upsert_mod_source_binding(
                slug, str(already.id), "nexus", str(_mid), source_url,
                .96, "download_preflight_name",
                str(requested_detail.get("version") or ""),
                {"nexus_slug": nexus_slug, "matched_name": requested_detail.get("name", "")},
            )
            cached_path = find_download(_mid, args.get("file_id"))
            cache_cleanup = (
                downloader.cleanup_installed_archive(cached_path)
                if cached_path else {"removed": False, "reason": "not_found"}
            )
            return json.dumps({
                "status": "already_installed", "already_installed": True,
                "download_skipped": True, "mod_id": str(_mid),
                "installed_id": str(already.id), "name": already.name,
                "version": already.version,
                "matched_upstream_name": requested_detail.get("name", ""),
                "binding_created": True,
                "cache_cleanup": cache_cleanup,
                "message": "下载前扫描发现本地已有同一 Mod，已绑定维护来源并跳过重复下载。",
            }, ensure_ascii=False)
        progress.start([{
            "mod_id": _mid,
            "name": requested_detail.get("name", "") or f"Nexus Mod {_mid}",
            "source": "nexus",
        }])
        progress.set_status(_mid, "downloading")
        try:
            result = asyncio.run(downloader.download_mod(
                mod_id=_mid, game_slug=nexus_slug, game_id=nexus_gid,
                api_key=api_key, cdp_port=cfg.chrome_cdp_port,
                progress_callback=lambda f: progress.set_pct(_mid, int(f * 100)),
                file_id=args.get("file_id")))
        except downloader.NexusManualDownloadRequired as e:
            progress.set_status(
                _mid,
                "queued" if e.existing_gate else "failed",
                "因前一项暂停，尚未尝试" if e.existing_gate else "等待 Nexus 页面人工确认",
            )
            progress.finish()
            if e.existing_gate:
                return json.dumps({
                    "status": "skipped_due_to_previous_nexus_gate",
                    "mod_id": _mid,
                    "page_url": e.page_url,
                    "message": "当前项尚未尝试下载；它因前一项 Nexus 下载尚未完成而被暂停。",
                    "attempted": False,
                    "stop_further_downloads": True,
                }, ensure_ascii=False)
            if "尚未登录" in e.reason:
                user_action = "请在已保留的 Nexus 页面完成登录，完成后回到 ModAgent 重试当前下载。"
                login_status = "login_required"
            elif "成人内容" in e.reason:
                user_action = "请在已保留的 Nexus 页面确认成人内容显示权限，完成后回到 ModAgent 重试当前下载。"
                login_status = "signed_in_or_not_required"
            elif "人机验证" in e.reason:
                user_action = "请在已保留的 Nexus 页面完成人机验证，完成后回到 ModAgent 重试当前下载。"
                login_status = "signed_in_or_not_required"
            elif "未生成下载位置" in e.reason:
                user_action = (
                    "Nexus 当前没有为该文件生成可用下载位置，手动点击也不会开始下载。"
                    "无需重新登录；请稍后重试，或检查网络/隐私软件是否拦截 Nexus CDN。"
                )
                login_status = "signed_in"
            else:
                user_action = (
                    "页面没有显示必须人工处理的登录或验证步骤；无需重新登录，也不要代点 Slow download。"
                    "请直接重试当前下载，ModAgent 会复用该页面继续自动操作。"
                )
                login_status = "signed_in_or_not_required"
            site_download_error = bool(
                (e.diagnostics or {}).get("site_download_error")
            )
            human_gate = any(token in e.reason for token in (
                "尚未登录", "成人内容", "人机验证",
            ))
            return json.dumps({
                "error": (
                    "nexus_download_location_unavailable"
                    if site_download_error else "manual_download_required"
                    if human_gate else "nexus_automation_retryable"
                ),
                "status": (
                    "retryable_site_error"
                    if site_download_error else "manual_action_required"
                    if human_gate else "retryable_automation_error"
                ),
                "mod_id": _mid,
                "page_url": e.page_url,
                "message": str(e),
                "observed_reason": e.reason,
                "login_status": login_status,
                "download_diagnostics": e.diagnostics,
                "user_action_required": user_action if human_gate else False,
                "automatic_retry_allowed": not human_gate,
                "stop_further_downloads": False,
                "continue_other_items": True,
            }, ensure_ascii=False)
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
        requested_mods = args.get("mods", [])
        preflight = _refresh_local_inventory(cfg)
        skipped_installed = []
        mods = []
        for item in requested_mods:
            mid = str(item.get("mod_id", ""))
            installed = _installed_duplicate(
                slug, "nexus", mid, str(item.get("mod_name") or "")
            )
            if installed:
                if not db.get_mod_by_source(slug, "nexus", mid):
                    db.upsert_mod_source_binding(
                        slug, str(installed.id), "nexus", mid, "", .96,
                        "download_preflight_name", str(item.get("version") or ""),
                    )
                cached_path = find_download(mid, item.get("file_id"))
                skipped_installed.append({
                    "mod_id": mid, "installed_id": str(installed.id),
                    "name": installed.name, "version": installed.version,
                    "cache_cleanup": (
                        downloader.cleanup_installed_archive(cached_path)
                        if cached_path else {"removed": False, "reason": "not_found"}
                    ),
                })
            else:
                mods.append(item)
        nexus_slug, nexus_gid, discovery = current_nexus_identity()
        if not nexus_slug:
            return json.dumps({
                "error": "game_mapping_missing",
                "status": discovery.get("status", "not_detected"),
                "reason": discovery.get("reason", "Nexus game page was not resolved"),
            }, ensure_ascii=False)
        success, failed = [], []
        progress.start([{
            "mod_id": m["mod_id"],
            "name": m.get("mod_name", "") or f"Nexus Mod {m['mod_id']}",
            "source": "nexus",
        } for m in mods])

        manual_action = []

        async def _batch():
            for m in mods:
                mid = m["mod_id"]
                progress.set_status(mid, "downloading")
                try:
                    downloaded = await downloader.download_mod(
                        mod_id=mid, game_slug=nexus_slug, game_id=nexus_gid,
                        api_key=api_key, cdp_port=cfg.chrome_cdp_port,
                        file_id=m.get("file_id"),
                        progress_callback=lambda f, _m=mid: progress.set_pct(_m, int(f * 100)))
                    progress.set_status(mid, "done")
                    success.append({
                        "mod_id": mid,
                        "file_id": downloaded.get("file_id"),
                        "local_path": os.path.abspath(downloaded.get("local_path", "")),
                        "cached": bool(downloaded.get("cached")),
                    })
                except downloader.NexusManualDownloadRequired as e:
                    progress.set_status(
                        mid,
                        "failed",
                        "该项等待 Nexus 页面验证；继续处理其他项",
                    )
                    failed.append({
                        "mod_id": mid,
                        "error": "manual_download_required",
                        "attempted": True,
                    })
                    manual_action.append({
                        "mod_id": mid,
                        "page_url": e.page_url,
                        "message": str(e),
                    })
                    continue
                except Exception as e:
                    progress.set_status(mid, "failed", str(e))
                    failed.append({"mod_id": mid, "error": str(e)})

        asyncio.run(_batch())
        progress.finish()
        return json.dumps({
            "success": success,
            "failed": failed,
            "skipped_installed": skipped_installed,
            "preflight_detected": preflight.get("detected", 0),
            "status": "partial_manual_action_required" if manual_action else "completed",
            "manual_action": manual_action,
            "stop_further_downloads": False,
            "remaining_items_processed": True,
        }, ensure_ascii=False)

    # T06
    elif name == "mod_install_batch":
        if not Tier.can(cfg.tier, "install"):
            return json.dumps({"error": "当前层级不支持安装"}, ensure_ascii=False)
        ids = args.get("mod_ids") or []
        if not isinstance(ids, list) or not ids:
            return json.dumps({"error": "请提供 mod_ids 列表"}, ensure_ascii=False)
        if len(ids) > 30:
            return json.dumps({"error": f"单批最多 30 个(收到 {len(ids)}),请分批"}, ensure_ascii=False)
        dependency_blocks = []
        if stardew.is_stardew(getattr(cfg, "game_name", ""), slug, root):
            for mid in ids:
                local_path = find_download(mid)
                if not local_path:
                    continue
                try:
                    checked = stardew.archive_dependency_preflight(
                        local_path, root, getattr(cfg, "game_name", ""), slug
                    )
                except Exception as exc:
                    return json.dumps({
                        "error": f"星露谷批量安装前依赖检查失败，安装未开始: {exc}",
                        "install_blocked": True,
                    }, ensure_ascii=False)
                if checked.get("install_blocked"):
                    dependency_blocks.append({"mod_id": str(mid), **checked})
        if dependency_blocks:
            return json.dumps({
                "status": "missing_dependencies",
                "install_blocked": True,
                "items": dependency_blocks,
                "message": "批量安装前发现必需前置未满足；尚未创建快照，也未写入游戏目录。",
            }, ensure_ascii=False, indent=2)
        # 整批共享一张安装前快照(治 22 连发时每装一个拍一张的浪费)
        try:
            batch_snap = snapshot.snapshot_create(root, slug,
                                                  trigger_mod_name=f"批量安装 {len(ids)} 个前")
        except (ValueError, FileNotFoundError, RuntimeError) as e:
            return json.dumps({"error": f"批量安装前快照失败,安装未开始: {e}"}, ensure_ascii=False)
        results = []
        for mid in ids:
            local_path = find_download(mid)
            call_args = {"mod_id": mid, "snapshot_id": batch_snap}
            if local_path:
                call_args["local_path"] = local_path
            r = json.loads(execute("mod_install", call_args, cfg))
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
        if mid not in (None, ""):
            installed = db.get_mod(str(mid), slug) or db.get_mod_by_source(slug, "nexus", str(mid))
            if installed:
                supplied_path = args.get("local_path") or find_download(mid)
                cache_cleanup = (
                    downloader.cleanup_installed_archive(supplied_path)
                    if supplied_path else {"removed": False, "reason": "not_found"}
                )
                return json.dumps({
                    "status": "already_installed", "already_installed": True,
                    "install_skipped": True, "mod_id": str(mid),
                    "installed_id": str(installed.id), "name": installed.name,
                    "version": installed.version,
                    "cache_cleanup": cache_cleanup,
                    "message": "当前游戏已安装该 Mod，未重复覆盖。需要升级时请使用 mod_update。",
                }, ensure_ascii=False)
        local_path = args.get("local_path") or ""
        if local_path and not os.path.isabs(local_path):
            basename = os.path.basename(local_path)
            local_path = next((os.path.join(downloader.DOWNLOADS_DIR, b, basename)
                               for b in download_buckets()
                               if os.path.exists(os.path.join(downloader.DOWNLOADS_DIR, b, basename))), "")
        # Nexus mod：可只给 mod_id，自动在下载目录里找
        if (not local_path or not os.path.exists(local_path)) and mid not in (None, ""):
            local_path = find_download(mid)
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

        try:
            dependency_preflight = stardew.archive_dependency_preflight(
                local_path, root, getattr(cfg, "game_name", ""), slug
            )
        except Exception as exc:
            return json.dumps({
                "error": f"星露谷安装前依赖检查失败，未写入任何文件: {exc}",
                "install_blocked": True,
            }, ensure_ascii=False)
        if dependency_preflight.get("install_blocked"):
            return json.dumps({
                "status": "missing_dependencies",
                **dependency_preflight,
                "hint": "请先补齐 missing_dependencies，并升级 incompatible_dependencies 中版本不足的前置，再重新执行安装。",
            }, ensure_ascii=False, indent=2)

        snap_id = args.get("snapshot_id", "")
        if not snap_id:
            snap_id = snapshot.snapshot_create(root, slug, trigger_mod_name=f"安装前快照")
        lo = db.get_max_load_order(slug) + 1
        try:
            result = installer.install_mod(local_path, root, slug, lo)
        except Exception as exc:
            rollback = snapshot.snapshot_restore(snap_id)
            return json.dumps({
                "error": f"安装事务失败，已恢复安装前快照: {exc}",
                "snapshot_id": snap_id,
                "rollback_complete": bool(rollback.get("complete")),
                "rollback": rollback,
            }, ensure_ascii=False, indent=1)
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
        try:
            db.add_mod(mod)
        except Exception as exc:
            rollback = snapshot.snapshot_restore(snap_id)
            return json.dumps({
                "error": f"安装文件已复核，但数据库登记失败，已恢复安装前快照: {exc}",
                "snapshot_id": snap_id,
                "rollback_complete": bool(rollback.get("complete")),
                "rollback": rollback,
            }, ensure_ascii=False, indent=1)
        cache_cleanup = downloader.cleanup_installed_archive(local_path)
        return json.dumps({"snapshot_id": snap_id, "files_installed": files_installed,
                           "load_order": lo, "name": mod_name,
                           "cache_cleanup": cache_cleanup,
                           "warnings": result.get("errors", [])}, indent=2, ensure_ascii=False)

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

        try:
            dependency_preflight = stardew.archive_dependency_preflight(
                local_path, root, getattr(cfg, "game_name", ""), slug
            )
        except Exception as exc:
            return json.dumps({
                "error": f"星露谷安装前依赖检查失败，未写入任何文件: {exc}",
                "install_blocked": True,
            }, ensure_ascii=False)
        if dependency_preflight.get("install_blocked"):
            return json.dumps({
                "status": "missing_dependencies",
                **dependency_preflight,
                "hint": "请先补齐 missing_dependencies，并升级 incompatible_dependencies 中版本不足的前置，再重新执行安装。",
            }, ensure_ascii=False, indent=2)

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

        try:
            db.add_mod(db.InstalledMod(
                id=mid, name=mid, version="", snapshot_id=snap_id,
                load_order=db.get_max_load_order(slug) + 1,
                files_installed=json.dumps(files_installed),
                dependencies=json.dumps(explicit_deps or []),
                installed_by="custom", game_slug=slug,
            ))
        except Exception as exc:
            rollback = snapshot.snapshot_restore(snap_id)
            return json.dumps({
                "error": f"安装文件已复核，但数据库登记失败，已恢复安装前快照: {exc}",
                "snapshot_id": snap_id,
                "rollback_complete": bool(rollback.get("complete")),
                "rollback": rollback,
            }, ensure_ascii=False, indent=1)
        cache_cleanup = downloader.cleanup_installed_archive(local_path)
        return json.dumps({
            "snapshot_id": snap_id, "installed": len(files_installed),
            "files_installed": files_installed,
            "custom_domain_registered": sorted(i["rel"] for i in result.get("installed", [])),
            "skipped": result.get("skipped", []),
            "rejected": plan.get("rejected", []),
            "warnings": result.get("warnings", []),
            "cache_cleanup": cache_cleanup,
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
        external_cleanup = user_config.uninstall_mod_configs(slug, str(mid))
        db.remove_mod(mid, slug)
        return json.dumps({"removed": len(result["removed"]),
                           "kept_shared": len(result.get("kept_shared", [])),
                           "snapshot_id": snap_id,
                           "dependents_warned": [d["name"] for d in deps],
                           "external_config_cleanup": external_cleanup,
                           "details": result}, indent=2, ensure_ascii=False)

    # T08
    elif name == "conflict_check":
        result = installer.conflict_check(args["local_path"], root, slug)
        return json.dumps(result, indent=2, ensure_ascii=False)

    # T08b:列出投放文件夹 + 下载缓存里的本地 mod 压缩包(手动下载资源的入口)
    elif name == "list_local_mods":
        dropbox = downloader.ensure_dropbox_dir(slug)
        result, seen = [], set()
        locations = [(dropbox, "投放文件夹")]
        locations += [(os.path.join(downloader.DOWNLOADS_DIR, b), "下载缓存")
                      for b in download_buckets()]
        for d, label in locations:
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

    elif name == "tool_extract":
        try:
            result = downloader.extract_external_tool(
                args.get("local_path", ""), args.get("display_name", "")
            )
        except Exception as e:
            return json.dumps(
                {"error": f"外部工具解压失败: {e}"}, ensure_ascii=False
            )
        result["cache_cleanup"] = downloader.cleanup_installed_archive(
            args.get("local_path", "")
        )
        return json.dumps(result, ensure_ascii=False, indent=2)

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
        # 所有用户发起的回滚都必须先预览并取得明确确认。
        if not args.get("confirmed"):
            pv = snapshot.snapshot_restore_preview(args["snapshot_id"])
            cap = 50
            for k in ("to_delete", "to_restore", "missing_in_snapshot"):
                if len(pv.get(k) or []) > cap:
                    total = len(pv[k])
                    pv[k] = pv[k][:cap] + [f"...(共 {total} 个,已截断)"]
            return json.dumps({
                "requires_confirmation": True,
                "confirmation_token": confirmation.issue("snapshot_restore", args["snapshot_id"]),
                "preview": pv,
                "note": "请把「将删除/将还原/外部配置/工坊订阅」影响原样展示给用户并停止本轮。"
                        "用户在新一轮明确同意后，携 confirmed=true 和 confirmation_token 重调；不得自行确认。",
            }, ensure_ascii=False, indent=2)
        if not confirmation.consume(args.get("confirmation_token", ""), "snapshot_restore", args["snapshot_id"]):
            return json.dumps({
                "error": "rollback_confirmation_invalid",
                "message": "回滚确认已失效或未经过预览，请重新生成预览并请求用户确认。",
            }, ensure_ascii=False)
        res = snapshot.snapshot_restore(args["snapshot_id"])
        ws = res.get("workshop") or {}
        # 被自动退订的工坊 mod,同步清掉 DB 记录(账本跟事实走)
        for pid in ws.get("unsubscribed", []):
            db.remove_mod("ws_" + pid, slug)
        # 回滚联动清账:快照后安装的 mod 文件刚被回滚删掉,DB 记录不能留成幽灵账。
        # 判定 = 记录里有文件、且所有文件在磁盘上都不存在(连 .disabled 禁用副本也没有)。
        # 工坊 mod 不在此列(文件由 Steam 托管,上面按订阅差集单独处理)。
        mods_cleaned = []
        # 文件复核未通过时保留账本，避免“磁盘没恢复、记录又被清了”的二次损坏。
        if res.get("complete"):
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
               "status": res.get("status", "incomplete"),
               "complete": bool(res.get("complete")),
               "deleted": res.get("deleted", 0),
               "restored": res.get("restored", 0),
               "unchanged_verified": res.get("unchanged_verified", 0),
               "verified_target_files": res.get("verified_target_files", 0),
               "files_restored": res.get("files_restored", 0),
               "operations_applied": res.get("operations_applied", 0),
               "directories_removed": res.get("directories_removed", 0),
               "pending_delete": res.get("pending_delete", []),
               "pending_restore": res.get("pending_restore", []),
               "missing_in_snapshot": res.get("missing_in_snapshot", []),
               "ignored_unsafe_snapshot_files": res.get("ignored_unsafe_snapshot_files", []),
               "mods_cleaned": mods_cleaned,
               "workshop": res.get("workshop"),
               "external_configs": res.get("external_configs")}
        _ignored = out.pop("ignored_unsafe_snapshot_files", [])
        out["ignored_unsafe_snapshot_count"] = len(_ignored)
        if _ignored:
            out["ignored_unsafe_snapshot_sample"] = _ignored[:20]
            out["safety_note"] = "旧快照中的游戏原生文件已被安全域隔离，未覆盖到游戏目录。"
        _failed = res.get("failed") or {}
        _all_failed = _failed.get("delete", []) + _failed.get("restore", [])
        if _all_failed:
            out["failed"] = _failed
            lead = _all_failed[0]   # 同一次回滚的失败通常同因(游戏在跑),取首项归因作主导建议
            out["warning"] = (f"{len(_all_failed)} 个文件操作失败({lead.get('reason','未知原因')}),"
                              f"回滚不完整。{lead.get('action','')}")
        elif not out["complete"]:
            out["warning"] = "回滚后文件级复核仍有差异，不能视为完成；请关闭游戏后重试或查看待处理清单。"
        db.log_operation("snapshot_restore", out)
        return json.dumps(out, ensure_ascii=False)

    elif name == "snapshot_delete":
        _snap = db.get_snapshot(args["snapshot_id"])
        if _snap is None:
            return json.dumps({"error": f"快照不存在: {args['snapshot_id']}"}, ensure_ascii=False)
        if _snap.game_slug and _snap.game_slug != slug:
            return json.dumps({
                "error": f"快照 {args['snapshot_id']} 属于游戏 {_snap.game_slug},当前游戏是 {slug}。"
                         "跨游戏删除已拒绝;请先切换到对应游戏。"}, ensure_ascii=False)
        if not args.get("confirmed"):
            file_count = len(json.loads(_snap.files)) if isinstance(_snap.files, str) else len(_snap.files or [])
            return json.dumps({
                "requires_confirmation": True,
                "action": "snapshot_delete",
                "snapshot_id": _snap.id,
                "game_slug": _snap.game_slug,
                "trigger_mod_name": _snap.trigger_mod_name,
                "timestamp": _snap.timestamp,
                "files_count": file_count,
                "irreversible": True,
                "confirmation_token": confirmation.issue("snapshot_delete", _snap.id),
                "message": "删除后无法再回滚到该快照。请展示此快照的时间、用途和文件数，并等待用户在下一轮明确确认。",
            }, ensure_ascii=False)
        if not confirmation.consume(args.get("confirmation_token", ""), "snapshot_delete", _snap.id):
            return json.dumps({
                "error": "snapshot_delete_confirmation_invalid",
                "message": "删除确认令牌缺失、过期或已使用；请重新生成删除预览并让用户确认。",
            }, ensure_ascii=False)
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

    elif name == "game_config_write":
        try:
            result = user_config.write_config(
                args.get("location", ""),
                args.get("relative_path", ""),
                args.get("content", ""),
                game_slug=slug,
                mod_id=str(args.get("mod_id") or ""),
                mode=args.get("mode") or "merge_ini",
            )
            db.log_operation("game_config_write", result)
            return json.dumps(result, indent=2, ensure_ascii=False)
        except Exception as exc:
            return json.dumps({"error": str(exc)}, ensure_ascii=False)

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
        installed = db.get_installed_mods(slug)
        if args.get("export"):
            r = diagnostics.export_diag_bundle(
                root, slug, cfg, installed,
                db.get_operation_log(limit=500), app_version=__import__("modagent").__version__)
        else:
            r = diagnostics.game_diagnose(root, slug, installed)
            from .diagnostic_impact import build_diagnostic_strategy
            bindings = {str(item["mod_id"]): item for item in db.get_mod_source_bindings(slug)}
            r["diagnostic_strategy"] = build_diagnostic_strategy(r, installed, bindings)
        return json.dumps(r, ensure_ascii=False, indent=1)

    # T16
    elif name == "mod_source_align":
        from .source_alignment import align_installed_mods
        result = align_installed_mods(
            cfg, force_refresh=bool(args.get("force_refresh"))
        )
        return json.dumps(result, indent=2, ensure_ascii=False)

    elif name == "mod_source_bind":
        local_mod_id = str(args.get("local_mod_id") or "").strip()
        nexus_mod_id = int(args.get("nexus_mod_id") or 0)
        mod = db.get_mod(local_mod_id, slug)
        if not mod:
            return json.dumps({
                "error": f"未找到本地已安装 Mod: {local_mod_id}"
            }, ensure_ascii=False)
        if nexus_mod_id <= 0:
            return json.dumps({"error": "Nexus Mod ID 无效"}, ensure_ascii=False)
        try:
            detail = nexus.get_detail(
                nexus_mod_id, slug, api_key, cfg.chrome_cdp_port
            )
        except Exception as exc:
            return json.dumps({
                "error": f"无法核验 Nexus #{nexus_mod_id} 完整详情: {exc}"
            }, ensure_ascii=False)
        preview = {
            "local": {
                "mod_id": str(mod.id),
                "name": mod.name,
                "version": mod.version,
            },
            "nexus": {
                "mod_id": nexus_mod_id,
                "name": detail.get("name") or "",
                "author": detail.get("author") or "",
                "version": detail.get("version") or "",
                "summary": detail.get("summary") or "",
                "description": detail.get("description") or "",
                "dependencies": detail.get("dependencies") or [],
                "updated_at": detail.get("updated_at") or "",
            },
        }
        if not args.get("confirmed"):
            return json.dumps({
                "requires_confirmation": True,
                "message": (
                    "已取得本地项与 Nexus 完整详情；只有用户明确确认二者是同一 Mod，"
                    "才能写入稳定更新绑定"
                ),
                "preview": preview,
            }, ensure_ascii=False, indent=2)
        url = f"https://www.nexusmods.com/{slug}/mods/{nexus_mod_id}"
        db.upsert_mod_source_binding(
            slug, str(mod.id), "nexus", str(nexus_mod_id), url,
            1.0, "user_confirmed", str(detail.get("version") or ""),
            {
                "nexus_slug": slug,
                "matched_name": detail.get("name") or "",
                "author": detail.get("author") or "",
                "summary": detail.get("summary") or "",
                "description": detail.get("description") or "",
                "dependencies": detail.get("dependencies") or [],
                "updated_at": detail.get("updated_at") or "",
            },
        )
        return json.dumps({
            "bound": True,
            "match_method": "user_confirmed",
            "source": "nexus",
            "source_key": str(nexus_mod_id),
            "preview": preview,
        }, ensure_ascii=False, indent=2)

    elif name == "mod_update_check":
        # 先建立稳定来源绑定。Thunderstore 使用完整社区包账本，不再逐个加载网页。
        from .source_alignment import align_installed_mods
        alignment = align_installed_mods(
            cfg, force_refresh=bool(args.get("force_refresh"))
        )
        mods = db.get_installed_mods(slug)
        if not mods:
            return json.dumps({
                "game_slug": slug, "updates_available": [], "items": [],
                "alignment": alignment,
                "summary": {"total": 0, "update_available": 0},
            }, indent=2, ensure_ascii=False)
        updates = []
        items = []
        initial_bindings = {
            str(item["mod_id"]): item for item in db.get_mod_source_bindings(slug)
        }
        nexus_targets = []
        for m in mods:
            binding = initial_bindings.get(str(m.id)) or {}
            upstream_id = (
                str(m.id) if str(m.id).isdigit()
                else str(binding.get("source_key") or "")
                if binding.get("source") == "nexus" else ""
            )
            if upstream_id.isdigit():
                nexus_targets.append((m, upstream_id))
        dependencies_refreshed = 0
        failed_checks = []
        latest_by_id = {}

        def inspect_mod(m, upstream_id):
            try:
                info = nexus.get_mod(int(upstream_id), slug, api_key, cdp_port=cfg.chrome_cdp_port)
                return m, upstream_id, info, ""
            except Exception as exc:
                return m, upstream_id, {}, str(exc)

        if nexus_targets:
            from concurrent.futures import ThreadPoolExecutor, as_completed
            workers = min(12, len(nexus_targets))
            with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="mod-update-check") as pool:
                futures = [pool.submit(inspect_mod, m, upstream_id)
                           for m, upstream_id in nexus_targets]
                for future in as_completed(futures):
                    m, upstream_id, info, error = future.result()
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
                    latest_by_id[str(m.id)] = latest
                    binding = db.get_mod_source_binding(str(m.id), slug)
                    if binding:
                        try:
                            binding_metadata = json.loads(
                                binding.get("metadata") or "{}"
                            )
                        except (TypeError, ValueError, json.JSONDecodeError):
                            binding_metadata = {}
                        binding_metadata["dependencies"] = dependencies
                        db.upsert_mod_source_binding(
                            slug, str(m.id), "nexus", upstream_id,
                            binding.get("source_url") or "",
                            binding.get("confidence") or 1,
                            binding.get("match_method") or "stable_id",
                            latest, binding_metadata,
                        )

        failed_by_id = {
            str(item["mod_id"]): item["error"] for item in failed_checks
        }
        bindings = {
            str(item["mod_id"]): item
            for item in db.get_mod_source_bindings(slug)
        }
        for m in mods:
            mid = str(m.id)
            binding = bindings.get(mid)
            source = (binding or {}).get("source") or ""
            latest = (
                latest_by_id.get(mid)
                or (binding or {}).get("latest_version")
                or ""
            )
            current = str(m.version or "").strip()
            current_known = bool(
                current and current.casefold() not in {"unknown", "vunknown", "n/a", "none"}
            )
            row = {
                "mod_id": mid,
                "name": m.name,
                "current": current or "unknown",
                "latest": latest,
                "source": source or "unbound",
                "source_key": (binding or {}).get("source_key") or "",
                "url": (binding or {}).get("source_url") or "",
                "binding_confidence": (binding or {}).get("confidence") or 0,
                "match_method": (binding or {}).get("match_method") or "",
                "can_update": False,
            }
            if mid in failed_by_id:
                row.update(status="check_failed", reason=failed_by_id[mid])
            elif source == "workshop":
                row.update(
                    status="managed_externally",
                    reason="Steam 创意工坊负责自动更新",
                )
            elif not binding:
                row.update(
                    status="unbound",
                    reason="尚未找到足够可信的维护页绑定",
                )
            elif not latest:
                row.update(
                    status="check_failed",
                    reason="已绑定维护页，但本次未取得最新版号",
                )
            elif not current_known:
                row.update(
                    status="version_unknown",
                    reason="本地未记录版本，可同步安装上游最新版",
                    can_update=source in {"nexus", "thunderstore"},
                )
            elif _same_version(current, latest):
                row.update(status="up_to_date", reason="本地版本与上游一致")
            else:
                relation = _version_relation(current, latest)
                if relation == "newer":
                    row.update(
                        status="local_newer",
                        reason="本地版本号高于维护页最新版，未自动降级",
                    )
                else:
                    row.update(
                        status="update_available",
                        reason="维护页存在不同的更新版本",
                        can_update=source in {"nexus", "thunderstore"},
                    )
            if row["can_update"] and row["status"] in {
                "update_available", "version_unknown"
            }:
                updates.append({
                    "mod_id": mid, "name": m.name, "current": row["current"],
                    "latest": latest, "source": source, "url": row["url"],
                    "status": row["status"], "changelog": "",
                })
            items.append(row)

        updates.sort(key=lambda item: item["name"].lower())
        items.sort(key=lambda item: item["name"].casefold())
        summary = {
            "total": len(items),
            "bound": sum(1 for item in items if item["source"] != "unbound"),
            "update_available": sum(
                1 for item in items
                if item["status"] in {"update_available", "version_unknown"}
                and item["can_update"]
            ),
            "up_to_date": sum(1 for item in items if item["status"] == "up_to_date"),
            "version_unknown": sum(1 for item in items if item["status"] == "version_unknown"),
            "managed_externally": sum(1 for item in items if item["status"] == "managed_externally"),
            "unbound": sum(1 for item in items if item["status"] == "unbound"),
            "check_failed": sum(1 for item in items if item["status"] == "check_failed"),
        }
        return json.dumps({
            "game_slug": slug,
            "updates_available": updates,
            "items": items,
            "summary": summary,
            "alignment": alignment,
            "dependencies_refreshed": dependencies_refreshed,
            "checked_nexus": len(nexus_targets) - len(failed_checks),
            "checked_thunderstore": sum(
                1 for item in items
                if item["source"] == "thunderstore" and item["latest"]
            ),
            "failed_checks": failed_checks,
            "unchecked_non_nexus": summary["unbound"],
            "note": "版本未知表示本地扫描未取得版本；已绑定项仍可安全同步到上游最新版。"
        }, indent=2, ensure_ascii=False)

    # T17
    elif name == "mod_update":
        mod = db.get_mod(args["mod_id"], slug)
        if not mod:
            return json.dumps({"error": f"Mod {args['mod_id']} 未安装"}, ensure_ascii=False)
        binding = db.get_mod_source_binding(str(mod.id), slug)
        source = (binding or {}).get("source") or (
            "nexus" if str(mod.id).isdigit() else ""
        )
        if source == "thunderstore":
            from .sources import thunderstore
            url = (binding or {}).get("source_url") or ""
            if not url:
                return json.dumps({
                    "error": "Thunderstore 绑定缺少维护页 URL，请重新执行 mod_source_align"
                }, ensure_ascii=False)
            try:
                path_result = thunderstore.download(url, slug)
            except Exception as exc:
                return json.dumps({
                    "error": f"Thunderstore 最新版下载失败: {exc}"
                }, ensure_ascii=False)
            path = path_result.get("local_path")
            latest_version = path_result.get("version") or (
                binding or {}
            ).get("latest_version") or mod.version
        elif source == "nexus":
            upstream_id = str((binding or {}).get("source_key") or mod.id)
            if not upstream_id.isdigit():
                return json.dumps({"error": "Nexus 绑定缺少有效 Mod ID，请重新执行一键绑定"}, ensure_ascii=False)
            main = nexus.get_main_file(int(upstream_id), slug, api_key)
            if not main or not main.get("file_id"):
                return json.dumps({"error": "无法获取最新版本信息或文件 ID"}, ensure_ascii=False)
            path_result = asyncio.run(downloader.download_mod(
                mod_id=int(upstream_id), game_slug=slug, game_id=gid,
                api_key=api_key, cdp_port=cfg.chrome_cdp_port))
            path = path_result.get("local_path")
            latest_version = main.get("version", mod.version)
        else:
            return json.dumps({
                "error": "该 Mod 尚未绑定到可自动更新的 Nexus/Thunderstore 维护页",
                "mod_id": str(mod.id),
                "hint": "先运行 mod_source_align；歧义项需要用户确认正确维护页。",
            }, ensure_ascii=False)
        if not path or not os.path.exists(path):
            return json.dumps({"error": "最新版下载未产生可安装文件"}, ensure_ascii=False)
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
            if stardew.is_stardew(
                getattr(cfg, "game_name", ""), slug, root
            ):
                real_mods = os.path.realpath(os.path.join(root, "Mods"))
                misplaced = []
                for installed_path in new_files:
                    try:
                        inside_mods = (
                            os.path.commonpath([
                                real_mods, os.path.realpath(installed_path)
                            ]) == real_mods
                        )
                    except ValueError:
                        inside_mods = False
                    if not inside_mods:
                        misplaced.append(installed_path)
                if misplaced or not result.get("verified_mods"):
                    raise RuntimeError(
                        "SMAPI 更新验收失败：新版本未完整安装到 Stardew Valley/Mods"
                    )
        except Exception as exc:
            try:
                rollback = snapshot.snapshot_restore(snap_id)
                failed = rollback.get("failed") or {}
                rollback_ok = bool(rollback.get("complete"))
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
        mod.version = latest_version
        if source == "nexus":
            try:
                upstream_id = str((binding or {}).get("source_key") or mod.id)
                info = nexus.get_mod(int(upstream_id), slug, api_key, cdp_port=cfg.chrome_cdp_port)
                mod.dependencies = json.dumps(db.parse_dependencies(info.get("dependencies", [])))
            except Exception:
                pass
        mod.files_installed = json.dumps(new_files, ensure_ascii=False)
        mod.snapshot_id = snap_id
        db.update_mod(mod)
        cache_cleanup = downloader.cleanup_installed_archive(path)
        if binding:
            db.upsert_mod_source_binding(
                slug, str(mod.id), source, binding["source_key"],
                binding.get("source_url") or "", binding.get("confidence") or 1,
                binding.get("match_method") or "stable_id", mod.version,
                json.loads(binding.get("metadata") or "{}"),
            )
        return json.dumps({"updated": mod.name, "version": mod.version,
                           "source": source,
                           "install_handler": result.get("handler", ""),
                           "verified_mods": result.get("verified_mods", []),
                           "snapshot_id": snap_id, "cache_cleanup": cache_cleanup},
                          indent=2, ensure_ascii=False)

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
        full_plan = dependents + [mod]
        plan = [item for item in full_plan if not installer.is_mod_disabled(_mod_files(item))]
        already_disabled = [item for item in full_plan if installer.is_mod_disabled(_mod_files(item))]
        dependent_info = [
            _toggle_mod_info(item) for item in dependents
            if not installer.is_mod_disabled(_mod_files(item))
        ]
        if not args.get("confirmed"):
            from .diagnostic_impact import build_disable_impact
            bindings = {str(item["mod_id"]): item for item in db.get_mod_source_bindings(slug)}
            return json.dumps({
                "requires_confirmation": True,
                "action": "disable",
                "target": _toggle_mod_info(mod),
                "dependents": dependent_info,
                "will_disable": [_toggle_mod_info(item) for item in plan],
                "already_disabled": [_toggle_mod_info(item) for item in already_disabled],
                "file_count": sum(len(_mod_files(item)) for item in plan),
                "external_configs": user_config.preview_toggle_mod_configs(slug, [str(item.id) for item in plan]),
                "decision_support": build_disable_impact(
                    mod, plan, already_disabled, db.get_installed_mods(slug), bindings),
                "confirmation_token": confirmation.issue("mod_disable", str(mod.id)),
                "note": "请先说明会失去和保留的功能、诊断理由、恢复方法及下一步，再等待用户下一轮明确确认；文件数只作技术附注。",
            }, indent=2, ensure_ascii=False)
        if not confirmation.consume(args.get("confirmation_token", ""), "mod_disable", str(mod.id)):
            return json.dumps({
                "error": "mod_disable_confirmation_invalid",
                "message": "禁用确认令牌缺失、过期或已使用；请重新生成禁用预览并让用户确认。",
            }, ensure_ascii=False)
        if not plan:
            return json.dumps({
                "disabled": 0, "disabled_mods": [], "already_disabled": True,
                "verified": True,
                "message": "目标及其依赖项已经禁用，本次未重复修改文件。",
            }, indent=2, ensure_ascii=False)
        operation = _execute_toggle_plan(plan, enabling=False, game_slug=slug)
        if operation.get("error"):
            return json.dumps(operation, indent=2, ensure_ascii=False)
        details = operation["details"]
        total_files = sum(len(item["disabled"]) for item in details)
        changed = [_toggle_mod_info(item, disabled=True) for item in plan]
        return json.dumps({
            "disabled": total_files, "disabled_mods": changed,
            "cascade": bool(dependents), "details": details,
            "external_configs": operation.get("external_configs"),
            "verified": all(installer.is_mod_disabled(_mod_files(item)) for item in plan)
                        and bool(operation.get("external_configs", {}).get("complete", True)),
        }, indent=2, ensure_ascii=False)

    elif name == "mod_enable":
        mod = db.get_mod(args["mod_id"], slug)
        if not mod:
            return json.dumps({"error": f"未找到 Mod: {args['mod_id']}"}, ensure_ascii=False)
        dependencies, missing = db.get_dependency_chain(mod.id, slug)
        dependency_info = [_toggle_mod_info(item) for item in dependencies]
        if missing:
            return json.dumps({
                "blocked": True,
                "action": "enable",
                "target": _toggle_mod_info(mod),
                "dependencies": dependency_info,
                "missing_dependencies": missing,
                "note": "缺少前置依赖，已阻止启用；请先安装缺失依赖。",
            }, indent=2, ensure_ascii=False)
        if dependencies and not args.get("confirmed"):
            return json.dumps({
                "requires_confirmation": True,
                "action": "enable",
                "target": _toggle_mod_info(mod),
                "dependencies": dependency_info,
                "will_enable": dependency_info + [_toggle_mod_info(mod)],
                "note": "此 Mod 需要以下前置依赖；继续会先启用依赖，再启用目标 Mod。",
            }, indent=2, ensure_ascii=False)
        plan = dependencies + [mod]
        operation = _execute_toggle_plan(plan, enabling=True, game_slug=slug)
        if operation.get("error"):
            return json.dumps(operation, indent=2, ensure_ascii=False)
        details = operation["details"]
        total_files = sum(len(item["enabled"]) for item in details)
        changed = [_toggle_mod_info(item, disabled=False) for item in plan]
        return json.dumps({
            "enabled": total_files, "enabled_mods": changed,
            "dependencies_enabled": len(dependencies), "details": details,
            "external_configs": operation.get("external_configs"),
        }, indent=2, ensure_ascii=False)

    elif name == "stardew_smapi_status":
        return json.dumps(
            stardew.smapi_status(root, getattr(cfg, "game_name", ""), slug),
            ensure_ascii=False,
            indent=2,
        )

    elif name == "game_file_check":
        rel = (args.get("path") or "").strip().replace("\\", "/").lstrip("/")
        gr = os.path.realpath(root or "")
        if not gr or not os.path.isdir(gr):
            return json.dumps({"error": "未配置有效的游戏根目录"}, ensure_ascii=False)
        full = os.path.realpath(os.path.join(gr, rel))
        if not (full == gr or full.startswith(gr + os.sep)):
            return json.dumps({"error": "路径越界:只允许查看游戏目录内的文件"}, ensure_ascii=False)
        if not os.path.exists(full):
            return json.dumps({
                "exists": False,
                "path": rel,
                "absolute_path": full,
                "game_root": gr,
            }, ensure_ascii=False)
        info = {
            "exists": True,
            "path": rel,
            "absolute_path": full,
            "game_root": gr,
            "is_dir": os.path.isdir(full),
        }
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
        dirs = [(b, os.path.join(downloader.DOWNLOADS_DIR, b)) for b in download_buckets()]
        if not any(os.path.isdir(d) for _, d in dirs):
            return json.dumps({"count": 0, "files": [],
                               "note": "当前游戏的本地/Nexus 下载缓存均为空"}, ensure_ascii=False)
        import re as _re
        items, seen = [], set()
        for bucket, d in dirs:
            if not os.path.isdir(d):
                continue
            for f in sorted(os.listdir(d)):
                if not f.lower().endswith((".zip", ".7z", ".rar")):
                    continue
                full = os.path.join(d, f)
                key = os.path.normcase(os.path.realpath(full))
                if key in seen:
                    continue
                seen.add(key)
                try:
                    size_mb = round(os.path.getsize(full) / 1048576, 1)
                except OSError:
                    size_mb = 0
                m = _re.match(r"^(\d+)_(.+?)\.(zip|7z|rar)$", f, _re.I)
                mid = m.group(1) if m else ""
                nm = (m.group(2) if m else os.path.splitext(f)[0]).replace("_", " ")
                items.append({"file": f, "mod_id": mid, "name": nm,
                              "size_mb": size_mb, "local_path": full,
                              "cache_bucket": bucket})
        return json.dumps({"count": len(items), "files": items}, ensure_ascii=False)

    return json.dumps({"error": f"未知工具: {name}"}, ensure_ascii=False)


def _recommend_nexus(
    query: str, slug: str, api_key: str, limit: int = 10,
    cdp_port: int = 18888,
) -> dict:
    """Search Nexus, then verify usable results through the detail endpoint."""
    import concurrent.futures as cf

    import inspect
    search_parameters = inspect.signature(nexus.search).parameters
    if "cdp_port" in search_parameters or any(
        parameter.kind == inspect.Parameter.VAR_KEYWORD
        for parameter in search_parameters.values()
    ):
        results = nexus.search(
            query[:60], slug, api_key, cdp_port=cdp_port
        )
    else:
        # Keep source adapters replaceable by small third-party/test adapters
        # that implement the original three-argument search contract.
        results = nexus.search(query[:60], slug, api_key)
    recs = []
    for r in (results or [])[:max(2, min(int(limit or 10), 20))]:
        try:
            mod_id = int(r.get("mod_id") or 0)
        except (TypeError, ValueError):
            mod_id = 0
        # Category, search and game-home pages are discovery noise, not mods.
        if mod_id <= 0:
            continue
        recs.append({
            "mod_id": mod_id,
            "name": r.get("name", ""),
            "summary": r.get("summary", ""),
            "version": r.get("version", ""),
            "updated_at": r.get("updated_time") or r.get("updated", ""),
            "url": (
                f"https://www.nexusmods.com/{slug}/mods/{mod_id}"
                if mod_id else ""
            ),
            "reason": f"评分 {r.get('endorsement_count', 0)}，最近更新 {r.get('updated_time', '')}",
            "endorsements": r.get("endorsement_count", 0),
            "dependencies": [],
            "dependencies_pending_detail": bool(mod_id),
        })

    verified_by_id = {}
    errors = {}

    def verify(row):
        mod_id = int(row["mod_id"])
        try:
            detail_parameters = inspect.signature(nexus.get_detail).parameters
            if "cdp_port" in detail_parameters or any(
                parameter.kind == inspect.Parameter.VAR_KEYWORD
                for parameter in detail_parameters.values()
            ):
                detail = nexus.get_detail(
                    mod_id, slug, api_key, cdp_port=cdp_port
                )
            else:
                detail = nexus.get_detail(mod_id, slug, api_key)
            return mod_id, detail, ""
        except Exception as exc:
            return mod_id, {}, (str(exc) or type(exc).__name__)[:160]

    if recs:
        pool = cf.ThreadPoolExecutor(
            max_workers=min(8, len(recs)),
            thread_name_prefix="recommend-detail",
        )
        futures = [pool.submit(verify, row) for row in recs]
        done, not_done = cf.wait(futures, timeout=30)
        for future in done:
            mod_id, detail, error = future.result()
            if detail:
                verified_by_id[mod_id] = detail
            elif error:
                errors[mod_id] = error
        for future in not_done:
            future.cancel()
        pool.shutdown(wait=False)

    enriched = []
    for row in recs:
        mod_id = int(row["mod_id"])
        detail = verified_by_id.get(mod_id)
        if detail:
            merged = dict(row)
            merged.update({
                key: value for key, value in detail.items()
                if value not in (None, "", [], {})
            })
            merged["_detail_verified"] = True
            merged["verification_source"] = "nexus_detail"
            enriched.append(merged)
        else:
            row["_detail_verified"] = False
            row["verification_status"] = "blocked"
            row["verification_error"] = errors.get(
                mod_id, "详情核验超过 30 秒预算"
            )
            enriched.append(row)

    attempted = len(recs)
    verified = len(verified_by_id)
    return {
        "recommendations": enriched,
        "install_plan": [],
        "verification": {
            "target_ratio": 0.95,
            "attempted": attempted,
            "verified": verified,
            "blocked": max(0, attempted - verified),
            "coverage_ratio": round(verified / attempted, 4) if attempted else 1.0,
        },
    }


def _recommend_thunderstore(community: str, query: str, limit: int = 5) -> list:
    """Retry one forced refresh when Thunderstore unexpectedly returns empty."""
    from .sources import thunderstore as ts
    results = ts.search(community, query, limit)
    if not results:
        results = ts.search(community, query, limit, force_refresh=True)
    return results


def _recommend(query: str, cfg: Config) -> dict:
    """多源聚合推荐(#1):按 available_sources 挑当前游戏的可用源并发查询,
    按来源分组返回——各源热度口径不同(评分/订阅/下载量/星数),不做跨源硬排序,
    交 agent 综合叙述。单源失败(如工坊需 Chrome 登录)不阻塞其余源,如实入 sources_failed。
    顶层 recommendations/install_plan 保持 Nexus 结构(兼容旧调用方)。"""
    if not query:
        return {"recommendations": [], "install_plan": [], "note": "请提供需求描述"}

    from .sources import available_sources
    slug, api_key = cfg.game_slug, cfg.nexus_api_key
    per_source_limit = max(
        2, min(int(getattr(cfg, "recommendation_limit", 10) or 10), 20)
    )
    src = available_sources(cfg.game_name or "", slug or "", cfg.game_root or "",
                            getattr(cfg, "tavily_api_key", ""), api_key)
    effective_slug = src.get("nexus") or ""

    import concurrent.futures as cf
    tasks = {}
    ex = cf.ThreadPoolExecutor(max_workers=5)
    if effective_slug:
        tasks["nexus"] = ex.submit(
            _recommend_nexus, query, effective_slug, api_key, per_source_limit,
            cfg.chrome_cdp_port,
        )
    if src.get("workshop"):
        from .sources import steam_workshop as sw
        tasks["workshop"] = ex.submit(
            lambda: asyncio.run(
                sw.search(query, src["workshop"], cfg.chrome_cdp_port)
            )[:per_source_limit]
        )
    if src.get("thunderstore"):
        tasks["thunderstore"] = ex.submit(
            _recommend_thunderstore, src["thunderstore"], query, per_source_limit
        )
    if src.get("gamebanana"):
        from .sources import gamebanana as gb
        tasks["gamebanana"] = ex.submit(
            gb.search, src["gamebanana"], query, per_source_limit
        )
    from .sources import github as gh
    tasks["github"] = ex.submit(
        gh.search, query, cfg.game_name or slug or "", per_source_limit
    )

    source_status = src.get("source_status", {})
    out = {"recommendations": [], "install_plan": [],
           "sources_attempted": list(tasks),
           "sources_consulted": [], "sources_empty": [],
           "sources_failed": {}, "sources_skipped": {},
           "source_evidence": source_status, "verification": {}}
    for source_name in ("nexus", "workshop", "thunderstore", "gamebanana", "github"):
        if source_name not in tasks:
            state = source_status.get(source_name, {})
            out["sources_skipped"][source_name] = {
                "status": state.get("status", "not_detected"),
                "reason": state.get("reason", "source was not selected for this search"),
            }
    # One unhealthy source must not hold all completed sources hostage. The old
    # insertion-order waits could block 90 seconds on Nexus before returning an
    # already-finished Thunderstore/GitHub result.
    done, not_done = cf.wait(list(tasks.values()), timeout=35)
    for name, fut in tasks.items():
        if fut in not_done:
            out["sources_failed"][name] = "该源超过全局 35 秒预算；其他来源结果已保留，可单独重试"
            fut.cancel()
            continue
        try:
            r = fut.result()
        except Exception as e:
            out["sources_failed"][name] = (str(e) or type(e).__name__)[:120]
            continue
        out["sources_consulted"].append(name)
        if name == "nexus":
            out["recommendations"] = r["recommendations"]
            out["install_plan"] = r["install_plan"]
            out["verification"]["nexus"] = r.get("verification") or {}
            if not r["recommendations"]:
                out["sources_empty"].append(name)
        else:
            out[name] = r
            if not r:
                out["sources_empty"].append(name)
    ex.shutdown(wait=False)

    total = len(out["recommendations"]) + sum(
        len(out.get(k) or []) for k in ("workshop", "thunderstore", "gamebanana", "github"))
    if total == 0 and out["sources_failed"]:
        out["note"] = (
            "当前没有获得匹配结果，但存在查询失败的来源；"
            "失败不能解释为该站没有游戏专区或相关 Mod，请检查网络/API 后重试。"
        )
    elif total == 0:
        out["note"] = (
            "已成功查询的来源暂未命中；不能据此断言相关 Mod 不存在，"
            "可更换关键词重试。"
        )
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
