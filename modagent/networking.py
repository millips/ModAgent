"""Small, deterministic network-route planner for the LLM HTTP client."""

from __future__ import annotations

import os
from urllib.parse import urlparse


SUPPORTED_PROXY_SCHEMES = {"http", "https", "socks5", "socks5h"}


def _env_value(environ, name: str) -> str:
    for key, value in environ.items():
        if key.casefold() == name.casefold() and str(value or "").strip():
            return str(value).strip()
    return ""


def plan_http_route(endpoint: str, environ=None) -> dict:
    """Choose a supported explicit proxy, or safely bypass an unsupported one."""
    environ = os.environ if environ is None else environ
    endpoint_scheme = urlparse(endpoint or "").scheme.casefold()
    preferred = "HTTPS_PROXY" if endpoint_scheme == "https" else "HTTP_PROXY"
    proxy_url = (
        _env_value(environ, preferred)
        or _env_value(environ, "ALL_PROXY")
        or _env_value(environ, "HTTP_PROXY")
    )
    if not proxy_url:
        return {"mode": "direct", "proxy_url": "", "reason": "未配置系统代理"}

    scheme = urlparse(proxy_url).scheme.casefold()
    if scheme not in SUPPORTED_PROXY_SCHEMES:
        return {
            "mode": "direct_fallback",
            "proxy_url": "",
            "ignored_proxy": proxy_url,
            "reason": f"系统代理协议 {scheme or '未知'} 不受 HTTPX 支持，已自动改走直连",
        }
    if scheme == "socks5h":
        proxy_url = "socks5://" + proxy_url.split("://", 1)[1]
    return {"mode": "proxy", "proxy_url": proxy_url, "reason": f"使用 {scheme} 系统代理"}


def build_http_client(endpoint: str, timeout: float = 120):
    import httpx

    route = plan_http_route(endpoint)
    kwargs = {"timeout": timeout, "trust_env": False}
    if route["mode"] == "proxy":
        kwargs["proxy"] = route["proxy_url"]
    return httpx.Client(**kwargs), route


def friendly_network_error(exc: Exception, route: dict | None = None) -> str:
    text = str(exc)
    if "Unknown scheme for proxy URL" in text:
        return "检测到不受支持的代理协议，已忽略该代理；请重试，程序会改走直连。"
    if route and route.get("mode") == "direct_fallback":
        return f"直连 LLM 服务失败（已自动绕过不兼容代理）：{text}"
    return text
