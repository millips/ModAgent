"""Normalize legacy tool receipts without treating a reply as proof of success.

This adapter does not verify files. Operation-specific verification belongs to
the execution layer; non-success receipts must never enter its success ledger.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from typing import Any


class OutcomeStatus(str, Enum):
    SUCCESS = "success"
    PARTIAL = "partial"
    WAITING_USER = "waiting_user"
    BLOCKED = "blocked"
    FAILED = "failed"
    CANCELLED = "cancelled"
    UNKNOWN = "unknown"


_WAITING = {
    "manual_action_required", "partial_manual_action_required",
    "preinstall_confirmation_required", "compatibility_confirmation_required",
    "variant_selection_required", "confirmation_required", "waiting_confirmation",
}
_BLOCKED = {
    "dependency_blocked", "detail_verification_required", "missing_dependencies",
    "incompatible_loader", "nexus_game_id_missing", "nexus_api_key_missing",
    "exact_batch_required", "blocked",
}
_FAILED = {
    "failed", "invalid_request", "download_failed_terminal",
    "download_retry_exhausted", "download_incomplete", "error",
}


@dataclass(frozen=True)
class ToolOutcome:
    status: OutcomeStatus
    reason: str = ""
    retryable: bool = False

    @property
    def succeeded(self) -> bool:
        return self.status == OutcomeStatus.SUCCESS

    @classmethod
    def from_legacy(cls, result: str | dict[str, Any], *, legacy_ok: bool) -> "ToolOutcome":
        try:
            data = json.loads(result) if isinstance(result, str) else result
        except (TypeError, ValueError):
            data = None
        if isinstance(data, dict):
            status = str(data.get("status") or "").lower()
            reason = str(data.get("error") or data.get("message") or status)
            if status in {"cancelled", "canceled"}:
                return cls(OutcomeStatus.CANCELLED, reason)
            if status in {"unknown", "outcome_unknown", "interrupted"}:
                return cls(OutcomeStatus.UNKNOWN, reason)
            if status in _WAITING or data.get("requires_confirmation") is True:
                return cls(OutcomeStatus.WAITING_USER, reason)
            if status in _BLOCKED or data.get("install_blocked"):
                return cls(OutcomeStatus.BLOCKED, reason)
            failure_count = data.get("failed", 0)
            if (isinstance(failure_count, (int, float)) and failure_count > 0) or (
                status == "completed" and data.get("all_selected_installed") is False
            ):
                return cls(OutcomeStatus.PARTIAL, reason or "incomplete_batch", False)
            if status in {"partial", "partial_failure", "partially_completed"}:
                return cls(OutcomeStatus.PARTIAL, reason, bool(data.get("retryable", True)))
            if data.get("error") or status in _FAILED or data.get("ok") is False:
                return cls(OutcomeStatus.FAILED, reason or "tool_failed", bool(data.get("retryable", True)))
            # Aggregated searches have per-source receipts. A JSON response is
            # not a successful search when every source failed.
            if "sources_consulted" in data and "sources_failed" in data:
                consulted = data.get("sources_consulted") or []
                failed = data.get("sources_failed") or {}
                if failed:
                    return cls(OutcomeStatus.PARTIAL if consulted else OutcomeStatus.FAILED,
                               "some_search_sources_failed" if consulted else "all_search_sources_failed", True)
                if not consulted and (data.get("sources_skipped") or data.get("sources_attempted")):
                    return cls(OutcomeStatus.BLOCKED, "no_search_source_available")
            if not legacy_ok:
                return cls(OutcomeStatus.FAILED, reason or "tool_failed", bool(data.get("retryable", True)))
            if status and status not in {
                "success", "succeeded", "completed", "ok", "already_installed",
                "already_completed", "downloaded", "installed", "ready", "skipped",
            }:
                return cls(OutcomeStatus.UNKNOWN, reason or "unrecognized_tool_status")
            # Legacy read tools often return only {items: [...]}, with no status.
            return cls(OutcomeStatus.SUCCESS)
        if not legacy_ok:
            return cls(OutcomeStatus.FAILED, "tool_failed", True)
        if data is None and not str(result or "").strip():
            return cls(OutcomeStatus.UNKNOWN, "empty_tool_result")
        return cls(OutcomeStatus.SUCCESS)
