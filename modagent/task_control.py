"""Per-tool cooperative cancellation propagated into the worker thread.

The chat API owns the cancellation event.  Agent tool calls run in a shared
ThreadPoolExecutor, so a thread-local binding is used to make the event visible
to lower-level network loops without adding a cancellation argument to every
source adapter.
"""
from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Callable, Iterator, Optional


class TaskCancelled(RuntimeError):
    """Raised when the user stops or supersedes the owning chat turn."""


_local = threading.local()


@contextmanager
def bind(cancel_check: Optional[Callable[[], bool]]) -> Iterator[None]:
    previous = getattr(_local, "cancel_check", None)
    _local.cancel_check = cancel_check
    try:
        yield
    finally:
        _local.cancel_check = previous


def is_cancelled() -> bool:
    check = getattr(_local, "cancel_check", None)
    if not callable(check):
        return False
    try:
        return bool(check())
    except Exception:
        # Cancellation checks must never turn into an unrelated tool failure.
        return False


def raise_if_cancelled() -> None:
    if is_cancelled():
        raise TaskCancelled("用户已停止本轮任务；旧轮次不会继续执行或写回结果。")
