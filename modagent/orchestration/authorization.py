"""Server-owned plan revisions and one-shot execution grants."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from . import store
from .models import ExecutionGrant, PlanRevision


class ExecutionGrantRejected(ValueError):
    pass


def _text(value: Any) -> str:
    return str(value if value is not None else "")


def _normalize_target(allowed: dict[str, Any], submitted: dict[str, Any]) -> dict[str, Any]:
    key = _text(submitted.get("selection_key"))
    if not key or key != _text(allowed.get("selection_key")):
        raise ExecutionGrantRejected("selection_not_in_plan")
    if allowed.get("installable") is False:
        raise ExecutionGrantRejected("selection_not_installable")

    normalized = dict(allowed)
    variants = [dict(item) for item in (allowed.get("variants") or []) if isinstance(item, Mapping)]
    requested_variant = _text(
        submitted.get("selected_variant_id") or submitted.get("variant_id")
    )
    requested_file = _text(submitted.get("file_id"))
    if variants:
        chosen = next((item for item in variants if (
            requested_variant and _text(item.get("variant_id")) == requested_variant
        )), None)
        if chosen is None and requested_file:
            chosen = next((item for item in variants if _text(item.get("file_id")) == requested_file), None)
        if chosen is None:
            raise ExecutionGrantRejected("variant_not_in_plan")
        if requested_file and _text(chosen.get("file_id")) != requested_file:
            raise ExecutionGrantRejected("variant_file_mismatch")
        normalized.update({
            "selected_variant_id": chosen.get("variant_id"),
            "variant_id": chosen.get("variant_id"),
            "file_id": chosen.get("file_id"),
            "file_name": chosen.get("file_name"),
            "variant_name": chosen.get("name"),
            "target_slot": chosen.get("target_slot"),
            "version": chosen.get("version") or allowed.get("version"),
        })
    else:
        for field in ("source", "source_id", "canonical_tool_mod_id", "mod_id", "file_id"):
            expected = allowed.get(field)
            supplied = submitted.get(field)
            if expected not in (None, "") and _text(supplied) != _text(expected):
                raise ExecutionGrantRejected(f"selection_{field}_mismatch")
    return normalized


def normalize_execution_targets(
    revision: PlanRevision, submitted_targets: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    allowed = {
        _text(item.get("selection_key")): dict(item)
        for item in revision.targets if _text(item.get("selection_key"))
    }
    if not allowed or not submitted_targets:
        raise ExecutionGrantRejected("selection_missing")
    normalized = []
    seen = set()
    for submitted in submitted_targets:
        if not isinstance(submitted, dict):
            raise ExecutionGrantRejected("selection_invalid")
        key = _text(submitted.get("selection_key"))
        if key in seen:
            raise ExecutionGrantRejected("selection_duplicate")
        if key not in allowed:
            raise ExecutionGrantRejected("selection_not_in_plan")
        seen.add(key)
        normalized.append(_normalize_target(allowed[key], submitted))
    return normalized


def authorize_execution(
    *, plan_task_id: str, plan_revision_id: str, session_id: str,
    game_id: str, submitted_targets: list[dict[str, Any]],
) -> ExecutionGrant:
    revision = store.get_plan_revision(plan_task_id)
    if revision is None:
        raise ExecutionGrantRejected("plan_revision_missing")
    if revision.revision_id != str(plan_revision_id or ""):
        raise ExecutionGrantRejected("plan_revision_mismatch")
    if revision.session_id != str(session_id or ""):
        raise ExecutionGrantRejected("plan_session_mismatch")
    if revision.game_id != str(game_id or ""):
        raise ExecutionGrantRejected("plan_game_mismatch")
    targets = normalize_execution_targets(revision, submitted_targets)
    grant = ExecutionGrant.create(revision=revision, targets=targets)
    try:
        store.consume_execution_grant(grant)
    except ValueError as exc:
        raise ExecutionGrantRejected(str(exc)) from exc
    return grant
