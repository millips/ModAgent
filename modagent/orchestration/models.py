from __future__ import annotations

import time
import uuid
import hashlib
import json
from dataclasses import asdict, dataclass, field, fields
from collections.abc import Mapping
from types import MappingProxyType
from enum import Enum
from typing import Any


def _freeze(value):
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


def _thaw(value):
    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


class AgentMode(str, Enum):
    CHAT_EXPLAIN = "CHAT_EXPLAIN"
    STATUS_CHECK = "STATUS_CHECK"
    SEARCH_EXACT = "SEARCH_EXACT"
    RECOMMEND_BROAD = "RECOMMEND_BROAD"
    RESOLVE_SOURCE = "RESOLVE_SOURCE"
    BUILD_PLAN = "BUILD_PLAN"
    EXECUTE_PLAN = "EXECUTE_PLAN"
    UPDATE_INSTALLED = "UPDATE_INSTALLED"
    DIAGNOSE = "DIAGNOSE"
    SNAPSHOT_ROLLBACK = "SNAPSHOT_ROLLBACK"
    IMPORT_SHARE = "IMPORT_SHARE"


class TaskState(str, Enum):
    RECEIVED = "RECEIVED"
    CLASSIFIED = "CLASSIFIED"
    GATHERING = "GATHERING"
    PRESENTING = "PRESENTING"
    WAITING_CONFIRMATION = "WAITING_CONFIRMATION"
    EXECUTING = "EXECUTING"
    VERIFYING = "VERIFYING"
    COMPLETED = "COMPLETED"
    PARTIAL = "PARTIAL"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    PAUSED_BY_NEW_TURN = "PAUSED_BY_NEW_TURN"

    @property
    def terminal(self) -> bool:
        return self in {
            self.COMPLETED,
            self.PARTIAL,
            self.BLOCKED,
            self.FAILED,
            self.CANCELLED,
            self.PAUSED_BY_NEW_TURN,
        }


@dataclass(frozen=True)
class TaskSpec:
    task_id: str
    session_id: str
    turn_id: str
    game_id: str
    intent: AgentMode
    user_goal: str
    targets: tuple[Mapping[str, Any], ...] = ()
    constraints: Mapping[str, Any] = field(default_factory=dict)
    authorization: Mapping[str, bool] = field(default_factory=dict)
    language: str = "zh-CN"
    confidence: float = 1.0
    route_reason: str = ""
    resumed_from: str = ""
    created_at: float = field(default_factory=time.time)

    def __post_init__(self):
        # frozen=True alone only protects the outer attributes. Never retain
        # a caller-owned nested list/dict inside the authoritative task.
        for name in ("targets", "constraints", "authorization"):
            object.__setattr__(self, name, _freeze(getattr(self, name)))

    @classmethod
    def create(
        cls,
        *,
        session_id: str,
        game_id: str,
        intent: AgentMode,
        user_goal: str,
        targets: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None = None,
        constraints: dict[str, Any] | None = None,
        authorization: dict[str, bool] | None = None,
        language: str = "zh-CN",
        confidence: float = 1.0,
        route_reason: str = "",
        task_id: str = "",
        turn_id: str = "",
        resumed_from: str = "",
    ) -> "TaskSpec":
        return cls(
            task_id=task_id or f"task_{uuid.uuid4().hex}",
            session_id=session_id,
            turn_id=turn_id or f"turn_{uuid.uuid4().hex}",
            game_id=game_id,
            intent=intent,
            user_goal=str(user_goal or "").strip(),
            targets=tuple(dict(item) for item in (targets or [])),
            constraints=dict(constraints or {}),
            authorization={
                "install": False,
                "destructive": False,
                **dict(authorization or {}),
            },
            language="en" if str(language).lower().startswith("en") else "zh-CN",
            confidence=max(0.0, min(float(confidence), 1.0)),
            route_reason=str(route_reason or ""),
            resumed_from=str(resumed_from or ""),
        )

    def to_dict(self) -> dict[str, Any]:
        data = {item.name: _thaw(getattr(self, item.name)) for item in fields(self)}
        data["intent"] = self.intent.value
        return data

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "TaskSpec":
        data = dict(value or {})
        data["intent"] = AgentMode(str(data.get("intent") or AgentMode.CHAT_EXPLAIN.value))
        data["targets"] = tuple(data.get("targets") or [])
        return cls(**data)


@dataclass(frozen=True)
class TaskEvent:
    task_id: str
    seq: int
    event_type: str
    state: TaskState
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "seq": self.seq,
            "type": self.event_type,
            "state": self.state.value,
            "payload": dict(self.payload),
            "created_at": self.created_at,
        }


@dataclass(frozen=True)
class TaskResult:
    status: str
    summary: str
    completed: tuple[dict[str, Any], ...] = ()
    not_completed: tuple[dict[str, Any], ...] = ()
    warnings: tuple[str, ...] = ()
    next_actions: tuple[dict[str, Any], ...] = ()
    retryable: bool = False

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["completed"] = [dict(item) for item in self.completed]
        data["not_completed"] = [dict(item) for item in self.not_completed]
        data["warnings"] = list(self.warnings)
        data["next_actions"] = [dict(item) for item in self.next_actions]
        return data


@dataclass(frozen=True)
class PlanRevision:
    revision_id: str
    task_id: str
    session_id: str
    game_id: str
    targets: tuple[Mapping[str, Any], ...]
    created_at: float = field(default_factory=time.time)

    def __post_init__(self):
        object.__setattr__(self, "targets", _freeze(self.targets))

    @classmethod
    def create(
        cls, *, task_id: str, session_id: str, game_id: str,
        targets: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    ) -> "PlanRevision":
        frozen_targets = tuple(dict(item) for item in targets)
        identity = json.dumps({
            "task_id": str(task_id),
            "session_id": str(session_id),
            "game_id": str(game_id),
            "targets": [_thaw(item) for item in frozen_targets],
        }, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
        digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()
        return cls(
            revision_id=f"plan_{digest[:32]}", task_id=str(task_id),
            session_id=str(session_id), game_id=str(game_id),
            targets=frozen_targets,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "revision_id": self.revision_id,
            "task_id": self.task_id,
            "session_id": self.session_id,
            "game_id": self.game_id,
            "targets": [_thaw(item) for item in self.targets],
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "PlanRevision":
        data = dict(value or {})
        data["targets"] = tuple(data.get("targets") or [])
        return cls(**data)


@dataclass(frozen=True)
class ExecutionGrant:
    grant_id: str
    plan_task_id: str
    plan_revision_id: str
    session_id: str
    game_id: str
    targets: tuple[Mapping[str, Any], ...]
    created_at: float = field(default_factory=time.time)
    consumed_at: float = field(default_factory=time.time)

    def __post_init__(self):
        object.__setattr__(self, "targets", _freeze(self.targets))

    @classmethod
    def create(
        cls, *, revision: PlanRevision, targets: list[dict[str, Any]],
    ) -> "ExecutionGrant":
        now = time.time()
        return cls(
            grant_id=f"grant_{uuid.uuid4().hex}",
            plan_task_id=revision.task_id,
            plan_revision_id=revision.revision_id,
            session_id=revision.session_id,
            game_id=revision.game_id,
            targets=tuple(dict(item) for item in targets),
            created_at=now, consumed_at=now,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "grant_id": self.grant_id,
            "plan_task_id": self.plan_task_id,
            "plan_revision_id": self.plan_revision_id,
            "session_id": self.session_id,
            "game_id": self.game_id,
            "targets": [_thaw(item) for item in self.targets],
            "created_at": self.created_at,
            "consumed_at": self.consumed_at,
        }
