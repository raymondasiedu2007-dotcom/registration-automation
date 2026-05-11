from __future__ import annotations

import asyncio
from pathlib import Path
import re
from typing import Awaitable, Callable

from playwright.async_api import Page, async_playwright

from app.ai_mapper import AIFormMapper
from app.captcha_handler import detect_captcha_or_verification
from app.form_extractor import extract_form_fields
from app.models import FieldMetadata, SiteConfig, UserProfile
from app.proxy import ProxyRotator
from app.safety import SafetyError, validate_allowed_url

ManualCallback = Callable[[str, str], Awaitable[None]]
ApprovalCallback = Callable[[str], Awaitable[bool]]


KEYWORD_MAP = {
    "first_name": ("first", "given"),
    "last_name": ("last", "family", "surname"),
    "address_line1": ("address", "street", "line 1"),
    "address_line2": ("address 2", "apt", "suite", "line 2"),
    "state_region": ("state", "region", "province"),
    "city": ("city", "town"),
    "postal_code": ("zip", "postal"),
    "phone_number": ("phone", "mobile", "tel"),
    "email": ("email", "e-mail"),
}


class PlaywrightRegistrationRunner:
    def __init__(
        self,
        screenshots_dir: str = "screenshots",
        headless: bool = True,
        ai_mapper: AIFormMapper | None = None,
        proxy_rotator: ProxyRotator | None = None,
    ) -> None:
        self.screenshots_dir = Path(screenshots_dir)
        self.headless = headless
        self.ai_mapper = ai_mapper
        self.proxy_rotator = proxy_rotator
        self.screenshots_dir.mkdir(parents=True, exist_ok=True)

    async def run(
        self,
        site: SiteConfig,
        profile: UserProfile,
        manual_callback: ManualCallback,
        approval_callback: ApprovalCallback,
    ) -> dict[str, object]:
        validate_allowed_url(site.registration_url, site)
        manual_interventions = 0
        async with async_playwright() as playwright:
            launch_options: dict[str, object] = {"headless": self.headless}
            if self.proxy_rotator and self.proxy_rotator.enabled:
                proxy = await self.proxy_rotator.next_proxy()
                if proxy:
                    launch_options["proxy"] = proxy
            browser = await playwright.chromium.launch(**launch_options)
            page = await browser.new_page()
            try:
                page.on("framenavigated", lambda frame: validate_allowed_url(frame.url, site) if frame == page.main_frame and frame.url != "about:blank" else None)
                await page.goto(site.registration_url, wait_until="domcontentloaded")
                validate_allowed_url(page.url, site)
                if await detect_captcha_or_verification(page):
                    manual_interventions += 1
                    screenshot = await self._screenshot(page, site.key, "manual-required")
                    await manual_callback("Manual action required. Please complete the CAPTCHA/verification in the browser, then press Continue.", screenshot)
                    await self._wait_for_manual_clear(page)
                fields = await extract_form_fields(page)
                mappings = await self._build_mappings(site, fields)
                low_confidence = [selector for selector, item in mappings.items() if float(item.get("confidence", 1)) < 0.8]
                if low_confidence:
                    manual_interventions += 1
                    await manual_callback(f"Please confirm low-confidence field mappings: {', '.join(low_confidence)}", "")
                await self._fill_fields(page, fields, mappings, profile)
                if await detect_captcha_or_verification(page):
                    manual_interventions += 1
                    screenshot = await self._screenshot(page, site.key, "manual-required-after-fill")
                    await manual_callback("Manual action required. Please complete the CAPTCHA/verification in the browser, then press Continue.", screenshot)
                    await self._wait_for_manual_clear(page)
                final_screenshot = await self._screenshot(page, site.key, "before-submit")
                approved = await approval_callback(final_screenshot)
                if not approved:
                    return {"status": "cancelled", "manual_interventions": manual_interventions, "screenshot": final_screenshot}
                await self._click_submit(page, site)
                return {"status": "success", "manual_interventions": manual_interventions, "screenshot": final_screenshot}
            except Exception as exc:
                screenshot = await self._screenshot(page, site.key, "error")
                if isinstance(exc, SafetyError):
                    raise
                return {"status": "failed", "manual_interventions": manual_interventions, "failure_reason": str(exc), "screenshot": screenshot}
            finally:
                await browser.close()

    async def _build_mappings(self, site: SiteConfig, fields: list[FieldMetadata]) -> dict[str, dict[str, object]]:
        mappings: dict[str, dict[str, object]] = {}
        for selector, profile_field in site.field_mappings.items():
            mappings[selector] = {"profile_field": profile_field, "confidence": 1.0}
        if self.ai_mapper and self.ai_mapper.enabled:
            mappings.update(await self.ai_mapper.map_fields(fields))
        for field in fields:
            if field.selector not in mappings:
                guessed = guess_profile_field(field)
                if guessed:
                    mappings[field.selector] = {"profile_field": guessed, "confidence": 0.7}
        return mappings

    async def _fill_fields(self, page: Page, fields: list[FieldMetadata], mappings: dict[str, dict[str, object]], profile: UserProfile) -> None:
        field_by_selector = {field.selector: field for field in fields}
        for selector, mapping in mappings.items():
            profile_field = str(mapping["profile_field"])
            value = getattr(profile, profile_field, "")
            if not value:
                continue
            field = field_by_selector.get(selector)
            locator = page.locator(selector).first
            tag = field.tag if field else "input"
            input_type = (field.input_type or "text").lower() if field else "text"
            if tag == "select":
                await locator.select_option(label=value)
            elif input_type in {"checkbox", "radio"}:
                await locator.check()
            else:
                await locator.fill(value)

    async def _click_submit(self, page: Page, site: SiteConfig) -> None:
        if site.submit_selector:
            await page.locator(site.submit_selector).first.click()
            return
        await page.get_by_role("button", name=re.compile(r"submit|register|sign up|create", re.I)).click()

    async def _screenshot(self, page: Page, site_key: str, suffix: str) -> str:
        path = self.screenshots_dir / f"{site_key}-{suffix}.png"
        await page.screenshot(path=str(path), full_page=True)
        return str(path)

    async def _wait_for_manual_clear(self, page: Page) -> None:
        for _ in range(120):
            if not await detect_captcha_or_verification(page):
                return
            await asyncio.sleep(1)


def guess_profile_field(field: FieldMetadata) -> str | None:
    haystack = " ".join(str(value or "") for value in [field.name, field.label, field.placeholder, field.aria_label, field.nearby_text, field.input_type]).lower()
    for profile_field, keywords in KEYWORD_MAP.items():
        if any(keyword in haystack for keyword in keywords):
            return profile_field
    return None
