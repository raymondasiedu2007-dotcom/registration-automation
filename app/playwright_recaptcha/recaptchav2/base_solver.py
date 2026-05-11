"""Base class for reCAPTCHA v2 solvers."""

import os
import re
from abc import ABC, abstractmethod
from typing import Any, Dict, Generic, Optional, TypeVar, Union

from playwright.sync_api import APIResponse, Page, Response

PageT = TypeVar("PageT", bound=Page)


class BaseSolver(ABC, Generic[PageT]):
    """
    The base class for reCAPTCHA v2 solvers.

    Parameters
    ----------
    page : PageT
        The Playwright page to solve the reCAPTCHA on.
    attempts : int, optional
        The number of solve attempts, by default 5.
    capsolver_api_key : Optional[str], optional
        The CapSolver API key, by default None.
        If None, the `CAPSOLVER_API_KEY` environment variable will be used.
    """

    def __init__(
        self, page: PageT, *, attempts: int = 5, capsolver_api_key: Optional[str] = None
    ) -> None:
        self._page = page
        self._attempts = attempts
        self._capsolver_api_key = capsolver_api_key or os.getenv("CAPSOLVER_API_KEY")

        self._token: Optional[str] = None
        self._payload_response: Union[APIResponse, Response, None] = None
        self._page.on("response", self._response_callback)

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}(page={self._page!r}, "
            f"attempts={self._attempts!r}, "
            f"capsolver_api_key={self._capsolver_api_key!r})"
        )

    def close(self) -> None:
        """Remove the response listener."""
        try:
            self._page.remove_listener("response", self._response_callback)
        except KeyError:
            pass

    @abstractmethod
    def _response_callback(self, response: Response) -> None:
        """
        The callback for intercepting payload and userverify responses.

        Parameters
        ----------
        response : Response
            The response.
        """

    @abstractmethod
    def solve_recaptcha(
        self,
        *,
        attempts: Optional[int] = None,
        wait: bool = False,
        wait_timeout: float = 30,
        image_challenge: bool = False,
    ) -> str:
        """
        Solve the reCAPTCHA and return the `g-recaptcha-response` token.

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
            Whether to solve the image challenge, by default False.

        Returns
        -------
        str
            The `g-recaptcha-response` token.

        Raises
        ------
        CapSolverError
            If the CapSolver API returned an error.
        RecaptchaNotFoundError
            If the reCAPTCHA was not found.
        RecaptchaRateLimitError
            If the reCAPTCHA rate limit has been exceeded.
        RecaptchaSolveError
            If the reCAPTCHA could not be solved.
        """
