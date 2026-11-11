"""Small, deterministic network-route planner for the LLM HTTP client."""

from __future__ import annotations

import os
from urllib.parse import urlparse


SUPPORTED_PROXY_SCHEMES = {"http", "https", "socks5", "socks5h"}


class CredentialFormatError(ValueError):
    """Contains a field identifier only, never the rejected secret."""
    def __init__(self, field: str):
        self.field = field if field in {"llm_api_key", "nexus_api_key", "tavily_api_key"} else "llm_api_key"
        super().__init__(f"credential_{self.field}_invalid")


def validate_api_key(value: str, field: str) -> str:
    clean = str(value or "").strip()
    # No provider-specific prefix requirement; empty also permits explicit clear.
    if any(ord(char) < 33 or ord(char) > 126 for char in clean):
        raise CredentialFormatError(field)
    return clean


def model_failure_summary(exc: Exception, route: dict | None = None) -> tuple[str, bool]:
    configuration_error = isinstance(exc, (CredentialFormatError, UnicodeError))
    advice = "请在设置中修正配置后重新发送。" if configuration_error else "请检查连接或服务状态后重新发送。"
    return (
        "本轮未能完成模型通信：" + friendly_network_error(exc, route)
        + "。已停止新增操作；此前已执行的结果请以任务记录为准。" + advice,
        not configuration_error,
    )


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
    if isinstance(exc, CredentialFormatError):
        field = {"llm_api_key": "LLM API Key", "nexus_api_key": "Nexus API Key", "tavily_api_key": "Tavily API Key"}[exc.field]
        return f"{field} 格式不正确，请填写密钥本身，不要包含中文、空格或换行"
    if isinstance(exc, UnicodeError):
        return "请求配置发生字符编码错误，请检查密钥及自定义请求配置；这不等同于网络断开"
    text = str(exc)
    if "Unknown scheme for proxy URL" in text:
        return "检测到不受支持的代理协议，已忽略该代理；请重试，程序会改走直连。"
    if route and route.get("mode") == "direct_fallback":
        return f"直连 LLM 服务失败（已自动绕过不兼容代理）：{text}"
    return text
