from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any
from urllib.parse import unquote, urlparse


class ProxyRotationError(ValueError):
    """Raised when proxy rotation is enabled but a proxy cannot be fetched or parsed."""


@dataclass(slots=True)
class ProxyRotationConfig:
    enabled: bool = False
    api_url: str = ""
    api_key: str = ""
    api_key_header: str = "Authorization"
    api_key_prefix: str = "Bearer"
    proxy_json_path: str = "proxy"
    timeout_seconds: float = 10.0


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
        if not self.config.api_url:
            raise ProxyRotationError("Proxy rotation is enabled but proxy_rotation.api_url is missing")

        import httpx

        headers = _auth_headers(self.config)
        async with httpx.AsyncClient(timeout=self.config.timeout_seconds) as client:
            response = await client.get(self.config.api_url, headers=headers)
            response.raise_for_status()
        return parse_proxy_response(response.text, response.headers.get("content-type", ""), self.config.proxy_json_path)


def load_proxy_rotation_config(raw: dict[str, Any]) -> ProxyRotationConfig:
    proxy_raw = raw.get("proxy_rotation", {}) or {}
    return ProxyRotationConfig(
        enabled=bool(proxy_raw.get("enabled", False)),
        api_url=_expand_env(str(proxy_raw.get("api_url") or os.getenv("PROXY_API_URL", ""))),
        api_key=_expand_env(str(proxy_raw.get("api_key") or os.getenv("PROXY_API_KEY", ""))),
        api_key_header=str(proxy_raw.get("api_key_header", "Authorization")),
        api_key_prefix=str(proxy_raw.get("api_key_prefix", "Bearer")),
        proxy_json_path=str(proxy_raw.get("proxy_json_path", "proxy")),
        timeout_seconds=float(proxy_raw.get("timeout_seconds", 10.0)),
    )


def parse_proxy_response(raw: str, content_type: str = "", proxy_json_path: str = "proxy") -> dict[str, str]:
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
        direct = _proxy_from_json_fields(payload)
        if direct:
            return direct
        proxy_value = _value_at_json_path(payload, proxy_json_path)
        if not isinstance(proxy_value, str):
            raise ProxyRotationError(f"Proxy API JSON response does not contain a string at '{proxy_json_path}'")
        return _proxy_from_url(proxy_value)

    return _proxy_from_url(raw)


def _proxy_from_json_fields(payload: dict[str, Any]) -> dict[str, str] | None:
    server = payload.get("server")
    if not isinstance(server, str):
        return None
    parsed = _proxy_from_url(server)
    username = payload.get("username")
    password = payload.get("password")
    if isinstance(username, str) and username:
        parsed["username"] = username
    if isinstance(password, str) and password:
        parsed["password"] = password
    return parsed


def _proxy_from_url(raw_url: str) -> dict[str, str]:
    parsed = urlparse(raw_url.strip())
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


def _expand_env(value: str) -> str:
    if value.startswith("${") and value.endswith("}"):
        return os.getenv(value[2:-1], "")
    return value
