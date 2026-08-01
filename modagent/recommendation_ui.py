"""Normalize multi-source recommendations for the shared recommendation UI."""

from __future__ import annotations

import hashlib
import html
import json
import re
from datetime import datetime, timezone
from typing import Any

from . import db
from .inventory_match import (
    find_installed_duplicate,
    find_installed_functional_equivalent,
)


SOURCE_LABELS = {
    "nexus": "Nexus",
    "workshop": "Steam 创意工坊",
    "thunderstore": "Thunderstore",
    "gamebanana": "GameBanana",
    "github": "GitHub",
}

SEARCH_TOOL_SOURCES = {
    "nexus_search": "nexus",
    "workshop_search": "workshop",
    "thunderstore_search": "thunderstore",
    "gamebanana_search": "gamebanana",
    "github_search": "github",
}

_CHINESE_RE = re.compile(r"[\u3400-\u9fff]")
_MARKDOWN_TABLE_SEPARATOR_RE = re.compile(
    r"^\s*:?-{3,}:?(?:\s*\|\s*:?-{3,}:?)+\s*$"
)

RECOMMENDATION_FALLBACK_TEXT = (
    "已根据本轮搜索与详情核验整理候选，并综合考虑更新时间、版本、依赖和潜在冲突。"
)
MISSING_CONTENT_TEXT = "来源未返回功能简介；目前只能确认标题，功能与适配性尚未核验。"


def _text(value: Any, fallback: str = "") -> str:
    value = str(value or "").strip()
    return value if value else fallback


def _sanitize_source_prose(value: Any) -> str:
    """Remove source-page promotion/contact copy from user-facing summaries."""
    text = _text(value)
    if not text:
        return ""
    promotion_patterns = (
        # e.g. "REPO游戏交流QQ群：824639225。"
        r"(?:\b[A-Z0-9_.-]+\s*)?游戏(?:交流|讨论)?\s*QQ\s*群"
        r"(?:群号|号码|号|：|:|\s)*\d{5,14}\s*[。.!！；;]?",
        r"加入\s*QQ\s*群(?:群号|号码|号|：|:|\s)*\d{5,14}\s*[。.!！；;]?",
        r"QQ\s*群(?:群号|号码|号|：|:|\s)*\d{5,14}\s*[。.!！；;]?",
    )
    for pattern in promotion_patterns:
        text = re.sub(pattern, " ", text, flags=re.I)
    return re.sub(r"\s+", " ", text).strip()


def _plain_detail(*values: Any) -> str:
    """Preserve useful source detail while removing page markup and noise."""
    parts = []
    for value in values:
        text = _text(value)
        if not text:
            continue
        text = re.sub(
            r"<(?:script|style)\b[^>]*>.*?</(?:script|style)>",
            " ", text, flags=re.I | re.S,
        )
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\[/?[a-z][^\]]*\]", " ", text, flags=re.I)
        text = html.unescape(text)
        text = _sanitize_source_prose(text)
        if text and not any(text.casefold() == item.casefold() for item in parts):
            parts.append(text)
    return " ".join(parts)[:1600]


def _source_coverage_text(payload: dict | None) -> str:
    if not isinstance(payload, dict):
        return ""
    counts = payload.get("source_counts") or {}
    parts = [
        f"{SOURCE_LABELS.get(source, source)} {int(count)} 项"
        for source, count in counts.items()
        if int(count or 0) > 0
    ]
    if not parts:
        return ""
    return "本轮各来源返回候选：" + "、".join(parts) + "。"


def recommendation_analysis_text(value: Any, payload: dict | None = None) -> str:
    """Render every structured candidate; model prose may not omit rows."""
    items = (payload or {}).get("items") or []
    if not items:
        text = _text(value, RECOMMENDATION_FALLBACK_TEXT)
        kept = []
        for line in text.splitlines():
            stripped = line.strip()
            if (
                (stripped.startswith("|") and stripped.endswith("|"))
                or _MARKDOWN_TABLE_SEPARATOR_RE.fullmatch(stripped)
                or stripped in {"---", "***", "___"}
            ):
                continue
            kept.append(line)
        cleaned = "\n".join(kept).strip() or RECOMMENDATION_FALLBACK_TEXT
        return cleaned + "\n\n请在下方清单中核对功能、来源与风险后再选择。"

    verified = sum(1 for item in items if item.get("detail_verified"))
    lines = [
        f"找到了 {len(items)} 个候选，其中 {verified} 个已取得来源详情。"
        "下面逐项说明它们具体做什么，以及选择前需要注意的条件：",
        "",
    ]
    selected_keys = {
        _text(key) for key in (
            list((payload or {}).get("selected_keys") or [])
            + list((payload or {}).get("wanted_keys") or [])
        )
        if _text(key)
    }
    selected_target_names = {
        _text(item.get("localized_name") or item.get("name"))
        for item in items
        if (
            not item.get("is_prerequisite")
            and item.get("selection_key") in selected_keys
        )
    }
    requirements = [
        requirement
        for requirement in ((payload or {}).get("dependency_requirements") or [])
        if selected_target_names.intersection(requirement.get("required_by") or [])
    ]
    if requirements:
        lines.append("**前置 / 必要依赖（优先处理）**")
        visible_requirements = requirements[:8]
        for requirement in visible_requirements:
            required_by = "、".join(requirement.get("required_by") or [])
            status = {
                "ready": "已匹配可安装候选",
                "needs_resolution": "已匹配，但需要先处理",
                "satisfied_installed": "本机已安装",
                "satisfied_local": "当前环境已满足",
                "unresolved": "尚未匹配明确来源",
            }.get(requirement.get("status"), "待核验")
            lines.append(
                f"- {requirement.get('name') or '未命名依赖'}：{status}"
                + (f"；被 {required_by} 需要" if required_by else "")
            )
        if len(requirements) > len(visible_requirements):
            lines.append(
                f"- 其余 {len(requirements) - len(visible_requirements)} 项仅属于当前所选目标，"
                "可在下方依赖面板中按需展开。"
            )
        lines.append("")
    for index, item in enumerate(items, 1):
        source = _text(item.get("source"))
        source_id = _text(item.get("source_id"))
        if source == "nexus" and item.get("mod_id"):
            identity = f"Nexus #{item['mod_id']}"
        elif source_id:
            identity = f"{_text(item.get('source_label'), source)} {source_id}"
        else:
            identity = _text(item.get("source_label"), source)

        original_name = _text(item.get("name"), "未命名 Mod")
        localized_name = _text(item.get("localized_name"))
        display_name = (
            f"{localized_name} / {original_name}"
            if localized_name and localized_name != original_name
            else original_name
        )
        lines.append(
            f"{index}. "
            + ("**[前置依赖]** " if item.get("is_prerequisite") else "")
            + f"**{display_name}**"
            + (f" ({identity})" if identity else "")
        )
        lines.append(_text(item.get("content"), MISSING_CONTENT_TEXT))

        facts = []
        version = _text(item.get("version"))
        if version and version != "待详情核验":
            facts.append(f"版本 {version}")
        dependencies = [
            _text(dependency) for dependency in item.get("dependencies") or []
            if _text(dependency)
        ]
        if dependencies:
            facts.append("需要 " + "、".join(dependencies[:5]))
        if item.get("required_by"):
            facts.append("被 " + "、".join(item["required_by"][:5]) + " 需要")
        if item.get("detail_verified"):
            facts.append("来源详情已核验")
        else:
            facts.append(
                "详情核验受阻，暂不可加入安装计划"
                if item.get("verification_status") == "blocked"
                else "仅有搜索证据，暂不可加入安装计划"
            )
        conflict = _text(item.get("conflict"))
        if conflict and conflict not in {
            "基础详情已核验，安装包仍需检查",
            "仅有搜索摘要，待详情核验",
        }:
            facts.append(conflict)
        if facts:
            lines.append("选择提示：" + "；".join(facts) + "。")
        lines.append("")

    coverage = _source_coverage_text(payload)
    if coverage:
        lines.extend([coverage, ""])
    lines.append(
        "请先根据上述功能说明选择；暂不可安装的候选可以保留为待处理目标，"
        "取得详情证据后才能进入安装计划。下载后还会继续检查安装包和目标游戏版本。"
    )
    return "\n".join(lines).strip()


