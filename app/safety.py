from __future__ import annotations

from collections.abc import Sequence
from urllib.parse import urlparse

from app.models import SiteConfig


MAX_CONCURRENT_REGISTRATIONS = 10
MAX_CONFIGURED_UNIQUE_SITES = 40


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
    if count > MAX_CONFIGURED_UNIQUE_SITES:
        raise SafetyError(f"At most {MAX_CONFIGURED_UNIQUE_SITES} unique configured sites may be registered in one task.")


def validate_registration_batch(sites: Sequence[SiteConfig], requested_concurrency: int = 1) -> None:
    """Validate a same-user, unique-site registration batch.

    A batch may register one authorized user on multiple distinct configured sites,
    with up to 10 concurrent workers and up to 40 unique sites in a task. Duplicate
    site registrations and higher concurrency are rejected to avoid spam/bulk abuse.
    """
    if requested_concurrency < 1:
        raise SafetyError("Registration concurrency must be at least 1.")
    if requested_concurrency > MAX_CONCURRENT_REGISTRATIONS:
        raise SafetyError(f"At most {MAX_CONCURRENT_REGISTRATIONS} concurrent registration workers are supported.")
    site_keys = [site.key for site in sites]
    if len(site_keys) != len(set(site_keys)):
        raise SafetyError("Duplicate site registrations in one task are not supported.")
    ensure_not_bulk(len(site_keys))
