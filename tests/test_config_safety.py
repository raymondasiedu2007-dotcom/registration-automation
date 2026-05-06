from pathlib import Path

import pytest

from app.config import ConfigError, load_config
from app.safety import SafetyError, is_domain_allowed, validate_allowed_url


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