def needs_chinese_localization(value: Any) -> bool:
    """True only when an existing description still contains no Chinese."""
    text = _text(value)
    # Missing evidence must stay visibly missing. Asking the model to infer a
    # function from the title turns uncertainty into a fabricated description.
    if not text or text == MISSING_CONTENT_TEXT:
        return False
    return not _CHINESE_RE.search(text)


def needs_chinese_name(value: Any) -> bool:
    """Whether an original source title would benefit from a Chinese display alias."""
    text = _text(value)
    return bool(text) and not _CHINESE_RE.search(text)


def apply_chinese_descriptions(payload: dict, translations: Any) -> dict:
    """Apply model translations by stable selection key, never exposing English fallback."""
    if not isinstance(payload, dict):
        return payload
    if isinstance(translations, str):
        fenced = re.search(r"```(?:json)?\s*(.*?)```", translations, re.S | re.I)
        candidate = fenced.group(1) if fenced else translations
        try:
            translations = json.loads(candidate)
        except (TypeError, ValueError, json.JSONDecodeError):
            translations = []
    if isinstance(translations, dict):
        translations = translations.get("items") or translations.get("translations") or []

    localized = {}
    localized_names = {}
    if isinstance(translations, list):
        for row in translations:
            if not isinstance(row, dict):
                continue
            key = _text(row.get("selection_key") or row.get("key"))
            content = _text(row.get("content") or row.get("description"))
            localized_name = _text(
                row.get("localized_name") or row.get("name_zh") or row.get("chinese_name")
            )
            if key and content and _CHINESE_RE.search(content):
                localized[key] = content[:280]
            if key and localized_name and _CHINESE_RE.search(localized_name):
                localized_names[key] = localized_name[:80]

    for item in payload.get("items") or []:
        if not isinstance(item, dict):
            continue
        key = _text(item.get("selection_key"))
        if needs_chinese_name(item.get("name")):
            item["localized_name"] = localized_names.get(
                key, _text(item.get("localized_name"))
            )
        if needs_chinese_localization(item.get("content")):
            item["content"] = localized.get(
                key,
                "原始简介暂未完成中文转换；请打开来源页面核对功能、版本与兼容性。",
            )
    return payload


def _key(source: str, item: dict) -> str:
    raw_id = (
        item.get("mod_id") or item.get("id") or item.get("full_name")
        or item.get("url") or item.get("name")
    )
    raw = f"{source}:{raw_id}"
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]
    return f"{source}:{digest}"


def _dependencies(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    result = []
    for item in value:
        if isinstance(item, dict):
            label = item.get("name") or item.get("mod_id") or item.get("id")
        else:
            label = item
        label = _text(label)
        if label and label not in result:
            result.append(label)
    return result[:8]


def _format_updated(value: Any) -> str:
    text = _text(value)
    if not text:
        return "待详情核验"
    iso = text.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(iso).date().isoformat()
    except (TypeError, ValueError):
        return text[:16]


def _freshness(value: Any) -> str:
    text = _text(value)
    if not text:
        return "更新时间待核验"
    try:
        updated = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if updated.tzinfo is None:
            updated = updated.replace(tzinfo=timezone.utc)
        days = max(0, (datetime.now(timezone.utc) - updated).days)
    except (TypeError, ValueError):
        return "已提供更新时间"
    if days <= 90:
        return "近 3 个月更新"
    if days <= 365:
        return "近 1 年更新"
    return f"约 {max(1, days // 30)} 个月未更新"


def _recommendation_reason(
    item: dict, updated: Any, detail_verified: bool, has_function_summary: bool,
) -> str:
    explicit = _text(item.get("recommendation_reason") or item.get("reason"))
    facts = []
    downloads = item.get("downloads") or item.get("mod_downloads")
    endorsements = item.get("endorsements") or item.get("endorsement_count")
    if downloads:
        facts.append(f"{downloads} 次下载")
    if endorsements:
        facts.append(f"{endorsements} 次认可")
    if updated:
        facts.append(_freshness(updated))
    if detail_verified:
        facts.append("详情已核验")
    if facts:
        return " · ".join(facts)[:160]
    if explicit and not re.fullmatch(r"评分\s*0[，,]\s*最近更新\s*", explicit):
        return explicit[:160]
    if not has_function_summary:
        return "目前仅匹配到标题，暂无足够信息支持功能推荐"
    return "来自本轮搜索候选，建议结合功能与风险信息判断"


def _loader_name(value: Any) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "", _text(value).casefold())
    if normalized in {"melonloader", "melon"}:
        return "MelonLoader"
    if (
        normalized in {"bepinex", "bepinexpack"}
        or "bepinexpack" in normalized
    ):
        return "BepInEx"
    if normalized in {"smapi"}:
        return "SMAPI"
    return _text(value)


