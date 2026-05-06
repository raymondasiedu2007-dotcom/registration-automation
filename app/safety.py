from __future__ import annotations

from urllib.parse import urlparse

from app.models import SiteConfig


class SafetyError(PermissionError):
    """Raised when an automation action violates configured safety boundaries."""


def normalize_host(url: str) -> str:
    host = urlparse(url).hostname
    if not host:
        raise SafetyError(f"URL has no hostname: {url}")
    return host.lower().rstrip(".")


def is_domain_allowed(url: str, site: SiteConfig) -> bool:
    host = normalize_host(url)
    domain = site.domain.lower().rstrip(".")
    return host == domain or host.endswith(f".{domain}")


def validate_allowed_url(url: str, site: SiteConfig) -> None:
    if not is_domain_allowed(url, site):
        raise SafetyError(f"Blocked navigation to non-allowlisted domain: {url}")


def ensure_not_bulk(count: int) -> None:
    if count > 1:
        raise SafetyError("Bulk account creation is not supported; run one authorized registration at a time.")
