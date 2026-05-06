from __future__ import annotations

from collections.abc import Sequence
from urllib.parse import urlparse

from app.models import SiteConfig


MAX_AUTHORIZED_SITES_PER_TASK = 1
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
    if count > MAX_AUTHORIZED_SITES_PER_TASK:
        raise SafetyError("Bulk account creation is not supported; run one authorized registration at a time.")


def validate_registration_batch(sites: Sequence[SiteConfig], requested_concurrency: int = 1) -> None:
    """Reject bulk/concurrent account-registration batches.

    The project is an assisted single-site registration helper. Running 10 concurrent
    registrations across many sites would be bulk account creation, so this guard
    makes that unsupported behavior explicit.
    """
    if requested_concurrency != 1:
        raise SafetyError("Concurrent registration workers are not supported; use one authorized registration at a time.")
    site_keys = [site.key for site in sites]
    if len(site_keys) != len(set(site_keys)):
        raise SafetyError("Duplicate site registrations in one task are not supported.")
    if len(site_keys) > MAX_CONFIGURED_UNIQUE_SITES:
        raise SafetyError(f"At most {MAX_CONFIGURED_UNIQUE_SITES} unique configured sites may be listed.")
    ensure_not_bulk(len(site_keys))
