"""
ModAgent 启动一致性检查 (P2.1)

作用:防止 prompt / schema 漂移。prompt 里若引用了模型根本收不到的工具,
就必然幻觉——与其运行时静默出错,不如启动时大声崩掉。

放置:modagent/startup_checks.py
调用:在 api.py 的 lifespan/startup 里 run_startup_checks(...)

⚠️ 关于 spec 2.1 的坑:
原 spec 用 re.findall(r'`([a-z_]+)`', prompt) 直接抓反引号里的 token 当工具名。
这会把 `mod_id` `file_id` `local_path` `snapshot_id` 这些【参数名】、
以及 `snap_20260627_192709` 这类【快照 ID 字面量】全都误判成"不存在的工具",
导致启动直接 raise、根本起不来。
下面用【显式清单】作为强校验(可靠),正则扫描仅作 warn 兜底(有误报也只告警)。
"""
from __future__ import annotations

import logging
import re

logger = logging.getLogger("modagent.startup")

# 参数名 / 字段名:它们会出现在反引号里,但不是工具,扫描时排除
_PARAM_DENYLIST = {
    "mod_id", "file_id", "local_path", "snapshot_id", "trigger_mod_name",
    "archive_path", "file_path", "new_content", "error_log", "file_hint",
    "instruction", "query", "description", "mods", "version", "name",
    "game_info", "installed_mods", "target", "load_order",
    "requires_confirmation", "missing_dependencies",
}

# 快照 ID 字面量 / 模板,如 snap_20260627_192709、snap_xxx
_SNAP_LITERAL = re.compile(r"^snap_\w+$")

# "工具形状":snake_case 且至少一个下划线段,如 nexus_get_detail
_TOOL_SHAPED = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)+$")


def assert_no_duplicate_tools(schema: list[dict]) -> None:
    """schema 里同名工具重复定义会让部分 API 行为不可控。"""
    names = [t["function"]["name"] for t in schema]
    dupes = sorted({n for n in names if names.count(n) > 1})
    if dupes:
        raise RuntimeError(f"[startup] schema 存在重复工具定义: {dupes}")


def assert_referenced_tools_exist(
    referenced_tools: set[str], schema: list[dict]
) -> None:
    """
    强校验(推荐):显式维护 prompt 里以散文形式提到的工具名清单。
    这个清单短、稳定、无误报,适合做硬崩溃。
    """
    schema_names = {t["function"]["name"] for t in schema}
    missing = sorted(referenced_tools - schema_names)
    if missing:
        raise RuntimeError(
            f"[startup] prompt 引用了 schema 中不存在的工具: {missing}。"
            f"请修正 prompt,或在 schema 中实现这些工具。"
        )


def scan_prompt_tool_refs(prompt_text: str) -> set[str]:
    """
    弱扫描(warn-only):从 prompt 反引号里尽力抓"工具形状"的 token,
    排除参数名与快照字面量。可能仍有误报,所以只用来告警,不用来崩溃。
    """
    refs: set[str] = set()
    for raw in re.findall(r"`([^`]+)`", prompt_text):
        tok = raw.strip()
        if not _TOOL_SHAPED.match(tok):        # 含 / \ . 或非 snake_case 的直接跳过
            continue
        if tok in _PARAM_DENYLIST:
            continue
        if _SNAP_LITERAL.match(tok):
            continue
        refs.add(tok)
    return refs


def run_startup_checks(
    prompt_text: str,
    schema: list[dict],
    referenced_tools: set[str] | None = None,
) -> None:
    """
    在 api.py 启动时调用。
    - referenced_tools:强烈建议传入显式清单(见 api.py 集成示例)。
      传了就做硬校验;没传就退化为弱扫描 + 告警。
    """
    assert_no_duplicate_tools(schema)

    if referenced_tools is not None:
        assert_referenced_tools_exist(referenced_tools, schema)

    # 无论是否传显式清单,都跑一次弱扫描做兜底告警
    schema_names = {t["function"]["name"] for t in schema}
    scanned_missing = sorted(scan_prompt_tool_refs(prompt_text) - schema_names)
    if scanned_missing:
        logger.warning(
            "[startup] 弱扫描发现 prompt 中疑似引用了不存在的工具(可能误报,"
            "确认后请补进 referenced_tools 或修正 prompt): %s",
            scanned_missing,
        )
    logger.info("[startup] 工具一致性检查通过 (%d 个工具)", len(schema_names))


if __name__ == "__main__":
    # 冒烟自测:python -m modagent.startup_checks
    fake_schema = [
        {"function": {"name": "nexus_get_detail"}},
        {"function": {"name": "mod_install"}},
    ]
    good_prompt = "用 `nexus_get_detail` 拿详情,传入 `mod_id`,快照 `snap_20260627_192709`。"
    run_startup_checks(good_prompt, fake_schema, referenced_tools={"nexus_get_detail", "mod_install"})
    print("OK: 正常 prompt 通过,且未把 mod_id / snap_ 字面量误判为工具")

    try:
        assert_referenced_tools_exist({"collection_view"}, fake_schema)
    except RuntimeError as e:
        print("OK: 幽灵工具被拦截 ->", e)

    try:
        assert_no_duplicate_tools(fake_schema + [{"function": {"name": "mod_install"}}])
    except RuntimeError as e:
        print("OK: 重复工具被拦截 ->", e)
