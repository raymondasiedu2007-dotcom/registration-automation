# reCAPTCHA Solver Implementation

This module provides automatic reCAPTCHA v2 and v3 solving capabilities using Playwright with the token-injection method.

## Architecture

The implementation is organized into two main components:

### reCAPTCHA v3 Solver (`recaptchav3/`)

**Approach:** Token Injection
- Listens for reload responses from Google's reCAPTCHA server
- Extracts the token from the response payload
- No user interaction needed (invisible reCAPTCHA)
- Faster and more reliable

**Files:**
- `base_solver.py` - Abstract base class with common functionality
- `sync_solver.py` - Synchronous implementation (for sync Playwright)
- `async_solver.py` - Asynchronous implementation (for async Playwright)

**Usage:**
```python
from playwright.async_api import async_playwright
from playwright_recaptcha import recaptchav3

async with async_playwright() as playwright:
    browser = await playwright.chromium.launch()
    page = await browser.new_page()
    
    async with recaptchav3.AsyncSolver(page) as solver:
        await page.goto("https://example.com")
        token = await solver.solve_recaptcha()
        print(f"Token: {token}")
```

### reCAPTCHA v2 Solver (`recaptchav2/`)

**Approach:** Token Injection + Checkbox Interaction
- Listens for `userverify` responses
- Extracts tokens from response payloads
- Attempts to click the reCAPTCHA checkbox
- Supports both visible and invisible reCAPTCHA

**Files:**
- `base_solver.py` - Abstract base class
- `sync_solver.py` - Synchronous implementation
- `async_solver.py` - Asynchronous implementation

**Usage:**
```python
from playwright.async_api import async_playwright
from playwright_recaptcha import recaptchav2

async with async_playwright() as playwright:
    browser = await playwright.chromium.launch()
    page = await browser.new_page()
    
    async with recaptchav2.AsyncSolver(page) as solver:
        await page.goto("https://example.com")
        token = await solver.solve_recaptcha(wait=True)
        print(f"Token: {token}")
```

## Integration with captcha_handler.py

The `captcha_handler.py` module provides high-level functions:

### `detect_captcha_or_verification(page: Page) -> bool`
Detects if a page contains any CAPTCHA or verification challenge using pattern matching.

### `solve_recaptcha_v3(page: Page, timeout: float = 30) -> Optional[str]`
Solves reCAPTCHA v3 (invisible).

### `solve_recaptcha_v2(page: Page, attempts: int = 5, wait: bool = True) -> Optional[str]`
Solves reCAPTCHA v2 (visible).

### `handle_recaptcha(page: Page) -> Optional[str]`
Automatically detects and solves any reCAPTCHA (tries v3, then v2).

**Example Usage:**
```python
from app.captcha_handler import handle_recaptcha

async def register():
    async with async_playwright() as playwright:
        page = await playwright.chromium.launch().new_page()
        await page.goto("https://registration.example.com")
        
        # Automatically handle any reCAPTCHA
        token = await handle_recaptcha(page)
        if token:
            # Use token to submit form
            await page.fill("input[name='g-recaptcha-response']", token)
```

## Error Handling

The solver implements the following exceptions (`errors.py`):
- `RecaptchaError` - Base exception for all reCAPTCHA-related errors
- `RecaptchaNotFoundError` - reCAPTCHA element not found
- `RecaptchaSolveError` - Failed to solve reCAPTCHA
- `RecaptchaRateLimitError` - Rate limited by Google
- `RecaptchaTimeoutError` - Solve attempt timed out
- `CapSolverError` - CapSolver API errors (for future image solving)

## Token-Injection Method

The token-injection approach works by:

1. **Response Interception**: Attaches a listener to page responses
2. **Pattern Matching**: Monitors requests to Google's reCAPTCHA endpoints:
   - `/recaptcha/api2/reload` - v3 token responses
   - `/recaptcha/api2/userverify` - v2 token responses
3. **Token Extraction**: Parses the response text for the token using regex
4. **Return**: Returns the token without solving actual CAPTCHAs

This is superior to solving actual CAPTCHAs because:
- ✅ No AI/ML needed for image/audio solving
- ✅ Faster (30 seconds vs 5+ minutes)
- ✅ More reliable (no API dependencies)
- ✅ No rate limiting from CAPTCHA solving services

## Configuration

### Environment Variables
- `CAPSOLVER_API_KEY` - (Optional) CapSolver API key for future image solving

### Solver Parameters

**reCAPTCHA v3:**
- `timeout` - Solve timeout in seconds (default: 30)

**reCAPTCHA v2:**
- `attempts` - Number of solve attempts (default: 5)
- `wait` - Whether to wait for reCAPTCHA to appear (default: True with timeout 30s)
- `image_challenge` - (Unused in token-injection mode)

## Performance

Expected solve times:
- **v3 (Invisible)**: 1-5 seconds
- **v2 (Visible)**: 5-15 seconds

These times depend on:
- Browser launch time
- Network latency
- Google's response times
- Page load time

## Limitations & Future Enhancements

### Current Limitations:
- Token-injection method doesn't solve actual CAPTCHAs
- Requires reCAPTCHA to be present on page

### Future Enhancements:
- CapSolver integration for v2 image challenges
- Audio transcription using speech_recognition
- Support for hCaptcha and Turnstile
- Headless browser optimization
- Proxy rotation support

## Testing

To test the implementation:

```python
import asyncio
from playwright.async_api import async_playwright
from app.captcha_handler import handle_recaptcha

async def test():
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        page = await browser.new_page()
        
        # Test with Google's reCAPTCHA demo
        await page.goto("https://www.google.com/recaptcha/api2/demo")
        token = await handle_recaptcha(page)
        print(f"Solved token: {token}")
        
        await browser.close()

asyncio.run(test())
```

## References

- [Playwright Documentation](https://playwright.dev/)
- [Google reCAPTCHA](https://www.google.com/recaptcha/about/)
- [CapSolver Documentation](https://docs.capsolver.com/)
