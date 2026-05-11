from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import unquote, urlparse


class ProxyRotationError(ValueError):
    """Raised when proxy rotation is enabled but a proxy cannot be fetched or parsed."""


@dataclass(slots=True)
class ProxyRotationConfig:
    enabled: bool = False
    provider: str = "generic"
    api_url: str = ""
    api_key: str = ""
    api_key_header: str = "Authorization"
    api_key_prefix: str = "Bearer"
    proxy_json_path: str = "proxy"
    timeout_seconds: float = 10.0
    request_params: dict[str, str] = field(default_factory=dict)
    proxy_scheme: str = "http"


class ProxyRotator:
    def __init__(self, config: ProxyRotationConfig) -> None:
        self.config = config

    @property
    def enabled(self) -> bool:
        return self.config.enabled

    async def next_proxy(self) -> dict[str, str] | None:
        """Fetch the next proxy from a provider API and return Playwright launch options."""
        if not self.config.enabled:
            return None

        import httpx

        url, params = _request_url_and_params(self.config)
        headers = _auth_headers(self.config)
        async with httpx.AsyncClient(timeout=self.config.timeout_seconds) as client:
            response = await client.get(url, headers=headers, params=params or None)
            response.raise_for_status()
        return parse_proxy_response(response.text, response.headers.get("content-type", ""), self.config.proxy_json_path, self.config.proxy_scheme)


def load_proxy_rotation_config(raw: dict[str, Any]) -> ProxyRotationConfig:
    proxy_raw = raw.get("proxy_rotation", {}) or {}
    provider = str(proxy_raw.get("provider", "generic")).lower().strip() or "generic"
    api_key_header = str(proxy_raw.get("api_key_header", "api-key" if provider == "9proxy" else "Authorization"))
    api_key_prefix = str(proxy_raw.get("api_key_prefix", "" if provider == "9proxy" else "Bearer"))
    proxy_json_path = str(proxy_raw.get("proxy_json_path", "data.0" if provider == "9proxy" else "proxy"))
    api_url = str(proxy_raw.get("api_url") or os.getenv("PROXY_API_URL", ""))
    if provider == "9proxy" and not api_url:
        api_url = "https://api.9proxy.com/api/proxy"
    return ProxyRotationConfig(
        enabled=bool(proxy_raw.get("enabled", False)),
        provider=provider,
        api_url=_expand_env(api_url),
        api_key=_expand_env(str(proxy_raw.get("api_key") or os.getenv("PROXY_API_KEY", ""))),
        api_key_header=api_key_header,
        api_key_prefix=api_key_prefix,
        proxy_json_path=proxy_json_path,
        timeout_seconds=float(proxy_raw.get("timeout_seconds", 10.0)),
        request_params=_normalize_request_params(proxy_raw.get("request_params", {}) or {}),
        proxy_scheme=str(proxy_raw.get("proxy_scheme", "http")).lower().strip() or "http",
    )


def parse_proxy_response(raw: str, content_type: str = "", proxy_json_path: str = "proxy", proxy_scheme: str = "http") -> dict[str, str]:
    """Parse a proxy provider response into Playwright's proxy dictionary."""
    raw = raw.strip()
    if not raw:
        raise ProxyRotationError("Proxy API returned an empty response")

    if "json" in content_type.lower() or raw.startswith("{"):
        import json

        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ProxyRotationError("Proxy API response must be valid JSON") from exc
        if not isinstance(payload, dict):
            raise ProxyRotationError("Proxy API JSON response must be an object")
        _raise_for_provider_error(payload)
        direct = _proxy_from_json_fields(payload, proxy_scheme)
        if direct:
            return direct
        proxy_value = _value_at_json_path(payload, proxy_json_path)
        if isinstance(proxy_value, list):
            proxy_value = next((item for item in proxy_value if isinstance(item, str) and item.strip()), None)
        if not isinstance(proxy_value, str):
            raise ProxyRotationError(f"Proxy API JSON response does not contain a proxy string at '{proxy_json_path}'")
        return _proxy_from_url(proxy_value, proxy_scheme)

    return _proxy_from_url(raw.splitlines()[0], proxy_scheme)


def _proxy_from_json_fields(payload: dict[str, Any], proxy_scheme: str) -> dict[str, str] | None:
    server = payload.get("server")
    if not isinstance(server, str):
        return None
    parsed = _proxy_from_url(server, proxy_scheme)
    username = payload.get("username")
    password = payload.get("password")
    if isinstance(username, str) and username:
        parsed["username"] = username
    if isinstance(password, str) and password:
        parsed["password"] = password
    return parsed


def _proxy_from_url(raw_url: str, proxy_scheme: str = "http") -> dict[str, str]:
    cleaned = raw_url.strip()
    if "://" not in cleaned:
        cleaned = f"{proxy_scheme}://{cleaned}"
    parsed = urlparse(cleaned)
    if parsed.scheme not in {"http", "https", "socks4", "socks5"}:
        raise ProxyRotationError("Proxy URL must include http, https, socks4, or socks5 scheme")
    if not parsed.hostname or parsed.port is None:
        raise ProxyRotationError("Proxy URL must include host and port")

    result = {"server": f"{parsed.scheme}://{parsed.hostname}:{parsed.port}"}
    if parsed.username:
        result["username"] = unquote(parsed.username)
    if parsed.password:
        result["password"] = unquote(parsed.password)
    return result


def _value_at_json_path(payload: dict[str, Any], path: str) -> Any:
    current: Any = payload
    for part in path.split("."):
        if isinstance(current, list) and part.isdigit():
            index = int(part)
            current = current[index] if index < len(current) else None
            continue
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def _auth_headers(config: ProxyRotationConfig) -> dict[str, str]:
    if not config.api_key:
        return {}
    value = config.api_key
    if config.api_key_prefix:
        value = f"{config.api_key_prefix} {config.api_key}"
    return {config.api_key_header: value}


def _request_url_and_params(config: ProxyRotationConfig) -> tuple[str, dict[str, str]]:
    if not config.api_url:
        raise ProxyRotationError("Proxy rotation is enabled but proxy_rotation.api_url is missing")
    params = dict(config.request_params)
    if config.provider == "9proxy":
        params = {"num": "1", "t": "2", **params}
    return config.api_url, params


def _normalize_request_params(raw_params: dict[str, Any]) -> dict[str, str]:
    return {str(key): str(value).lower() if isinstance(value, bool) else str(value) for key, value in raw_params.items() if value is not None}


def _raise_for_provider_error(payload: dict[str, Any]) -> None:
    if payload.get("error") is True or payload.get("success") is False:
        message = payload.get("message")
        if not isinstance(message, str) or not message:
            message = "Proxy API returned an error response"
        raise ProxyRotationError(message)


def _expand_env(value: str) -> str:
    if value.startswith("${") and value.endswith("}"):
        return os.getenv(value[2:-1], "")
    return value
