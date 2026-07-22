"""Short-lived one-time tokens for destructive-action confirmation previews."""
from __future__ import annotations

import secrets
import threading
import time

_TTL_SECONDS = 15 * 60
_LOCK = threading.Lock()
_TOKENS: dict[str, tuple[str, str, float]] = {}


def issue(action: str, target: str) -> str:
    now = time.time()
    token = secrets.token_urlsafe(24)
    with _LOCK:
        for old, (_, _, expires) in list(_TOKENS.items()):
            if expires <= now:
                _TOKENS.pop(old, None)
        _TOKENS[token] = (str(action), str(target), now + _TTL_SECONDS)
    return token


def consume(token: str, action: str, target: str) -> bool:
    with _LOCK:
        record = _TOKENS.pop(str(token or ""), None)
    if not record:
        return False
    expected_action, expected_target, expires = record
    return (expires > time.time() and expected_action == str(action)
            and expected_target == str(target))
