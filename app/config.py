from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from app.yaml_compat import safe_load

from app.models import PROFILE_FIELDS, SiteConfig


class ConfigError(ValueError):
    """Raised when config.yaml is missing required or safe values."""


class AppConfig:
    def __init__(self, raw: dict[str, Any], source: Path | None = None) -> None:
        self.raw = raw
        self.source = source
        self.telegram_token = os.getenv("TELEGRAM_BOT_TOKEN") or raw.get("telegram", {}).get("bot_token", "")
        self.database_path = raw.get("database", {}).get("path", "registration_bot.sqlite3")
        self.screenshots_dir = raw.get("screenshots_dir", "screenshots")
        # Safety default: registration automation runs headless. This is intentionally
        # not configurable to a visible browser mode from YAML.
        self.playwright_headless = True
        self.ai = raw.get("ai", {})
        self.sites = _parse_sites(raw.get("sites", {}))

    @property
    def enabled_sites(self) -> dict[str, SiteConfig]:
        return {key: site for key, site in self.sites.items() if site.enabled}

    def require_site(self, key: str) -> SiteConfig:
        site = self.sites.get(key)
        if site is None:
            raise ConfigError(f"Unknown site: {key}")
        if not site.enabled:
            raise ConfigError(f"Site is disabled: {key}")
        return site


def load_config(path: str | Path = "config.yaml") -> AppConfig:
    config_path = Path(path)
    if not config_path.exists():
        raise ConfigError(f"Config file not found: {config_path}")
    with config_path.open("r", encoding="utf-8") as handle:
        raw = safe_load(handle.read()) or {}
    return AppConfig(raw, config_path)


def _parse_sites(raw_sites: dict[str, Any] | list[dict[str, Any]]) -> dict[str, SiteConfig]:
    sites: dict[str, SiteConfig] = {}
    iterable = raw_sites.items() if isinstance(raw_sites, dict) else ((item.get("key"), item) for item in raw_sites or [])
    for key, raw in iterable:
        if not key:
            raise ConfigError("Every site must have a key")
        domain = str(raw.get("domain", "")).lower().strip()
        url = str(raw.get("registration_url", "")).strip()
        if not domain or not url:
            raise ConfigError(f"Site {key} must define domain and registration_url")
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ConfigError(f"Site {key} has invalid registration_url")
        if parsed.hostname and parsed.hostname.lower() != domain and not parsed.hostname.lower().endswith(f".{domain}"):
            raise ConfigError(f"Site {key} URL host must match configured domain")
        required = raw.get("required_profile_fields") or PROFILE_FIELDS.copy()
        invalid_fields = set(required) - set(PROFILE_FIELDS)
        if invalid_fields:
            raise ConfigError(f"Site {key} has invalid profile fields: {sorted(invalid_fields)}")
        sites[str(key)] = SiteConfig(
            key=str(key),
            name=raw.get("name", str(key)),
            domain=domain,
            registration_url=url,
            enabled=bool(raw.get("enabled", True)),
            selectors=raw.get("selectors", {}) or {},
            required_profile_fields=list(required),
            submit_selector=raw.get("submit_selector"),
            field_mappings=raw.get("field_mappings", {}) or {},
        )
    return sites