def _loader_from_verified_evidence(item: dict, content: str) -> str:
    """Infer only strong loader requirements from verified page evidence."""
    title = _text(item.get("name") or item.get("full_name"))
    # The loader package itself provides the loader; it must not become its own
    # prerequisite merely because its title contains "BepInExPack".
    if re.sub(r"[^a-z0-9]+", "", title.casefold()) in {
        "bepinex",
        "bepinexpack",
        "melonloader",
        "smapi",
    }:
        return ""
    evidence = " ".join((
        title,
        _text(item.get("summary")),
        _text(item.get("description")),
        _text(item.get("install_notes")),
        _text(content),
    ))
    patterns = (
        (
            r"(?:^|[\s(\[])BepInEx(?:Pack)?(?:[\s)\]]|$)"
            r"|\b(?:requires?|needs?|built\s+for|made\s+for)\s+BepInEx\b"
            r"|(?:需要|要求|前置)[：:\s]*BepInEx\b"
            r"|\bBepInEx[\\/](?:plugins|patchers|config)\b",
            "BepInEx",
        ),
        (
            r"(?:^|[\s(\[])MelonLoader(?:[\s)\]]|$)"
            r"|\b(?:requires?|needs?|built\s+for|made\s+for)\s+MelonLoader\b"
            r"|(?:需要|要求|前置)[：:\s]*MelonLoader\b"
            r"|\bMelonLoader[\\/](?:Mods|UserData)\b",
            "MelonLoader",
        ),
        (
            r"\b(?:requires?|needs?)\s+SMAPI\b"
            r"|(?:需要|要求|前置)[：:\s]*SMAPI\b",
            "SMAPI",
        ),
    )
    return next(
        (loader for pattern, loader in patterns if re.search(pattern, evidence, re.I)),
        "",
    )


def _dependency_identity(value: Any) -> str:
    """Return a version-independent package identity for one dependency label."""
    text = _text(value)
    if not text:
        return ""
    loader = _loader_name(text)
    if loader in {"BepInEx", "MelonLoader", "SMAPI"}:
        return f"loader:{loader.casefold()}"
    normalized = text.casefold()
    normalized = re.sub(r"^(?:custom[_-])?(?:ts[_-])", "", normalized)
    normalized = re.sub(
        r"[-_.\s]+v?\d+(?:\.\d+){1,4}(?:[-+][a-z0-9.-]+)?$",
        "",
        normalized,
    )
    return re.sub(r"[^a-z0-9]+", "", normalized)


def _dependency_version(value: Any) -> tuple[int, ...]:
    text = _text(value)
    match = re.search(
        r"(?:^|[-_.\s])v?(\d+(?:\.\d+){1,4})(?:[-+][a-z0-9.-]+)?$",
        text,
        flags=re.I,
    )
    if not match:
        return ()
    return tuple(int(part) for part in match.group(1).split("."))


def _dependency_identity_matches(left: str, right: str) -> bool:
    if not left or not right:
        return False
    if left == right:
        return True
    if left.startswith("loader:") or right.startswith("loader:"):
        return False
    return min(len(left), len(right)) >= 8 and (
        left.endswith(right) or right.endswith(left)
    )


def _normalize_variants(source: str, item: dict, source_id: Any) -> list[dict]:
    raw_variants = item.get("variants")
    if not isinstance(raw_variants, list):
        raw_variants = []
    variants = []
    seen = set()
    for index, raw in enumerate(raw_variants):
        if not isinstance(raw, dict):
            continue
        file_id = raw.get("file_id")
        variant_id = _text(
            raw.get("variant_id"),
            f"{source}:{source_id}:{file_id if file_id not in (None, '') else index}",
        )
        if not variant_id or variant_id in seen:
            continue
        seen.add(variant_id)
        variants.append({
            "variant_id": variant_id[:180],
            "file_id": file_id,
            "name": _text(
                raw.get("name") or raw.get("label") or raw.get("file_name"),
                f"文件选项 {index + 1}",
            )[:160],
            "file_name": _text(raw.get("file_name"))[:220],
            "version": _text(raw.get("version"))[:48],
            "size_kb": raw.get("size_kb") or 0,
            "description": _plain_detail(
                raw.get("description"), raw.get("install_notes"),
            )[:240],
            "target_slot": _text(raw.get("target_slot"))[:120],
            "is_primary": bool(raw.get("is_primary")),
        })
    if not variants and item.get("file_id") not in (None, ""):
        variants.append({
            "variant_id": f"{source}:{source_id}:{item.get('file_id')}",
            "file_id": item.get("file_id"),
            "name": _text(
                item.get("file_name") or item.get("name"), "主文件",
            )[:160],
            "file_name": _text(item.get("file_name"))[:220],
            "version": _text(
                item.get("version") or item.get("latest_version"),
            )[:48],
            "size_kb": item.get("file_size_kb") or 0,
            "description": "",
            "target_slot": "",
            "is_primary": True,
        })
    if variants and not any(variant.get("is_primary") for variant in variants):
        variants[0]["is_primary"] = True
    return variants


