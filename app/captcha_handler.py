from __future__ import annotations

from typing import Optional

from playwright.async_api import Page
from playwright_recaptcha import recaptchav2, recaptchav3

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


async def detect_captcha_or_verification(page: Page) -> bool:
    """Detect if page contains CAPTCHA or verification challenges."""
    for selector in CAPTCHA_SELECTORS:
        if await page.locator(selector).count() > 0:
            return True
    text = (await page.locator("body").inner_text(timeout=3000)).lower()
    return any(keyword in text for keyword in CAPTCHA_KEYWORDS)


async def solve_recaptcha_v3(page: Page, timeout: float = 30) -> Optional[str]:
    """
    Solve reCAPTCHA v3 using token injection.
    
    Parameters
    ----------
    page : Page
        The Playwright page containing the reCAPTCHA.
    timeout : float, optional
        Solve timeout in seconds, by default 30.
    
    Returns
    -------
    Optional[str]
        The g-recaptcha-response token or None if solving failed.
    """
    try:
        async with recaptchav3.AsyncSolver(page, timeout=timeout) as solver:
            token = await solver.solve_recaptcha(timeout=timeout)
            return token
    except Exception as e:
        return None


async def solve_recaptcha_v2(
    page: Page,
    attempts: int = 5,
    wait: bool = True,
    wait_timeout: float = 30,
) -> Optional[str]:
    """
    Solve reCAPTCHA v2 using token injection method.
    
    Parameters
    ----------
    page : Page
        The Playwright page containing the reCAPTCHA.
    attempts : int, optional
        Number of solve attempts, by default 5.
    wait : bool, optional
        Whether to wait for reCAPTCHA to appear, by default True.
    wait_timeout : float, optional
        Wait timeout in seconds, by default 30.
    
    Returns
    -------
    Optional[str]
        The g-recaptcha-response token or None if solving failed.
    """
    try:
        async with recaptchav2.AsyncSolver(page, attempts=attempts) as solver:
            token = await solver.solve_recaptcha(wait=wait, wait_timeout=wait_timeout)
            return token
    except Exception as e:
        return None


async def handle_recaptcha(page: Page) -> Optional[str]:
    """
    Automatically detect and solve reCAPTCHA.
    
    Attempts to solve reCAPTCHA v3 first, then v2 if v3 fails.
    
    Parameters
    ----------
    page : Page
        The Playwright page to check for reCAPTCHA.
    
    Returns
    -------
    Optional[str]
        The solved reCAPTCHA token or None if no reCAPTCHA found or solving failed.
    """
    # Check if reCAPTCHA is present
    if not await detect_captcha_or_verification(page):
        return None
    
    # Try v3 first (invisible, faster)
    v3_token = await solve_recaptcha_v3(page)
    if v3_token:
        return v3_token
    
    # Fall back to v2 (visible, requires interaction)
    v2_token = await solve_recaptcha_v2(page)
    if v2_token:
        return v2_token
    
    return None
