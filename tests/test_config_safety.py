from pathlib import Path

import pytest

from app.config import ConfigError, load_config
from app.models import SiteConfig
from app.safety import MAX_CONCURRENT_REGISTRATIONS, SafetyError, is_domain_allowed, validate_allowed_url, validate_registration_batch


def test_config_loading_parses_sites(tmp_path: Path):
    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        """
sites:
  demo:
    name: Demo
    domain: example.com
    registration_url: https://example.com/register
    enabled: true
""",
        encoding="utf-8",
    )
    config = load_config(config_file)
    assert config.sites["demo"].domain == "example.com"
    assert config.enabled_sites["demo"].registration_url == "https://example.com/register"


def test_config_rejects_registration_url_outside_domain(tmp_path: Path):
    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        """
sites:
  unsafe:
    domain: example.com
    registration_url: https://evil.test/register
""",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError):
        load_config(config_file)


def test_domain_allowlist_validation():
    site = load_config(Path("config.example.yaml")).sites["example_site"]
    assert is_domain_allowed("https://example.com/register", site)
    assert is_domain_allowed("https://accounts.example.com/register", site)
    with pytest.raises(SafetyError):
        validate_allowed_url("https://not-example.com/register", site)


def test_playwright_config_is_forced_headless(tmp_path: Path):
    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        """
playwright:
  headless: false
sites:
  demo:
    name: Demo
    domain: example.com
    registration_url: https://example.com/register
""",
        encoding="utf-8",
    )
    config = load_config(config_file)
    assert config.playwright_headless is True


def test_multi_site_registration_batch_allows_ten_concurrent_unique_sites():
    sites = [
        SiteConfig(key=f"site_{index}", name=f"Site {index}", domain=f"example{index}.com", registration_url=f"https://example{index}.com/register")
        for index in range(10)
    ]
    validate_registration_batch(sites, requested_concurrency=MAX_CONCURRENT_REGISTRATIONS)


def test_registration_batch_rejects_duplicate_sites_and_too_much_concurrency():
    config = load_config(Path("config.example.yaml"))
    site = config.sites["example_site"]
    with pytest.raises(SafetyError):
        validate_registration_batch([site], requested_concurrency=11)
    with pytest.raises(SafetyError):
        validate_registration_batch([site, site], requested_concurrency=1)
    validate_registration_batch([site], requested_concurrency=1)


def test_proxy_rotation_config_parses_api_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("PROXY_API_KEY", "secret-token")
    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        """
proxy_rotation:
  enabled: true
  api_url: https://proxy-provider.example/next
  api_key: ${PROXY_API_KEY}
  api_key_header: X-API-Key
  api_key_prefix: ""
  proxy_json_path: data.proxy
  timeout_seconds: 5
sites:
  demo:
    name: Demo
    domain: example.com
    registration_url: https://example.com/register
""",
        encoding="utf-8",
    )
    config = load_config(config_file)
    assert config.proxy_rotation.enabled is True
    assert config.proxy_rotation.api_url == "https://proxy-provider.example/next"
    assert config.proxy_rotation.api_key == "secret-token"
    assert config.proxy_rotation.api_key_header == "X-API-Key"
    assert config.proxy_rotation.api_key_prefix == ""
    assert config.proxy_rotation.proxy_json_path == "data.proxy"
    assert config.proxy_rotation.timeout_seconds == 5