def _normalize_item(source: str, item: dict, mod_loader: str = "") -> dict:
    dependencies = []
    for raw_dependencies in (
        item.get("dependencies"),
        item.get("dependency_labels"),
        item.get("requirements"),
        item.get("deps"),
    ):
        for dependency in _dependencies(raw_dependencies):
            if dependency not in dependencies:
                dependencies.append(dependency)
    dependencies = dependencies[:12]
    archived = bool(item.get("archived"))
    has_files = item.get("has_files")
    detail_verified = bool(item.get("_detail_verified"))
    verification_status = _text(item.get("verification_status"))
    verification_error = _text(item.get("verification_error"))[:200]
    content = _plain_detail(
        item.get("summary"),
        item.get("description"),
        item.get("install_notes"),
    )
    has_function_summary = bool(_text(content))
    staleness = item.get("staleness") if isinstance(item.get("staleness"), dict) else {}
    required_loader = _loader_name(item.get("required_loader"))
    if not required_loader:
        required_loader = next(
            (
                loader for loader in (
                    _loader_name(dependency) for dependency in dependencies
                )
                if loader in {"BepInEx", "MelonLoader", "SMAPI"}
            ),
            "",
        )
    if not required_loader and detail_verified:
        required_loader = _loader_from_verified_evidence(item, content)
    if (
        required_loader
        and not any(_loader_name(dependency) == required_loader for dependency in dependencies)
    ):
        dependencies.insert(0, required_loader)
        dependencies = dependencies[:12]
    active_loader = _loader_name(mod_loader)
    loader_mismatch = bool(
        required_loader
        and active_loader
        and required_loader.casefold() != active_loader.casefold()
    )
    loader_unverified = bool(required_loader and not active_loader)
    if archived:
        conflict_status = "danger"
        conflict = "项目已归档"
    elif has_files is False:
        conflict_status = "warning"
        conflict = "未提供下载文件"
    elif loader_mismatch:
        conflict_status = "danger"
        conflict = (
            f"该 Mod 明确要求 {required_loader}，当前游戏配置为 "
            f"{active_loader}；加载器不兼容，禁止加入安装计划"
        )
    elif loader_unverified:
        conflict_status = "warning"
        conflict = f"该 Mod 明确要求 {required_loader}，但当前加载器尚未核实"
    elif staleness.get("stale"):
        conflict_status = "warning"
        conflict = staleness.get("note") or "较长时间未更新，需核对兼容性"
    elif verification_status == "blocked":
        conflict_status = "warning"
        conflict = (
            f"详情核验受阻：{verification_error}"
            if verification_error else "详情核验受阻，请稍后重试"
        )
    elif not has_function_summary:
        conflict_status = "unknown"
        conflict = "仅确认标题，功能、依赖与兼容性待核验"
    elif detail_verified:
        conflict_status = "clear"
        conflict = "基础详情已核验，安装包仍需检查"
    else:
        conflict_status = "unknown"
        conflict = "仅有搜索摘要，待详情核验"

    version = item.get("version") or item.get("latest_version")
    updated = item.get("updated_at") or item.get("updated_time") or item.get("updated")
    source_id = (
        item.get("mod_id") or item.get("id") or item.get("full_name")
        or item.get("url") or ""
    )
    variants = _normalize_variants(source, item, source_id)
    selected_variant = next(
        (variant for variant in variants if variant.get("is_primary")), None,
    )
    # Keep open-source discovery visible, but only authoritative detail or
    # catalogue evidence may cross into an executable install plan.
    installable = (
        detail_verified
        and not archived
        and has_files is not False
        and bool(source_id)
        and not loader_mismatch
        and not loader_unverified
    )
    if installable:
        resolution_kind = "ready"
        resolution_title = "可以加入安装计划"
        resolution_actions = []
    elif archived:
        resolution_kind = "archived"
        resolution_title = "项目已归档；可保留目标并查看来源页或历史文件"
        resolution_actions = ["keep", "open_source"]
    elif has_files is False:
        resolution_kind = "manual_download"
        resolution_title = "来源未提供可自动取得的文件；可打开页面后手动下载并导入"
        resolution_actions = ["keep", "open_source", "manual_import"]
    elif loader_mismatch:
        resolution_kind = "incompatible_loader"
        resolution_title = (
            f"需要 {required_loader}，当前为 {active_loader}；"
            "不可直接安装到现有加载器目录"
        )
        resolution_actions = ["keep", "open_source"]
    elif loader_unverified:
        resolution_kind = "loader_unverified"
        resolution_title = f"需要先确认当前游戏已安装 {required_loader}"
        resolution_actions = ["keep", "verify_detail", "open_source"]
    elif verification_status == "blocked":
        resolution_kind = "verification_blocked"
        resolution_title = "详情核验受阻；完成站点验证或重新核验后可继续"
        resolution_actions = ["keep", "verify_detail", "open_source"]
    elif not detail_verified:
        resolution_kind = "needs_verification"
        resolution_title = "当前只有搜索证据；先核验详情再加入安装计划"
        resolution_actions = ["keep", "verify_detail", "open_source"]
    else:
        resolution_kind = "source_unresolved"
        resolution_title = "缺少稳定来源身份；需要选择正确来源"
        resolution_actions = ["keep", "verify_detail", "open_source"]
    return {
        "selection_key": _key(source, item),
        "source": source,
        "source_label": SOURCE_LABELS.get(source, source),
        "source_id": str(source_id),
        "mod_id": item.get("mod_id"),
        "file_id": (
            selected_variant.get("file_id") if selected_variant
            else item.get("file_id")
        ),
        "variants": variants,
        "selected_variant_id": (
            selected_variant.get("variant_id") if selected_variant else ""
        ),
        "variant_selection_required": len(variants) > 1,
        "name": _text(item.get("name") or item.get("full_name"), "未命名 Mod")[:120],
        "localized_name": _text(item.get("localized_name"))[:80],
        "content": _text(content, MISSING_CONTENT_TEXT)[:280],
        "has_function_summary": has_function_summary,
        "recommendation_reason": _recommendation_reason(
            item, updated, detail_verified, has_function_summary
        ),
        "updated_at": _format_updated(updated),
        "freshness": _freshness(updated),
        "version": _text(version, "待详情核验")[:48],
        "conflict": conflict,
        "conflict_status": conflict_status,
        "dependencies": dependencies,
        "required_loader": required_loader,
        "active_loader": active_loader,
        "loader_compatible": (
            False if loader_mismatch else None if loader_unverified else True
        ),
        "dependency_status": (
            "known" if dependencies else "none_verified" if detail_verified else "unknown"
        ),
        "detail_verified": detail_verified,
        "verification_status": (
            "verified" if detail_verified
            else verification_status or "pending"
        ),
        "verification_error": verification_error,
        "verification_source": _text(item.get("verification_source"))[:80],
        "endorsements": item.get("endorsements") or item.get("endorsement_count") or 0,
        "downloads": item.get("downloads") or item.get("mod_downloads") or 0,
        "url": _text(item.get("url"))[:500],
        "installable": installable,
        "resolution_kind": resolution_kind,
        "resolution_title": resolution_title,
        "resolution_actions": resolution_actions,
        "is_prerequisite": False,
        "required_by": [],
        "default_selected": False,
    }


