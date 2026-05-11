"""Asynchronous reCAPTCHA v2 solver using token injection."""

import re
import time
from typing import Any, Optional

from playwright.async_api import Page, Response

from ..errors import (
    RecaptchaNotFoundError,
    RecaptchaRateLimitError,
    RecaptchaSolveError,
)
from .base_solver import BaseSolver


class AsyncSolver(BaseSolver[Page]):
    """
    A class for solving reCAPTCHA v2 asynchronously using token injection.

    Parameters
    ----------
    page : Page
        The Playwright page to solve the reCAPTCHA on.
    attempts : int, optional
        The number of solve attempts, by default 5.
    capsolver_api_key : Optional[str], optional
        The CapSolver API key, by default None.
    """

    async def __aenter__(self) -> "AsyncSolver":
        return self

    async def __aexit__(self, *_: Any) -> None:
        self.close()

    async def _response_callback(self, response: Response) -> None:
        """
        The callback for intercepting payload and userverify responses.

        Parameters
        ----------
        response : Response
            The response.
        """
        # Capture payload response for token extraction
        if (
            re.search("/recaptcha/(api2|enterprise)/payload", response.url) is not None
            and self._payload_response is None
        ):
            self._payload_response = response
        # Capture userverify response containing token
        elif (
            re.search("/recaptcha/(api2|enterprise)/userverify", response.url)
            is not None
        ):
            response_text = await response.text()
            token_match = re.search('"uvresp","(.*?)"', response_text)
            if token_match is not None:
                self._token = token_match.group(1)

    async def solve_recaptcha(
        self,
        *,
        attempts: Optional[int] = None,
        wait: bool = False,
        wait_timeout: float = 30,
        image_challenge: bool = False,
    ) -> str:
        """
        Solve the reCAPTCHA and return the `g-recaptcha-response` token using token injection.

        Parameters
        ----------
        attempts : Optional[int], optional
            The number of solve attempts, by default 5.
        wait : bool, optional
            Whether to wait for the reCAPTCHA to appear, by default False.
        wait_timeout : float, optional
            The amount of time in seconds to wait for the reCAPTCHA to appear,
            by default 30. Only used if `wait` is True.
        image_challenge : bool, optional
            Ignored in token-injection mode.

        Returns
        -------
        str
            The `g-recaptcha-response` token.

        Raises
        ------
        RecaptchaNotFoundError
            If the reCAPTCHA was not found.
        RecaptchaRateLimitError
            If the reCAPTCHA rate limit has been exceeded.
        RecaptchaSolveError
            If the reCAPTCHA could not be solved.
        """
        self._token = None
        attempts = attempts or self._attempts

        # Wait for reCAPTCHA to appear if requested
        if wait:
            start_time = time.time()
            recaptcha_found = False
            while time.time() - start_time < wait_timeout:
                iframe_count = await self._page.locator('iframe[src*="recaptcha"]').count()
                if iframe_count > 0:
                    recaptcha_found = True
                    break
                await self._page.wait_for_timeout(250)

            if not recaptcha_found:
                raise RecaptchaNotFoundError("reCAPTCHA not found within timeout")

        # Try to find and interact with reCAPTCHA checkbox
        try:
            checkbox = self._page.locator('div[role="checkbox"]').first
            if await checkbox.is_visible():
                await checkbox.click()
        except Exception:
            # reCAPTCHA might be invisible or already solved
            pass

        # Wait for token to be captured from response interception
        start_time = time.time()
        timeout = 30.0  # Token injection timeout
        
        while self._token is None:
            if time.time() - start_time >= timeout:
                raise RecaptchaSolveError("Failed to capture reCAPTCHA token")
            await self._page.wait_for_timeout(250)

        return self._token
