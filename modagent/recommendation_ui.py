"""Normalize multi-source recommendations for the subscription chat UI."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any

from . import db
from .inventory_match import find_installed_duplicate


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
    """Keep a compact model analysis while removing its duplicate table."""
    text = _text(value)
    result: list[str] = []
    previous_blank = False
    for line in text.splitlines():
        stripped = line.strip()
        if (
            (stripped.startswith("|") and stripped.endswith("|"))
            or _MARKDOWN_TABLE_SEPARATOR_RE.fullmatch(stripped)
            or stripped in {"---", "***", "___"}
        ):
            continue
        if not stripped:
            if result and not previous_blank:
                result.append("")
            previous_blank = True
            continue
        result.append(line)
        previous_blank = False

    cleaned = "\n".join(result).strip()
    # The structured card already carries versions, activity and source metadata.
    # Keep only a small decision-oriented preface in chat.
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", cleaned) if part.strip()]
    cleaned = "\n\n".join(paragraphs[:6])
    if len(cleaned) > 1200:
        cleaned = cleaned[:1197].rstrip("，。；:： ") + "…"
    if len(cleaned) < 20:
        cleaned = RECOMMENDATION_FALLBACK_TEXT
    coverage = _source_coverage_text(payload)
    return (
        f"{cleaned}"
        + (f"\n\n{coverage}" if coverage and coverage not in cleaned else "")
        + "\n\n"
        "请在下方清单中调整选择；优先候选已默认勾选，也可以取消、增添或全选。"
    )


def needs_chinese_localization(value: Any) -> bool:
    """True only when an existing description still contains no Chinese."""
    text = _text(value)
    # Missing evidence must stay visibly missing. Asking the model to infer a
    # function from the title turns uncertainty into a fabricated description.
    if not text or text == MISSING_CONTENT_TEXT:
        return False
    return not _CHINESE_RE.search(text)


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
    if isinstance(translations, list):
        for row in translations:
            if not isinstance(row, dict):
                continue
            key = _text(row.get("selection_key") or row.get("key"))
            content = _text(row.get("content") or row.get("description"))
            if key and content and _CHINESE_RE.search(content):
                localized[key] = content[:280]

    for item in payload.get("items") or []:
        if not isinstance(item, dict) or not needs_chinese_localization(item.get("content")):
            continue
        key = _text(item.get("selection_key"))
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


def _normalize_item(source: str, item: dict) -> dict:
    dependencies = _dependencies(
        item.get("dependencies") or item.get("requirements") or item.get("deps")
    )
    archived = bool(item.get("archived"))
    has_files = item.get("has_files")
    detail_verified = bool(item.get("_detail_verified"))
    content = item.get("summary") or item.get("description")
    has_function_summary = bool(_text(content))
    staleness = item.get("staleness") if isinstance(item.get("staleness"), dict) else {}
    if archived:
        conflict_status = "danger"
        conflict = "项目已归档"
    elif has_files is False:
        conflict_status = "warning"
        conflict = "未提供下载文件"
    elif staleness.get("stale"):
        conflict_status = "warning"
        conflict = staleness.get("note") or "较长时间未更新，需核对兼容性"
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
    installable = not archived and has_files is not False and bool(source_id)
    return {
        "selection_key": _key(source, item),
        "source": source,
        "source_label": SOURCE_LABELS.get(source, source),
        "source_id": str(source_id),
        "mod_id": item.get("mod_id"),
        "name": _text(item.get("name") or item.get("full_name"), "未命名 Mod")[:120],
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
        "dependency_status": (
            "known" if dependencies else "none_verified" if detail_verified else "unknown"
        ),
        "detail_verified": detail_verified,
        "endorsements": item.get("endorsements") or item.get("endorsement_count") or 0,
        "downloads": item.get("downloads") or item.get("mod_downloads") or 0,
        "url": _text(item.get("url"))[:500],
        "installable": installable,
        "default_selected": False,
    }


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
    return normalize_recommendations({
        "recommendations": combined["nexus"],
        "workshop": combined["workshop"],
        "thunderstore": combined["thunderstore"],
        "gamebanana": combined["gamebanana"],
        "github": combined["github"],
    }, limit=limit, game_slug=game_slug)


def normalize_recommendations(
    payload: Any, limit: int = 10, game_slug: str = "",
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
            item = _normalize_item(source, raw)
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

    selected = 0
    for item in items:
        if item["installable"] and item["has_function_summary"] and selected < 4:
            item["default_selected"] = True
            selected += 1

    return {
        "kind": "recommendation_set",
        "items": items,
        "selected_keys": [
            item["selection_key"] for item in items if item["default_selected"]
        ],
        "sources_failed": payload.get("sources_failed") or {},
        "note": _text(payload.get("note")),
        "installed_skipped": installed_skipped,
        "installed_skipped_count": len(installed_skipped),
        "source_counts": source_counts,
    }