def _dependency_requirements(
    items: list[dict], installed_mods: list[Any] | None = None,
) -> list[dict]:
    """Resolve declared dependency labels against visible candidates.

    Requirements remain visible even when no candidate can be matched. This
    keeps a missing prerequisite at the top of the decision table instead of
    burying it inside a target Mod's risk cell.
    """
    requirements: dict[str, dict] = {}
    for target in items:
        for dependency in target.get("dependencies") or []:
            label = _text(dependency)
            key = _dependency_identity(label)
            if not key:
                continue
            entry = requirements.setdefault(key, {
                "name": label,
                "required_by": [],
                "matched_selection_key": "",
                "status": "unresolved",
                "_version": _dependency_version(label),
                "_requested_versions": [],
            })
            requested_version = _dependency_version(label)
            if requested_version and requested_version not in entry["_requested_versions"]:
                entry["_requested_versions"].append(requested_version)
            if requested_version > entry["_version"]:
                entry["name"] = label
                entry["_version"] = requested_version
            target_name = _text(
                target.get("localized_name") or target.get("name"), "未命名 Mod"
            )
            if target_name not in entry["required_by"]:
                entry["required_by"].append(target_name)
            loader = _loader_name(label)
            if (
                loader in {"BepInEx", "MelonLoader", "SMAPI"}
                and target.get("loader_compatible") is True
                and _loader_name(target.get("active_loader")) == loader
            ):
                entry["status"] = "satisfied_local"

    installed_aliases = []
    for installed in installed_mods or []:
        installed_version = _dependency_version(
            getattr(installed, "version", "")
        )
        for alias in (
            getattr(installed, "id", ""),
            getattr(installed, "name", ""),
        ):
            identity = _dependency_identity(alias)
            if identity:
                installed_aliases.append((identity, installed_version))
    for key, entry in requirements.items():
        if entry["status"] != "unresolved":
            continue
        installed_match = next(
            (
                (alias, version)
                for alias, version in installed_aliases
                if _dependency_identity_matches(key, alias)
            ),
            None,
        )
        if installed_match:
            installed_version = installed_match[1]
            required_version = entry["_version"]
            if required_version and installed_version and installed_version < required_version:
                entry["status"] = "needs_resolution"
                entry["installed_version"] = ".".join(map(str, installed_version))
            else:
                entry["status"] = "satisfied_installed"

    for item in items:
        aliases = {
            _dependency_identity(item.get("name")),
            _dependency_identity(item.get("localized_name")),
            _dependency_identity(item.get("source_id")),
            _dependency_identity(item.get("mod_id")),
        }
        aliases.discard("")
        match = next(
            (
                entry for key, entry in requirements.items()
                if any(
                    _dependency_identity_matches(key, alias)
                    for alias in aliases
                )
            ),
            None,
        )
        if not match:
            continue
        if match["status"] in {"satisfied_installed", "satisfied_local"}:
            continue
        match["matched_selection_key"] = item["selection_key"]
        match["status"] = (
            "ready" if item.get("installable")
            else "needs_resolution"
        )
        item["is_prerequisite"] = True
        item["required_by"] = list(match["required_by"])

    public_requirements = []
    for entry in requirements.values():
        requested_versions = sorted(entry.pop("_requested_versions"), reverse=True)
        entry.pop("_version", None)
        if len(requested_versions) > 1:
            entry["requested_versions"] = [
                ".".join(map(str, version)) for version in requested_versions
            ]
            entry["version_conflict"] = True
        public_requirements.append(entry)

    return sorted(
        public_requirements,
        key=lambda entry: (
            0 if entry["matched_selection_key"] else 1,
            entry["name"].casefold(),
        ),
    )


def _decode_payload(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}
    return value


def _rows(value: Any, *keys: str) -> list[dict]:
    value = _decode_payload(value)
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if not isinstance(value, dict):
        return []
    for key in keys:
        rows = value.get(key)
        if isinstance(rows, list):
            return [item for item in rows if isinstance(item, dict)]
    return []


def _dedupe(source: str, items: list[dict]) -> list[dict]:
    result = []
    seen = set()
    for item in items:
        identity = (
            item.get("mod_id") or item.get("id") or item.get("full_name")
            or item.get("url") or item.get("name")
        )
        key = (source, str(identity or "").strip().casefold())
        if not key[1] or key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def _identity(item: dict) -> str:
    value = (
        item.get("mod_id") or item.get("id") or item.get("full_name")
        or item.get("url") or item.get("name")
    )
    return str(value or "").strip().casefold()


def _target_identity(value: Any) -> str:
    text = _text(value).casefold()
    text = re.sub(r"\bv?\d+(?:\.\d+){1,4}\b", " ", text)
    text = re.sub(r"\b(?:mod|模组)\b", " ", text)
    return re.sub(r"[^a-z0-9\u3400-\u9fff]+", "", text)


def _version_identity(value: Any) -> tuple[int, ...]:
    match = re.search(r"\bv?(\d+(?:\.\d+){1,4})\b", _text(value), flags=re.I)
    if not match:
        return ()
    return tuple(int(part) for part in match.group(1).split("."))


def _exact_target_matches(item: dict, target_name: str, target_version: str = "") -> bool:
    wanted = _target_identity(target_name)
    if not wanted:
        return False
    identities = {
        _target_identity(item.get("name")),
        _target_identity(item.get("full_name")),
    }
    identities.discard("")
    name_match = any(
        identity == wanted
        or (
            len(wanted) >= 4
            and (identity.endswith(wanted) or wanted.endswith(identity))
        )
        for identity in identities
    )
    if not name_match:
        return False
    wanted_version = _version_identity(target_version)
    candidate_version = _version_identity(
        item.get("version") or item.get("latest_version")
    )
    return not wanted_version or not candidate_version or wanted_version == candidate_version


