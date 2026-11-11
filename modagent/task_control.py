"""Per-tool cooperative cancellation propagated into the worker thread.

The chat API owns the cancellation event.  Agent tool calls run in a shared
ThreadPoolExecutor, so a thread-local binding is used to make the event visible
to lower-level network loops without adding a cancellation argument to every
source adapter.
"""
from __future__ import annotations

import threading
import os
import inspect
from functools import wraps
from contextlib import contextmanager
from typing import Callable, Iterator, Optional


class TaskCancelled(RuntimeError):
    """Raised when the user stops or supersedes the owning chat turn."""


_local = threading.local()
_write_locks = {}
_write_locks_guard = threading.Lock()


@contextmanager
def observe_progress(sink=None, cache=None):
    previous = getattr(_local, 'progress_sink', None), getattr(_local, 'read_cache', None)
    _local.progress_sink = sink
    _local.read_cache = cache if cache is not None else {}
    try:
        yield
    finally:
        _local.progress_sink, _local.read_cache = previous


def read_cache():
    return getattr(_local, 'read_cache', None)


def report_progress(**event):
    if is_cancelled():
        return
    sink = getattr(_local, 'progress_sink', None)
    if callable(sink):
        sink(event)


def scoped_worker(function, *args, **kwargs):
    """Capture the owner before crossing an executor/thread boundary."""
    check = getattr(_local, 'cancel_check', None)
    sink = getattr(_local, 'progress_sink', None)
    cache = getattr(_local, 'read_cache', None)
    def run():
        with bind(check), observe_progress(sink, cache):
            raise_if_cancelled()
            return function(*args, **kwargs)
    return run


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
        # An unavailable cancellation authority must not permit new writes.
        return True


def raise_if_cancelled() -> None:
    if is_cancelled():
        raise TaskCancelled("用户已停止本轮任务；旧轮次不会继续执行或写回结果。")


@contextmanager
def game_write_scope(game_root: str):
    """Serialize live writers, including a timed-out worker still unwinding.

    The owning tool holds this lock through its file and metadata commit.
    New work may wait, but cancellation is rechecked before obtaining access.
    This is process-local; durable cross-process fencing is a separate layer.
    """
    identity = os.path.normcase(os.path.realpath(game_root or "."))
    with _write_locks_guard:
        lock = _write_locks.setdefault(identity, threading.RLock())
    while True:
        raise_if_cancelled()
        if lock.acquire(timeout=.1):
            break
    try:
        raise_if_cancelled()
        yield
    finally:
        lock.release()


def serialized_game_operation(function):
    signature = inspect.signature(function)
    @wraps(function)
    def wrapped(*args, **kwargs):
        bound = signature.bind(*args, **kwargs)
        with game_write_scope(bound.arguments.get("game_root", "")):
            return function(*args, **kwargs)
    return wrapped
