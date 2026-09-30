"""Agent Core v2 orchestration primitives.

The package is intentionally independent from the legacy ``Agent`` loop.  The
legacy path can therefore remain available while task modes are migrated one
by one behind the ``agent_core_v2`` feature flag.
"""

from .models import AgentMode, TaskEvent, TaskResult, TaskSpec, TaskState
from .router import RouteDecision, route_message
from .runtime import AgentCoreRuntime

__all__ = [
    "AgentCoreRuntime",
    "AgentMode",
    "RouteDecision",
    "TaskEvent",
    "TaskResult",
    "TaskSpec",
    "TaskState",
    "route_message",
]
