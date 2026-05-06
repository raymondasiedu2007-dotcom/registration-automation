from __future__ import annotations

CAPTCHA_KEYWORDS = ("captcha", "recaptcha", "hcaptcha", "turnstile", "verification code", "verify you are human")
CAPTCHA_SELECTORS = [
    "iframe[src*='recaptcha']",
    "iframe[src*='hcaptcha']",
    "iframe[src*='challenges.cloudflare']",
    ".g-recaptcha",
    ".h-captcha",
    "[data-sitekey]",
    "input[name*='captcha' i]",
]


async def detect_captcha_or_verification(page) -> bool:
    for selector in CAPTCHA_SELECTORS:
        if await page.locator(selector).count() > 0:
            return True
    text = (await page.locator("body").inner_text(timeout=3000)).lower()
    return any(keyword in text for keyword in CAPTCHA_KEYWORDS)