def has_exact_target_candidate(
    tool_name: str, raw: Any, target_name: str, target_version: str = "",
) -> bool:
    """Return whether one search payload contains the user's explicit target."""
    source = SEARCH_TOOL_SOURCES.get(tool_name)
    if not source and tool_name != "mod_recommend":
        return False
    payload = _decode_payload(raw)
    if tool_name == "mod_recommend" and isinstance(payload, dict):
        rows = []
        rows.extend(_rows(payload, "recommendations", "nexus"))
        for key in ("workshop", "thunderstore", "gamebanana", "github"):
            rows.extend(_rows(payload, key))
    else:
        rows = _rows(payload, "results", source, "recommendations", "items")
    return any(
        _exact_target_matches(item, target_name, target_version)
        for item in rows
        if isinstance(item, dict)
    )


def _merge_evidence(broad: list[dict], verified: list[dict]) -> list[dict]:
    """Preserve search metadata while letting verified detail override it."""
    broad_by_key = {}
    for item in broad:
        key = _identity(item)
        if not key or key in broad_by_key:
            continue
        broad_by_key[key] = dict(item)

    result = []
    verified_keys = set()
    for item in verified:
        key = _identity(item)
        if not key or key in verified_keys:
            continue
        verified_keys.add(key)
        detail = {
            field: value for field, value in item.items()
            if value not in (None, "", [], {})
        }
        detail["_detail_verified"] = True
        merged = dict(broad_by_key.get(key) or {})
        merged.update(detail)
        result.append(merged)
    for key, item in broad_by_key.items():
        if key not in verified_keys:
            result.append(item)
    return result


def recommendations_from_tool_evidence(
    evidence: list[tuple[str, Any]], limit: int = 10, game_slug: str = "",
    mod_loader: str = "", target_name: str = "", target_version: str = "",
) -> dict:
    """Build the final Pro table from all search evidence in this turn."""
    broad = {source: [] for source in SOURCE_LABELS}
    verified = {source: [] for source in SOURCE_LABELS}
    saw_search = False

    for tool_name, raw in evidence:
        payload = _decode_payload(raw)
        if tool_name == "mod_recommend":
            saw_search = True
            if isinstance(payload, dict):
                broad["nexus"].extend(_rows(payload, "recommendations", "nexus"))
                for source in ("workshop", "thunderstore", "gamebanana", "github"):
                    broad[source].extend(_rows(payload, source))
            continue
        if tool_name in SEARCH_TOOL_SOURCES:
            saw_search = True
            source = SEARCH_TOOL_SOURCES[tool_name]
            broad[source].extend(
                _rows(payload, "results", source, "recommendations", "items")
            )
            continue
        if tool_name == "nexus_get_detail" and isinstance(payload, dict):
            if payload.get("mod_id") or payload.get("id"):
                verified["nexus"].append(payload)

    if not saw_search:
        return {"kind": "recommendation_set", "items": [], "selected_keys": []}

    combined = {
        source: _merge_evidence(
            _dedupe(source, broad[source]),
            _dedupe(source, verified[source]),
        )
        for source in SOURCE_LABELS
    }
    if target_name:
        combined = {
            source: [
                item for item in rows
                if _exact_target_matches(item, target_name, target_version)
            ]
            for source, rows in combined.items()
        }
        # Explicit installation resolves one named target. Keep at most a few
        # genuine same-name/source identities for user disambiguation.
        limit = min(int(limit or 3), 3)
    return normalize_recommendations({
        "recommendations": combined["nexus"],
        "workshop": combined["workshop"],
        "thunderstore": combined["thunderstore"],
        "gamebanana": combined["gamebanana"],
        "github": combined["github"],
    }, limit=limit, game_slug=game_slug, mod_loader=mod_loader)


def normalize_recommendations(
    payload: Any, limit: int = 10, game_slug: str = "", mod_loader: str = "",
) -> dict:
    """Return a stable six-row payload for the Pro recommendation table."""
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except (TypeError, ValueError, json.JSONDecodeError):
            payload = {}
    if not isinstance(payload, dict):
        payload = {}

    groups = {
        "nexus": payload.get("recommendations") or [],
        "workshop": payload.get("workshop") or [],
        "thunderstore": payload.get("thunderstore") or [],
        "gamebanana": payload.get("gamebanana") or [],
        "github": payload.get("github") or [],
    }
    source_counts = {
        source: len(rows) for source, rows in groups.items() if isinstance(rows, list)
    }
    try:
        installed_mods = db.get_installed_mods(game_slug) if game_slug else []
    except Exception:
        installed_mods = []
    installed_skipped = []
    normalized_groups = {}
    for source, rows in groups.items():
        normalized_groups[source] = []
        for raw in rows:
            if not isinstance(raw, dict):
                continue
            item = _normalize_item(source, raw, mod_loader=mod_loader)
            installed = find_installed_duplicate(
                game_slug,
                source,
                item.get("source_id") or "",
                target_name=item.get("name") or "",
                installed_mods=installed_mods,
            ) if game_slug else None
            if installed:
                installed_skipped.append({
                    "selection_key": item["selection_key"],
                    "source": source,
                    "source_id": item.get("source_id") or "",
                    "name": item.get("name") or "",
                    "installed_id": installed.id,
                    "installed_name": installed.name,
                    "installed_version": installed.version,
                })
                continue
            alternative = find_installed_functional_equivalent(
                item.get("name") or "", installed_mods,
            ) if game_slug else None
            if alternative:
                item.update({
                    "installable": False,
                    "default_selected": False,
                    "installed_match_kind": "functional_alternative",
                    "installed_id": alternative.id,
                    "installed_name": alternative.name,
                    "installed_version": alternative.version,
                    "conflict_status": "warning",
                    "conflict": (
                        f"已安装同类实现 {alternative.name} "
                        f"{alternative.version}；这是替代方案，不是版本更新，不建议同时安装"
                    ),
                    "resolution_kind": "alternative_installed",
                    "resolution_title": (
                        f"已安装功能重叠的 {alternative.name}。若要改用此候选，"
                        "请先核验差异并禁用或卸载现有实现"
                    ),
                    "resolution_actions": ["keep", "open_source"],
                })
            normalized_groups[source].append(item)

    # Round-robin sources so Nexus' first five rows cannot hide every other
    # source in a six-row table.
    normalized_limit = max(2, min(int(limit or 10), 20))
    items = []
    index = 0
    source_order = tuple(groups)
    while len(items) < normalized_limit:
        added = False
        for source in source_order:
            rows = normalized_groups[source]
            if index < len(rows):
                items.append(rows[index])
                added = True
                if len(items) >= normalized_limit:
                    break
        if not added:
            break
        index += 1

    dependency_requirements = _dependency_requirements(items, installed_mods)
    # Prerequisites are always rendered before target candidates.
    items.sort(key=lambda item: 0 if item.get("is_prerequisite") else 1)

    selected = 0
    for item in items:
        if (
            not item.get("is_prerequisite")
            and item["installable"]
            and item["has_function_summary"]
            and selected < 4
        ):
            item["default_selected"] = True
            selected += 1
    selected_target_names = {
        _text(item.get("localized_name") or item.get("name"))
        for item in items if item.get("default_selected")
    }
    for item in items:
        if (
            item.get("is_prerequisite")
            and item.get("installable")
            and selected_target_names.intersection(item.get("required_by") or [])
        ):
            item["default_selected"] = True

    return {
        "kind": "recommendation_set",
        "items": items,
        "selected_keys": [
            item["selection_key"] for item in items if item["default_selected"]
        ],
        "wanted_keys": [],
        "selected_variants": {
            item["selection_key"]: item.get("selected_variant_id")
            for item in items if item.get("selected_variant_id")
        },
        "dependency_requirements": dependency_requirements,
        "sources_failed": payload.get("sources_failed") or {},
        "note": _text(payload.get("note")),
        "installed_skipped": installed_skipped,
        "installed_skipped_count": len(installed_skipped),
        "source_counts": source_counts,
        "verification": {
            "target_ratio": 0.95,
            "total": len(items),
            "verified": sum(1 for item in items if item["detail_verified"]),
            "coverage_ratio": round(
                sum(1 for item in items if item["detail_verified"]) / len(items),
                4,
            ) if items else 1.0,
        },
    }


