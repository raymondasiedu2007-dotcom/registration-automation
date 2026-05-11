from pathlib import Path
import asyncio

import pytest

from app.ai_mapper import AIMapperError, parse_ai_mapping
from app.analytics import AnalyticsService, format_analytics
from app.captcha_handler import detect_captcha_or_verification
from app.database import Database
from app.menu import main_menu
from app.models import AttemptStatus, UserProfile


def test_user_profile_validation():
    profile = UserProfile(telegram_user_id=1, first_name="Ada")
    assert "last_name" in profile.missing_required_fields()
    assert "address_line2" not in profile.missing_required_fields()
    assert not profile.is_complete()
    complete = UserProfile(
        telegram_user_id=1,
        first_name="Ada",
        last_name="Lovelace",
        address_line1="1 Algorithm Ave",
        state_region="CA",
        city="San Francisco",
        postal_code="94105",
        email="ada@example.com",
        country="US",
    )
    assert complete.is_complete()
    assert complete.masked_dict()["email"].startswith("ad***@")
    assert complete.missing_required_fields(["phone_number"]) == ["phone_number"]


def test_ai_json_parsing_accepts_valid_mapping():
    parsed = parse_ai_mapping('{"mappings":{"#email":{"profile_field":"email","confidence":0.95}}}', {"#email"})
    assert parsed["#email"]["profile_field"] == "email"


def test_ai_json_parsing_rejects_invalid_json_and_unknown_fields():
    with pytest.raises(AIMapperError):
        parse_ai_mapping("not json", {"#email"})
    with pytest.raises(AIMapperError):
        parse_ai_mapping('{"mappings":{"#email":{"profile_field":"ssn","confidence":1}}}', {"#email"})


class FakeLocator:
    def __init__(self, count=0, text=""):
        self._count = count
        self._text = text

    async def count(self):
        return self._count

    async def inner_text(self, timeout=3000):
        return self._text


class FakePage:
    def __init__(self, selectors=None, body=""):
        self.selectors = selectors or set()
        self.body = body

    def locator(self, selector):
        if selector == "body":
            return FakeLocator(text=self.body)
        return FakeLocator(count=1 if selector in self.selectors else 0)


def test_captcha_detection_behavior():
    async def run():
        assert await detect_captcha_or_verification(FakePage(body="Please verify you are human"))
        assert await detect_captcha_or_verification(FakePage(selectors={".g-recaptcha"}))
        assert not await detect_captcha_or_verification(FakePage(body="Regular registration form"))
    asyncio.run(run())


def test_analytics_calculations(tmp_path: Path):
    async def run():
        db_path = tmp_path / "bot.sqlite3"
        db = Database(db_path)
        await db.init()
        one = await db.start_attempt(1, "demo")
        await db.finish_attempt(one, AttemptStatus.SUCCESS, manual_interventions=1)
        two = await db.start_attempt(1, "demo")
        await db.finish_attempt(two, AttemptStatus.FAILED, failure_reason="captcha", failure_category="manual", manual_interventions=2)
        assert await db.successful_site_keys_for_user(1) == {"demo"}
        summary = await AnalyticsService(str(db_path)).summary()
        assert summary["total_registration_attempts"] == 2
        assert summary["successful_registrations"] == 1
        assert summary["failed_registrations"] == 1
        assert summary["manual_intervention_count"] == 3
        assert summary["most_used_site"] == "demo"
        assert summary["failure_reasons_by_category"] == {"manual": 1}
        assert "Average completion time" in format_analytics(summary)
    asyncio.run(run())


def test_menu_routing_contains_required_callbacks():
    markup = main_menu()
    callbacks = {button.callback_data for row in markup.inline_keyboard for button in row}
    assert {"register", "register_all", "info", "edit", "sites", "upload_sites", "status", "analytics", "export_logs", "settings", "help", "cancel"}.issubset(callbacks)


