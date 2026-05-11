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
    assert not profile.is_complete()
    complete = UserProfile(
        telegram_user_id=1,
        first_name="Ada",
        last_name="Lovelace",
        address_line1="1 Algorithm Ave",
        address_line2="Unit 2",
        state_region="CA",
        city="San Francisco",
        postal_code="94105",
        phone_number="5551234567",
        email="ada@example.com",
    )
    assert complete.is_complete()
    assert complete.masked_dict()["email"].startswith("ad***@")


def test_ai_json_parsing_accepts_valid_mapping():
    parsed = parse_ai_mapping('{"mappings":{"#email":{"profile_field":"email","confidence":0.95}}}', {"#email"})
    assert parsed["#email"]["profile_field"] == "email"


def test_ai_json_parsing_rejects_invalid_json_and_unknown_fields():
    with pytest.raises(AIMapperError):
        parse_ai_mapping("not json", {"#email"})
    with pytest.raises(AIMapperError):
        parse_ai_mapping('{"mappings":{"#email":{"profile_field":"password","confidence":1}}}', {"#email"})


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
    assert {"register", "register_all", "info", "edit", "sites", "analytics", "settings", "help", "cancel"}.issubset(callbacks)


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
