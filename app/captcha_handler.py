from __future__ import annotations

CAPTCHA_KEYWORDS = ("captcha", "recaptcha", "hcaptcha", "turnstile", "verification code", "verify you are human", "multi-factor", "mfa", "one-time code", "email verification", "verify your email", "phone verification", "rate limit", "too many requests", "bot detection", "suspicious activity")
CAPTCHA_SELECTORS = [
    "iframe[src*='recaptcha']",
    "iframe[src*='hcaptcha']",
    "iframe[src*='challenges.cloudflare']",
    ".g-recaptcha",
    ".h-captcha",
    "[data-sitekey]",
    "input[name*='captcha' i]",
    "input[name*='otp' i]",
    "input[name*='verification' i]",
]


async def detect_captcha_or_verification(page) -> bool:
    for selector in CAPTCHA_SELECTORS:
        if await page.locator(selector).count() > 0:
            return True
    text = (await page.locator("body").inner_text(timeout=3000)).lower()
    return any(keyword in text for keyword in CAPTCHA_KEYWORDS)