def test_profile_edit_sequence_advances_through_fields():
    from types import SimpleNamespace

    from app.bot import (
        EDITING_FIELD_KEY,
        PROFILE_EDIT_QUEUE_KEY,
        next_profile_edit_field,
        remaining_profile_fields_after,
    )
    from app.models import PROFILE_FIELDS

    context = SimpleNamespace(
        user_data={
            PROFILE_EDIT_QUEUE_KEY: remaining_profile_fields_after("first_name"),
            EDITING_FIELD_KEY: "first_name",
        }
    )

    assert next_profile_edit_field(context) == "last_name"
    assert context.user_data[EDITING_FIELD_KEY] == "last_name"
    assert context.user_data[PROFILE_EDIT_QUEUE_KEY][0] == "address_line1"

    while next_profile_edit_field(context):
        pass

    assert EDITING_FIELD_KEY not in context.user_data
    assert PROFILE_EDIT_QUEUE_KEY not in context.user_data
    assert remaining_profile_fields_after(PROFILE_FIELDS[-1]) == []


def test_profile_prompt_marks_optional_fields_as_skippable():
    from app.bot import profile_field_prompt

    assert "optional" in profile_field_prompt("address_line2")
    assert "skip" in profile_field_prompt("password")
    assert "skip" not in profile_field_prompt("first_name")


def test_proxy_response_parsing_accepts_text_and_json_formats():
    from app.proxy import parse_proxy_response

    assert parse_proxy_response("http://user:pass@proxy.example:8080") == {
        "server": "http://proxy.example:8080",
        "username": "user",
        "password": "pass",
    }
    assert parse_proxy_response('{"data":{"proxy":"socks5://proxy.example:1080"}}', "application/json", "data.proxy") == {
        "server": "socks5://proxy.example:1080"
    }
    assert parse_proxy_response('{"server":"https://proxy.example:8443","username":"u","password":"p"}', "application/json") == {
        "server": "https://proxy.example:8443",
        "username": "u",
        "password": "p",
    }


def test_uploaded_site_lists_are_scoped_per_telegram_user():
    from types import SimpleNamespace

    from app.bot import (
        USER_SITE_UPLOADS_KEY,
        enabled_sites_for_user,
        require_site_for_user,
        sites_for_user,
    )
    from app.config import AppConfig, ConfigError
    from app.models import SiteConfig

    config = AppConfig({
        "sites": {
            "global": {
                "name": "Global Site",
                "domain": "global.example",
                "registration_url": "https://global.example/register",
            }
        }
    })
    user_site = SiteConfig(
        key="personal",
        name="Personal Site",
        domain="personal.example",
        registration_url="https://personal.example/register",
    )
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"config": config, USER_SITE_UPLOADS_KEY: {42: {"personal": user_site}}}))

    assert list(sites_for_user(context, 42)) == ["personal"]
    assert list(enabled_sites_for_user(context, 42)) == ["personal"]
    assert require_site_for_user(context, 42, "personal") is user_site
    assert list(sites_for_user(context, 99)) == ["global"]
    assert list(config.sites) == ["global"]

    with pytest.raises(ConfigError):
        require_site_for_user(context, 99, "personal")


def test_apply_sites_upload_does_not_replace_global_config_sites():
    import asyncio
    from types import SimpleNamespace

    from app.bot import SITES_UPLOAD_KEY, USER_SITE_UPLOADS_KEY, apply_sites_upload, sites_for_user
    from app.config import AppConfig

    class FakeMessage:
        def __init__(self):
            self.replies = []

        async def reply_text(self, text, reply_markup=None):
            self.replies.append(text)

    async def run():
        config = AppConfig({
            "sites": {
                "global": {
                    "name": "Global Site",
                    "domain": "global.example",
                    "registration_url": "https://global.example/register",
                }
            }
        })
        context = SimpleNamespace(application=SimpleNamespace(bot_data={"config": config}), user_data={SITES_UPLOAD_KEY: True})
        update = SimpleNamespace(effective_user=SimpleNamespace(id=42), message=FakeMessage())

        await apply_sites_upload(update, context, """
sites:
  personal:
    name: Personal Site
    domain: personal.example
    registration_url: https://personal.example/register
""")

        assert list(config.sites) == ["global"]
        assert list(context.application.bot_data[USER_SITE_UPLOADS_KEY]) == [42]
        assert list(sites_for_user(context, 42)) == ["personal"]
        assert list(sites_for_user(context, 99)) == ["global"]
        assert SITES_UPLOAD_KEY not in context.user_data
        assert "for your account" in update.message.replies[-1]

    asyncio.run(run())