def promote_verified_recommendation(
    payload: Any,
    source: str,
    verified_detail: Any,
    *,
    mod_loader: str = "",
    game_slug: str = "",
) -> dict:
    """Upgrade one unresolved row in-place after authoritative detail lookup.

    The stable selection key and table position are preserved.  A prior
    "wanted" choice becomes selected only when the verified row is actually
    installable; blocked rows remain wanted and expose the verified reason.
    """
    payload = _decode_payload(payload)
    verified_detail = _decode_payload(verified_detail)
    if (
        not isinstance(payload, dict)
        or payload.get("kind") != "recommendation_set"
        or not isinstance(verified_detail, dict)
    ):
        return {}

    detail_identity = _identity(verified_detail)
    if not detail_identity:
        return {}
    items = [
        dict(item) for item in (payload.get("items") or [])
        if isinstance(item, dict)
    ]
    matched_index = next((
        index for index, item in enumerate(items)
        if _text(item.get("source")).casefold() == _text(source).casefold()
        and (
            _text(item.get("mod_id")).casefold() == detail_identity
            or _text(item.get("source_id")).casefold() == detail_identity
        )
    ), -1)
    if matched_index < 0:
        return {}

    previous = items[matched_index]
    merged = dict(previous)
    for key, value in verified_detail.items():
        if value not in (None, "", [], {}):
            merged[key] = value
    merged["_detail_verified"] = True
    promoted = _normalize_item(source, merged, mod_loader=mod_loader)
    promoted["selection_key"] = previous["selection_key"]
    if _text(previous.get("localized_name")):
        promoted["localized_name"] = previous["localized_name"]
    if (
        _CHINESE_RE.search(_text(previous.get("content")))
        and not _CHINESE_RE.search(_text(promoted.get("content")))
    ):
        promoted["content"] = previous["content"]
    items[matched_index] = promoted

    for item in items:
        item["is_prerequisite"] = False
        item["required_by"] = []
    try:
        installed_mods = db.get_installed_mods(game_slug) if game_slug else []
    except Exception:
        installed_mods = []
    dependency_requirements = _dependency_requirements(items, installed_mods)
    items.sort(key=lambda item: 0 if item.get("is_prerequisite") else 1)

    selected_keys = [
        str(key) for key in (payload.get("selected_keys") or []) if key
    ]
    wanted_keys = [
        str(key) for key in (payload.get("wanted_keys") or []) if key
    ]
    promoted_key = promoted["selection_key"]
    if promoted.get("installable") and promoted_key in wanted_keys:
        wanted_keys = [key for key in wanted_keys if key != promoted_key]
        if promoted_key not in selected_keys:
            selected_keys.append(promoted_key)
    elif not promoted.get("installable"):
        selected_keys = [key for key in selected_keys if key != promoted_key]
        if promoted_key not in wanted_keys:
            wanted_keys.append(promoted_key)

    valid_keys = {item.get("selection_key") for item in items}
    previous_variants = payload.get("selected_variants") or {}
    selected_variants = {}
    for item in items:
        key = item.get("selection_key")
        variants = item.get("variants") or []
        valid_variant_ids = {
            _text(variant.get("variant_id"))
            for variant in variants if isinstance(variant, dict)
        }
        preferred = _text(previous_variants.get(key))
        if preferred not in valid_variant_ids:
            preferred = _text(item.get("selected_variant_id"))
        if preferred in valid_variant_ids:
            selected_variants[key] = preferred
    result = {
        **payload,
        "items": items,
        "selected_keys": [key for key in selected_keys if key in valid_keys],
        "wanted_keys": [key for key in wanted_keys if key in valid_keys],
        "selected_variants": selected_variants,
        "dependency_requirements": dependency_requirements,
    }
    result["verification"] = {
        **(payload.get("verification") or {}),
        "target_ratio": 0.95,
        "total": len(items),
        "verified": sum(1 for item in items if item.get("detail_verified")),
        "coverage_ratio": round(
            sum(1 for item in items if item.get("detail_verified")) / len(items),
            4,
        ) if items else 1.0,
    }
    result["promotion"] = {
        "selection_key": promoted_key,
        "installable": bool(promoted.get("installable")),
        "resolution_kind": promoted.get("resolution_kind"),
    }
    return result


