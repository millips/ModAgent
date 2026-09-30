from __future__ import annotations

import json
import sqlite3
import time
from typing import Any

from modagent import db

from .models import ExecutionGrant, PlanRevision, TaskResult, TaskSpec, TaskState


def create_task(spec: TaskSpec, state: TaskState = TaskState.RECEIVED) -> None:
    now = time.time()
    conn = db.get_conn()
    try:
        conn.execute(
            """
            INSERT INTO agent_tasks
            (task_id, session_id, turn_id, game_id, intent, state, spec_json,
             checkpoint_json, outcome_json, cancel_reason, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, '{}', '{}', '', ?, ?)
            ON CONFLICT(task_id) DO UPDATE SET
                session_id=excluded.session_id,
                turn_id=excluded.turn_id,
                game_id=excluded.game_id,
                intent=excluded.intent,
                state=excluded.state,
                spec_json=excluded.spec_json,
                outcome_json='{}',
                cancel_reason='',
                updated_at=excluded.updated_at
            """,
            (
                spec.task_id, spec.session_id, spec.turn_id, spec.game_id,
                spec.intent.value, state.value,
                json.dumps(spec.to_dict(), ensure_ascii=False), now, now,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def save_checkpoint_step(
    task_id: str,
    step_key: str,
    value: dict[str, Any],
) -> None:
    """Merge one completed step without discarding earlier checkpoints."""
    conn = db.get_conn()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT checkpoint_json FROM agent_tasks WHERE task_id=?",
            (str(task_id),),
        ).fetchone()
        try:
            checkpoint = json.loads((row[0] if row else "") or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            checkpoint = {}
        steps = checkpoint.setdefault("steps", {})
        steps[str(step_key)] = dict(value or {})
        checkpoint["updated_at"] = time.time()
        conn.execute(
            "UPDATE agent_tasks SET checkpoint_json=?, updated_at=? WHERE task_id=?",
            (json.dumps(checkpoint, ensure_ascii=False), time.time(), str(task_id)),
        )
        conn.commit()
    finally:
        conn.close()


def get_checkpoint_step(task_id: str, step_key: str) -> dict[str, Any] | None:
    task = get_task(task_id)
    checkpoint = (task or {}).get("checkpoint") or {}
    value = (checkpoint.get("steps") or {}).get(str(step_key))
    return dict(value) if isinstance(value, dict) else None


def save_plan_revision(revision: PlanRevision) -> None:
    """Persist the immutable plan presented to the user."""
    conn = db.get_conn()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT checkpoint_json FROM agent_tasks WHERE task_id=?",
            (revision.task_id,),
        ).fetchone()
        if row is None:
            raise ValueError("plan_task_not_found")
        try:
            checkpoint = json.loads(row[0] or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            checkpoint = {}
        existing = checkpoint.get("plan_revision")
        if isinstance(existing, dict) and existing.get("revision_id") not in {
            None, "", revision.revision_id,
        }:
            raise ValueError("plan_revision_already_frozen")
        checkpoint["plan_revision"] = revision.to_dict()
        checkpoint["updated_at"] = time.time()
        conn.execute(
            "UPDATE agent_tasks SET checkpoint_json=?, updated_at=? WHERE task_id=?",
            (json.dumps(checkpoint, ensure_ascii=False), time.time(), revision.task_id),
        )
        conn.commit()
    finally:
        conn.close()


def get_plan_revision(task_id: str) -> PlanRevision | None:
    task = get_task(task_id)
    value = ((task or {}).get("checkpoint") or {}).get("plan_revision")
    if not isinstance(value, dict):
        return None
    try:
        return PlanRevision.from_dict(value)
    except (TypeError, ValueError):
        return None


def consume_execution_grant(grant: ExecutionGrant) -> None:
    """Atomically consume one plan revision; replaying it is rejected."""
    conn = db.get_conn()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT state, checkpoint_json FROM agent_tasks WHERE task_id=?",
            (grant.plan_task_id,),
        ).fetchone()
        if row is None:
            raise ValueError("plan_task_not_found")
        if str(row["state"]) != TaskState.WAITING_CONFIRMATION.value:
            raise ValueError("plan_not_waiting_confirmation")
        try:
            checkpoint = json.loads(row["checkpoint_json"] or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            checkpoint = {}
        revision = checkpoint.get("plan_revision") or {}
        if revision.get("revision_id") != grant.plan_revision_id:
            raise ValueError("plan_revision_mismatch")
        try:
            conn.execute(
                """
                INSERT INTO agent_execution_grants
                (grant_id, plan_task_id, plan_revision_id, session_id, game_id,
                 targets_json, status, created_at, consumed_at)
                VALUES (?, ?, ?, ?, ?, ?, 'consumed', ?, ?)
                """,
                (
                    grant.grant_id, grant.plan_task_id, grant.plan_revision_id,
                    grant.session_id, grant.game_id,
                    json.dumps(grant.to_dict()["targets"], ensure_ascii=False),
                    grant.created_at, grant.consumed_at,
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise ValueError("plan_revision_already_consumed") from exc
        conn.commit()
    finally:
        conn.close()


def cancel_task(task_id: str, reason: str) -> bool:
    """Persist a terminal cancellation and its user-visible event."""
    task = get_task(task_id)
    if task is None:
        return False
    try:
        state = TaskState(str(task.get("state") or TaskState.RECEIVED.value))
    except ValueError:
        state = TaskState.RECEIVED
    if state.terminal:
        return False
    summary = str(reason or "任务已取消")
    result = TaskResult(
        status="cancelled",
        summary=summary,
        not_completed=({"reason": summary},),
        retryable=False,
    )
    update_state(
        task_id, TaskState.CANCELLED,
        result=result, cancel_reason=summary,
    )
    append_event(
        task_id, "task_cancelled", TaskState.CANCELLED,
        {"result": result.to_dict()},
    )
    return True


def get_task(task_id: str) -> dict[str, Any] | None:
    conn = db.get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM agent_tasks WHERE task_id=?", (str(task_id),)
        ).fetchone()
        if row is None:
            return None
        data = dict(row)
        for key in ("spec_json", "checkpoint_json", "outcome_json"):
            try:
                data[key[:-5] if key.endswith("_json") else key] = json.loads(data.get(key) or "{}")
            except (TypeError, ValueError, json.JSONDecodeError):
                data[key[:-5] if key.endswith("_json") else key] = {}
        return data
    finally:
        conn.close()


def update_state(
    task_id: str,
    state: TaskState,
    *,
    checkpoint: dict[str, Any] | None = None,
    result: TaskResult | None = None,
    cancel_reason: str = "",
) -> None:
    values: list[Any] = [state.value, time.time()]
    setters = ["state=?", "updated_at=?"]
    if checkpoint is not None:
        setters.append("checkpoint_json=?")
        values.append(json.dumps(checkpoint, ensure_ascii=False))
    if result is not None:
        setters.append("outcome_json=?")
        values.append(json.dumps(result.to_dict(), ensure_ascii=False))
    if cancel_reason:
        setters.append("cancel_reason=?")
        values.append(str(cancel_reason))
    values.append(str(task_id))
    conn = db.get_conn()
    try:
        conn.execute(
            f"UPDATE agent_tasks SET {', '.join(setters)} WHERE task_id=?",
            tuple(values),
        )
        conn.commit()
    finally:
        conn.close()


def append_event(
    task_id: str,
    event_type: str,
    state: TaskState,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    conn = db.get_conn()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT COALESCE(MAX(seq), 0) + 1 FROM agent_task_events WHERE task_id=?",
            (str(task_id),),
        ).fetchone()
        seq = int(row[0] if row else 1)
        created_at = time.time()
        clean_payload = dict(payload or {})
        conn.execute(
            """
            INSERT INTO agent_task_events
            (task_id, seq, event_type, state, payload_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                str(task_id), seq, str(event_type), state.value,
                json.dumps(clean_payload, ensure_ascii=False), created_at,
            ),
        )
        conn.commit()
        return {
            "task_id": str(task_id), "seq": seq, "type": str(event_type),
            "state": state.value, "payload": clean_payload,
            "created_at": created_at,
        }
    finally:
        conn.close()


def list_events(task_id: str, after: int = 0) -> list[dict[str, Any]]:
    conn = db.get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM agent_task_events WHERE task_id=? AND seq>? ORDER BY seq",
            (str(task_id), max(0, int(after))),
        ).fetchall()
        events = []
        for row in rows:
            item = dict(row)
            try:
                payload = json.loads(item.get("payload_json") or "{}")
            except (TypeError, ValueError, json.JSONDecodeError):
                payload = {}
            events.append({
                "task_id": item["task_id"], "seq": item["seq"],
                "type": item["event_type"], "state": item["state"],
                "payload": payload, "created_at": item["created_at"],
            })
        return events
    finally:
        conn.close()


def record_effect(
    idempotency_key: str,
    *,
    task_id: str,
    tool_name: str,
    target_key: str,
    status: str,
    result: dict[str, Any] | str | None = None,
) -> bool:
    conn = db.get_conn()
    try:
        cursor = conn.execute(
            """
            INSERT OR IGNORE INTO agent_effects
            (idempotency_key, task_id, tool_name, target_key, status,
             result_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(idempotency_key), str(task_id), str(tool_name),
                str(target_key), str(status),
                json.dumps(result, ensure_ascii=False) if not isinstance(result, str) else result,
                time.time(), time.time(),
            ),
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def get_effect(idempotency_key: str) -> dict[str, Any] | None:
    conn = db.get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM agent_effects WHERE idempotency_key=?",
            (str(idempotency_key),),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()
