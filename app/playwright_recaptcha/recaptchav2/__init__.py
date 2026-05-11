"""reCAPTCHA v2 solver package."""

from .sync_solver import SyncSolver
from .async_solver import AsyncSolver

__all__ = ["SyncSolver", "AsyncSolver"]