def merge_recommendation_resolution(
    payload: Any,
    resolved_payload: Any,
    *,
    target_selection_key: str = "",
    game_slug: str = "",
) -> dict:
    """Merge one wanted target's verification round back into its table.

    The dependency graph is plan-scoped: dependencies selected for one wanted
    target may satisfy the same prerequisite for other candidates, but those
    other candidates are never selected automatically.
    """
    payload = _decode_payload(payload)
    resolved_payload = _decode_payload(resolved_payload)
    if (
        not isinstance(payload, dict)
        or payload.get("kind") != "recommendation_set"
        or not isinstance(resolved_payload, dict)
    ):
        return {}

    items = [
        dict(item) for item in (payload.get("items") or [])
        if isinstance(item, dict)
    ]
    incoming = [
        dict(item) for item in (resolved_payload.get("items") or [])
        if isinstance(item, dict)
    ]
    if not items:
        return resolved_payload

    selected_keys = {
        str(key) for key in (payload.get("selected_keys") or []) if key
    }
    wanted_keys = {
        str(key) for key in (payload.get("wanted_keys") or []) if key
    }
    if target_selection_key:
        wanted_keys.add(str(target_selection_key))

    target = next((
        item for item in items
        if item.get("selection_key") == target_selection_key
    ), None)
    target_dependency_keys = {
        _dependency_identity(dependency)
        for dependency in ((target or {}).get("dependencies") or [])
        if _dependency_identity(dependency)
    }

    def same_candidate(left: dict, right: dict) -> bool:
        if (
            left.get("selection_key")
            and left.get("selection_key") == right.get("selection_key")
        ):
            return True
        if _text(left.get("source")).casefold() != _text(right.get("source")).casefold():
            return False
        left_ids = {
            _text(left.get("source_id")).casefold(),
            _text(left.get("mod_id")).casefold(),
        }
        right_ids = {
            _text(right.get("source_id")).casefold(),
            _text(right.get("mod_id")).casefold(),
        }
        left_ids.discard("")
        right_ids.discard("")
        return bool(left_ids.intersection(right_ids))

    for resolved in incoming:
        match_index = next((
            index for index, item in enumerate(items)
            if same_candidate(item, resolved)
        ), -1)
        if match_index >= 0:
            previous = items[match_index]
            stable_key = previous.get("selection_key")
            localized_name = previous.get("localized_name")
            merged = {**previous, **resolved}
            merged["selection_key"] = stable_key
            if localized_name and not merged.get("localized_name"):
                merged["localized_name"] = localized_name
            items[match_index] = merged
            continue

        aliases = {
            _dependency_identity(resolved.get("name")),
            _dependency_identity(resolved.get("localized_name")),
            _dependency_identity(resolved.get("source_id")),
            _dependency_identity(resolved.get("mod_id")),
        }
        aliases.discard("")
        if target_dependency_keys and any(
            _dependency_identity_matches(dependency, alias)
            for dependency in target_dependency_keys
            for alias in aliases
        ):
            items.append(resolved)

    for item in items:
        item["is_prerequisite"] = False
        item["required_by"] = []
    try:
        installed_mods = db.get_installed_mods(game_slug) if game_slug else []
    except Exception:
        installed_mods = []
    requirements = _dependency_requirements(items, installed_mods)

    active_target_names = {
        _text(item.get("localized_name") or item.get("name"))
        for item in items
        if (
            not item.get("is_prerequisite")
            and (
                item.get("selection_key") in selected_keys
                or item.get("selection_key") in wanted_keys
            )
        )
    }
    planned_keys = set()
    for requirement in requirements:
        if not active_target_names.intersection(requirement.get("required_by") or []):
            continue
        dependency_key = requirement.get("matched_selection_key")
        if requirement.get("status") == "ready" and dependency_key:
            selected_keys.add(dependency_key)
            planned_keys.add(dependency_key)
            requirement["status"] = "planned"

    planned_loaders = {
        loader
        for requirement in requirements
        if requirement.get("status") in {
            "planned", "satisfied_installed", "satisfied_local"
        }
        for loader in [_loader_name(requirement.get("name"))]
        if loader
    }
    for item in items:
        required_loader = _loader_name(item.get("required_loader"))
        if (
            item.get("resolution_kind") == "loader_unverified"
            and item.get("detail_verified")
            and required_loader in planned_loaders
            and not _loader_name(item.get("active_loader"))
            and item.get("source_id")
        ):
            item.update({
                "installable": True,
                "loader_compatible": True,
                "dependency_plan_satisfied": True,
                "conflict_status": "clear",
                "conflict": (
                    f"本轮拟安装计划已包含 {required_loader}；"
                    "最终执行前仍会核验版本与安装落点"
                ),
                "resolution_kind": "ready_after_dependencies",
                "resolution_title": "共享前置依赖已加入本轮计划，可以选择",
                "resolution_actions": [],
            })

    target_item = next((
        item for item in items
        if item.get("selection_key") == target_selection_key
    ), None)
    if target_item and target_item.get("installable"):
        wanted_keys.discard(target_selection_key)
        selected_keys.add(target_selection_key)

    items.sort(key=lambda item: 0 if item.get("is_prerequisite") else 1)
    valid_keys = {item.get("selection_key") for item in items}
    previous_variants = payload.get("selected_variants") or {}
    incoming_variants = resolved_payload.get("selected_variants") or {}
    selected_variants = {}
    for item in items:
        key = item.get("selection_key")
        variants = item.get("variants") or []
        valid_variant_ids = {
            _text(variant.get("variant_id"))
            for variant in variants if isinstance(variant, dict)
        }
        preferred = _text(
            incoming_variants.get(key) or previous_variants.get(key)
        )
        if preferred not in valid_variant_ids:
            preferred = _text(item.get("selected_variant_id"))
        if preferred in valid_variant_ids:
            selected_variants[key] = preferred
    result = {
        **payload,
        "items": items,
        "selected_keys": [
            key for key in selected_keys if key in valid_keys
        ],
        "wanted_keys": [
            key for key in wanted_keys if key in valid_keys
        ],
        "selected_variants": selected_variants,
        "dependency_requirements": requirements,
        "planned_dependency_keys": sorted(planned_keys),
        "resolution_refresh": {
            "target_selection_key": target_selection_key,
            "planned_dependencies": len(planned_keys),
            "shared_candidates_unlocked": sum(
                1 for item in items if item.get("dependency_plan_satisfied")
            ),
        },
    }
    result["verification"] = {
        **(payload.get("verification") or {}),
        "target_ratio": 0.95,
        "total": len(items),
        "verified": sum(1 for item in items if item.get("detail_verified")),
        "coverage_ratio": round(
            sum(1 for item in items if item.get("detail_verified")) / len(items),
            4,
        ) if items else 1.0,
    }
    return result
