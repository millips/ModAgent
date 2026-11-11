"""Bounded, credential-free HTTP probes for the connection diagnostics panel."""
from __future__ import annotations

import asyncio
import socket
import ssl
import time
from datetime import datetime, timezone

import httpx


TARGETS = (
    {"id": "github", "name": "GitHub API", "url": "https://api.github.com/"},
    {"id": "github_raw", "name": "GitHub Raw", "url": "https://raw.githubusercontent.com/github/gitignore/main/README.md"},
    {"id": "nexus", "name": "Nexus Mods", "url": "https://www.nexusmods.com/"},
    {"id": "thunderstore", "name": "Thunderstore", "url": "https://thunderstore.io/"},
    {"id": "modio", "name": "mod.io", "url": "https://mod.io/"},
    {"id": "gamebanana", "name": "GameBanana", "url": "https://gamebanana.com/"},
    {"id": "workshop", "name": "Steam Workshop", "url": "https://steamcommunity.com/workshop/"},
)
_BY_ID = {item["id"]: item for item in TARGETS}
PROBE_TIMEOUT = 8.0
_slots = asyncio.Semaphore(3)
_active: set[str] = set()


class ProbeBusy(Exception):
    pass


def classify_status(code: int) -> str:
    if 200 <= code < 300:
        return "reachable"
    if 300 <= code < 400:
        return "redirect"
    if code == 401:
        return "auth_required"
    if code == 403:
        return "restricted"
    if code == 407:
        return "proxy_auth"
    if code == 429:
        return "rate_limited"
    if code >= 500:
        return "service_error"
    return "http_error"


def classify_exception(exc: Exception) -> str:
    # Inspect types, never return exception text (proxy URLs may contain secrets).
    chain = []
    current = exc
    while current is not None and id(current) not in {id(item) for item in chain}:
        chain.append(current)
        current = current.__cause__ or current.__context__
    if any(isinstance(item, (ssl.SSLError, ssl.CertificateError)) for item in chain):
        return "tls_error"
    if any(isinstance(item, socket.gaierror) for item in chain):
        return "dns_error"
    if isinstance(exc, (asyncio.TimeoutError, httpx.TimeoutException)):
        return "timeout"
    if isinstance(exc, httpx.ProxyError):
        return "proxy_error"
    if isinstance(exc, (ValueError, ImportError)):
        return "configuration_error"
    return "connection_error"


async def probe_target(target_id: str) -> dict:
    if target_id not in _BY_ID:
        raise ValueError("unknown_target")
    if target_id in _active:
        raise ProbeBusy()
    _active.add(target_id)
    try:
        async with _slots:
            start = time.monotonic()
            result = {"target_id": target_id, "http_status": None}

            async def request_headers():
                # No saved keys/cookies, no redirects to arbitrary hosts, no body download.
                async with httpx.AsyncClient(
                    timeout=httpx.Timeout(PROBE_TIMEOUT), follow_redirects=False,
                    trust_env=True, headers={"User-Agent": "ModAgent-ConnectionTest/1.0"},
                ) as client:
                    async with client.stream("GET", _BY_ID[target_id]["url"]) as response:
                        return response.status_code

            try:
                code = await asyncio.wait_for(request_headers(), timeout=PROBE_TIMEOUT)
                result.update(status=classify_status(code), http_status=code)
            except Exception as exc:
                result["status"] = classify_exception(exc)
            result["elapsed_ms"] = round((time.monotonic() - start) * 1000)
            result["checked_at"] = datetime.now(timezone.utc).isoformat()
            result["scope"] = "backend_http_headers"
            return result
    finally:
        _active.discard(target_id)


if __name__ == "__main__":
    import json

    async def main():
        return await asyncio.gather(*(probe_target(item["id"]) for item in TARGETS))

    print(json.dumps(asyncio.run(main()), ensure_ascii=False, indent=2))
