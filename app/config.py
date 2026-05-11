from __future__ import annotations

import os
from pathlib import Path
from typing import Any
import re
from urllib.parse import urlparse

from app.yaml_compat import safe_load

from app.models import PROFILE_FIELDS, SiteConfig
from app.proxy import ProxyRotationConfig, load_proxy_rotation_config


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
        self.proxy_rotation: ProxyRotationConfig = load_proxy_rotation_config(raw)
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


def parse_sites_config_text(text: str) -> dict[str, SiteConfig]:
    """Parse an uploaded sites.yaml/sites.json payload into validated site config."""
    raw = safe_load(text) or {}
    if isinstance(raw, dict) and "sites" in raw:
        raw = raw["sites"]
    return _parse_sites(raw)


def _parse_sites(raw_sites: dict[str, Any] | list[dict[str, Any]]) -> dict[str, SiteConfig]:
    sites: dict[str, SiteConfig] = {}
    if isinstance(raw_sites, dict):
        iterable = raw_sites.items()
    else:
        iterable = ((_site_key_from_raw(item), item) for item in raw_sites or [])
    for key, raw in iterable:
        if not isinstance(raw, dict):
            raise ConfigError(f"Site {key or '<unknown>'} must be an object")
        url = str(raw.get("registration_url") or raw.get("signup_url") or "").strip()
        parsed = urlparse(url)
        domain = str(raw.get("domain") or parsed.hostname or "").lower().strip().rstrip(".")
        if not key:
            key = _site_key_from_raw(raw)
        if not key:
            raise ConfigError("Every site must have a key, name, or signup_url")
        if not domain or not url:
            raise ConfigError(f"Site {key} must define domain/signup_url or domain/registration_url")
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ConfigError(f"Site {key} has invalid registration_url")
        if parsed.hostname and parsed.hostname.lower().rstrip(".") != domain and not parsed.hostname.lower().rstrip(".").endswith(f".{domain}"):
            raise ConfigError(f"Site {key} URL host must match configured domain")
        required = raw.get("required_profile_fields") or PROFILE_FIELDS.copy()
        invalid_fields = set(required) - set(PROFILE_FIELDS)
        if invalid_fields:
            raise ConfigError(f"Site {key} has invalid profile fields: {sorted(invalid_fields)}")
        status = str(raw.get("status", "active")).lower().strip() or "active"
        enabled = bool(raw.get("enabled", status not in {"disabled", "inactive", "blocked"}))
        sites[str(key)] = SiteConfig(
            key=str(key),
            name=raw.get("name", str(key)),
            domain=domain,
            registration_url=url,
            enabled=enabled,
            selectors=raw.get("selectors", {}) or {},
            required_profile_fields=list(required),
            submit_selector=raw.get("submit_selector"),
            field_mappings=_normalize_field_mappings(raw.get("field_mappings", {}) or {}),
            notes=str(raw.get("notes", "")),
            status=status,
        )
    return sites


def _normalize_field_mappings(raw_mappings: dict[str, str]) -> dict[str, str]:
    """Accept selector->profile_field and profile_field->selector mapping styles."""
    normalized: dict[str, str] = {}
    for key, value in raw_mappings.items():
        key_str = str(key)
        value_str = str(value)
        if key_str in PROFILE_FIELDS and value_str not in PROFILE_FIELDS:
            normalized[value_str] = key_str
        else:
            normalized[key_str] = value_str
    invalid_fields = {field for field in normalized.values() if field not in PROFILE_FIELDS}
    if invalid_fields:
        raise ConfigError(f"Invalid profile fields in field_mappings: {sorted(invalid_fields)}")
    return normalized


def _site_key_from_raw(raw: dict[str, Any]) -> str:
    explicit = str(raw.get("key", "")).strip()
    if explicit:
        return explicit
    source = str(raw.get("name") or urlparse(str(raw.get("signup_url") or raw.get("registration_url") or "")).hostname or "").lower()
    return re.sub(r"[^a-z0-9]+", "_", source).strip("_")
