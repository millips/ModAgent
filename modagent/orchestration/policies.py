from __future__ import annotations

from collections.abc import Iterable

from .models import AgentMode, TaskSpec


SEARCH_TOOLS = {
    "mod_recommend", "nexus_search", "workshop_search",
    "thunderstore_search", "github_search", "gamebanana_search",
}
DETAIL_TOOLS = {
    "nexus_get_detail", "read_readme", "game_file_check",
    "get_installed", "list_local_mods", "conflict_check",
    "stardew_smapi_status", "collection_view",
}
STATUS_TOOLS = {
    "get_installed", "list_local_mods", "game_file_check",
    "stardew_smapi_status", "snapshot_list", "collection_view",
}
DIAGNOSE_TOOLS = STATUS_TOOLS | {
    "game_diagnose", "read_readme", "conflict_check",
}
SOURCE_RESOLUTION_TOOLS = DETAIL_TOOLS | {
    "mod_source_align", "official_share_network_diagnostics",
}
PLAN_TOOLS = DETAIL_TOOLS | {
    "official_share_import", "share_import", "mod_update_check",
}
EXECUTION_TOOLS = PLAN_TOOLS | {
    "mod_download", "batch_download", "download_from_url",
    "mod_install", "mod_install_batch", "mod_install_custom",
    "workshop_install", "tool_extract", "game_config_write",
    "snapshot_create",
}
UPDATE_TOOLS = STATUS_TOOLS | {"mod_update_check", "mod_source_align"}
SNAPSHOT_TOOLS = STATUS_TOOLS | {
    "snapshot_create", "snapshot_restore", "snapshot_delete",
}
SHARE_TOOLS = DETAIL_TOOLS | {
    "share_import", "official_share_catalog", "official_share_import",
    "official_share_network_diagnostics",
}

MUTATING_TOOLS = {
    "import_existing_mods", "mod_download", "batch_download",
    "download_from_url", "mod_install", "mod_install_batch",
    "mod_install_custom", "mod_uninstall", "mod_update", "mod_disable",
    "mod_enable", "mod_dependency_set", "mod_source_bind", "mod_patch",
    "game_config_write", "snapshot_create", "snapshot_restore",
    "snapshot_delete", "workshop_install", "workshop_uninstall", "tool_extract",
}
DESTRUCTIVE_TOOLS = {
    "mod_uninstall", "mod_disable", "snapshot_restore", "snapshot_delete",
    "workshop_uninstall",
}


def allowed_tools(spec: TaskSpec) -> set[str]:
    mode = spec.intent
    if mode == AgentMode.CHAT_EXPLAIN:
        allowed = set()
    elif mode == AgentMode.STATUS_CHECK:
        allowed = set(STATUS_TOOLS)
    elif mode == AgentMode.SEARCH_EXACT:
        allowed = SEARCH_TOOLS | DETAIL_TOOLS
    elif mode == AgentMode.RECOMMEND_BROAD:
        allowed = SEARCH_TOOLS | DETAIL_TOOLS
    elif mode == AgentMode.RESOLVE_SOURCE:
        allowed = set(SOURCE_RESOLUTION_TOOLS)
    elif mode == AgentMode.BUILD_PLAN:
        allowed = set(PLAN_TOOLS)
    elif mode == AgentMode.EXECUTE_PLAN:
        allowed = set(EXECUTION_TOOLS)
    elif mode == AgentMode.UPDATE_INSTALLED:
        allowed = set(UPDATE_TOOLS)
        if spec.authorization.get("install"):
            allowed.add("mod_update")
    elif mode == AgentMode.DIAGNOSE:
        allowed = set(DIAGNOSE_TOOLS)
    elif mode == AgentMode.SNAPSHOT_ROLLBACK:
        allowed = set(SNAPSHOT_TOOLS)
    elif mode == AgentMode.IMPORT_SHARE:
        allowed = set(SHARE_TOOLS)
    else:
        allowed = set()

    if not spec.authorization.get("install"):
        allowed -= MUTATING_TOOLS - {"mod_source_align"}
    if not spec.authorization.get("destructive"):
        allowed -= DESTRUCTIVE_TOOLS
        # These tools implement their own mandatory preview/token gate.  Keep
        # them visible in the dedicated snapshot mode so the first read-only
        # impact preview can be produced; confirmed execution is still checked
        # by the tool and the legacy hard guard.
        if mode == AgentMode.SNAPSHOT_ROLLBACK:
            allowed |= {"snapshot_restore", "snapshot_delete"}
    return allowed


def tool_is_allowed(spec: TaskSpec, tool_name: str) -> bool:
    return str(tool_name or "") in allowed_tools(spec)


def filter_tool_definitions(definitions: Iterable[dict], spec: TaskSpec) -> list[dict]:
    permitted = allowed_tools(spec)
    return [
        item for item in definitions
        if str(item.get("function", {}).get("name") or "") in permitted
    ]
